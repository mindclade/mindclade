use std::{
    fmt, io,
    path::{Path, PathBuf},
    time::Duration,
};

use mindclade_internal_sdk::{
    ArtifactRef, CallOptions, Client, Error, ErrorKind, EventRejectedError, Identity,
    decode_job_requested_delivery,
};
use sha2::{Digest, Sha256};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const DEFAULT_ARTIFACT_LIMIT: u64 = 16 << 20;

/// A safe worker-boundary error. Server payloads and credentials are never rendered.
#[derive(Debug)]
pub enum AssignmentError {
    Rejected(&'static str),
    Event(EventRejectedError),
    Deadline,
    Sdk(Error),
    Io(io::Error),
}

impl AssignmentError {
    #[must_use]
    pub fn sdk_kind(&self) -> Option<ErrorKind> {
        match self {
            Self::Sdk(error) => Some(error.kind()),
            Self::Rejected(_) | Self::Event(_) | Self::Deadline | Self::Io(_) => None,
        }
    }
}

impl fmt::Display for AssignmentError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Rejected(message) => write!(formatter, "assignment rejected: {message}"),
            Self::Event(error) => write!(formatter, "assignment event rejected: {error}"),
            Self::Deadline => formatter.write_str("assignment materialization deadline expired"),
            Self::Sdk(error) => error.fmt(formatter),
            Self::Io(_) => formatter.write_str("assignment local I/O failed"),
        }
    }
}

impl std::error::Error for AssignmentError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Sdk(error) => Some(error),
            Self::Event(error) => Some(error),
            Self::Io(error) => Some(error),
            Self::Rejected(_) | Self::Deadline => None,
        }
    }
}

impl From<Error> for AssignmentError {
    fn from(value: Error) -> Self {
        Self::Sdk(value)
    }
}

impl From<io::Error> for AssignmentError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<EventRejectedError> for AssignmentError {
    fn from(value: EventRejectedError) -> Self {
        Self::Event(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MaterializedAssignment {
    pub event_id: String,
    pub job_id: String,
    pub configuration_path: PathBuf,
    pub input_path: Option<PathBuf>,
}

/// Decodes and verifies the registered exact-version event before service I/O.
///
/// # Errors
///
/// Returns an error for malformed, unknown, non-canonical, or cross-scope deliveries.
pub fn decode_job_requested(
    serialized: &[u8],
    tenant_id: &str,
    project_id: &str,
) -> Result<(String, String), AssignmentError> {
    let decoded = decode_job_requested_delivery(serialized, tenant_id, project_id)?;
    Ok((decoded.event_id, decoded.job_id))
}

/// Bounded worker intake that resolves durable state and content only via the private SDK.
pub struct SourceFetcher {
    client: Client,
    identity: Identity,
    rpc_timeout: Duration,
    maximum_artifact_bytes: u64,
}

impl SourceFetcher {
    /// Creates a fetcher with bounded per-RPC and artifact policies.
    ///
    /// # Errors
    ///
    /// Returns an error when client and worker identity differ or a bound is
    /// zero or unreasonably large.
    pub fn new(
        client: Client,
        identity: Identity,
        rpc_timeout: Duration,
        maximum_artifact_bytes: Option<u64>,
    ) -> Result<Self, AssignmentError> {
        if client.identity() != &identity {
            return Err(AssignmentError::Rejected(
                "worker identity does not match SDK client scope",
            ));
        }
        if rpc_timeout.is_zero() || rpc_timeout > Duration::from_mins(5) {
            return Err(AssignmentError::Rejected("RPC timeout is outside policy"));
        }
        let maximum_artifact_bytes = maximum_artifact_bytes.unwrap_or(DEFAULT_ARTIFACT_LIMIT);
        if maximum_artifact_bytes == 0 || maximum_artifact_bytes > 1 << 30 {
            return Err(AssignmentError::Rejected(
                "artifact byte limit is outside policy",
            ));
        }
        Ok(Self {
            client,
            identity,
            rpc_timeout,
            maximum_artifact_bytes,
        })
    }

    /// Materializes generation-pinned artifacts under a job-specific directory.
    ///
    /// # Errors
    ///
    /// Returns a normalized SDK, validation, deadline, or local I/O error.
    pub async fn materialize(
        &self,
        serialized_envelope: &[u8],
        destination: &Path,
        total_timeout: Duration,
    ) -> Result<MaterializedAssignment, AssignmentError> {
        if total_timeout.is_zero() || total_timeout > Duration::from_mins(10) {
            return Err(AssignmentError::Rejected(
                "total worker timeout is outside policy",
            ));
        }
        let future =
            Box::pin(self.materialize_inner(serialized_envelope, destination, total_timeout));
        tokio::time::timeout(total_timeout, future)
            .await
            .map_err(|_| AssignmentError::Deadline)?
    }

    async fn materialize_inner(
        &self,
        serialized_envelope: &[u8],
        destination: &Path,
        total_timeout: Duration,
    ) -> Result<MaterializedAssignment, AssignmentError> {
        let decoded = decode_job_requested_delivery(
            serialized_envelope,
            self.identity.tenant_id(),
            self.identity.project_id(),
        )?;
        let options = CallOptions::new()
            .with_timeout(self.rpc_timeout.min(total_timeout))?
            .with_request_id(decoded.request_id.clone())?
            .with_trace_id(decoded.trace_id.clone())?;
        let job = self
            .client
            .jobs()
            .get(&decoded.job_id, "", options.clone())
            .await?;
        let configuration = job.configuration.as_ref().ok_or(AssignmentError::Rejected(
            "durable job omitted its configuration",
        ))?;
        if configuration.digest != decoded.configuration_digest {
            return Err(AssignmentError::Rejected(
                "durable job configuration does not match its immutable event",
            ));
        }
        let job_leaf = decoded
            .job_id
            .strip_prefix("jobs/")
            .ok_or(AssignmentError::Rejected("job identity is not canonical"))?;
        let root = destination.join(job_leaf);
        tokio::fs::create_dir_all(&root).await?;
        let configuration_path = root.join("configuration.artifact");
        Box::pin(self.download(configuration, &configuration_path, options.clone())).await?;
        let input_path = if let Some(input) = job.input.as_ref() {
            let path = root.join("input.artifact");
            Box::pin(self.download(input, &path, options)).await?;
            Some(path)
        } else {
            None
        };
        Ok(MaterializedAssignment {
            event_id: decoded.event_id,
            job_id: decoded.job_id,
            configuration_path,
            input_path,
        })
    }

    async fn download(
        &self,
        artifact: &ArtifactRef,
        destination: &Path,
        options: CallOptions,
    ) -> Result<(), AssignmentError> {
        let size = u64::try_from(artifact.size_bytes)
            .map_err(|_| AssignmentError::Rejected("artifact size is invalid"))?;
        if size > self.maximum_artifact_bytes || !valid_digest(&artifact.digest) {
            return Err(AssignmentError::Rejected("artifact exceeds intake policy"));
        }
        match tokio::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(destination)
            .await
        {
            Ok(mut file) => {
                let mut guard = PartialFile::new(destination);
                self.client
                    .artifacts()
                    .download(artifact, &mut file, options)
                    .await?;
                file.flush().await?;
                file.sync_all().await?;
                guard.commit();
                Ok(())
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                let digest =
                    Box::pin(file_digest(destination, self.maximum_artifact_bytes)).await?;
                if digest == artifact.digest {
                    Ok(())
                } else {
                    Err(AssignmentError::Rejected(
                        "existing worker artifact has a different digest",
                    ))
                }
            }
            Err(error) => Err(error.into()),
        }
    }
}

struct PartialFile<'a> {
    path: &'a Path,
    committed: bool,
}

impl<'a> PartialFile<'a> {
    fn new(path: &'a Path) -> Self {
        Self {
            path,
            committed: false,
        }
    }

    fn commit(&mut self) {
        self.committed = true;
    }
}

impl Drop for PartialFile<'_> {
    fn drop(&mut self) {
        if !self.committed {
            let _ = std::fs::remove_file(self.path);
        }
    }
}

async fn file_digest(path: &Path, maximum: u64) -> Result<String, AssignmentError> {
    let metadata = tokio::fs::metadata(path).await?;
    if metadata.len() > maximum {
        return Err(AssignmentError::Rejected(
            "existing worker artifact exceeds policy",
        ));
    }
    let mut file = tokio::fs::File::open(path).await?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 64 << 10].into_boxed_slice();
    loop {
        let read = file.read(&mut buffer).await?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("sha256:{:x}", digest.finalize()))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

#[cfg(test)]
mod tests {
    use std::sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    };

    use mindclade_internal_sdk::{
        ArtifactRef, Config, Identity, Job, RecordingTransport, RpcTransport,
        testing::{
            ScriptedJobArtifactTransport, artifact_fixture, job_fixture,
            job_requested_delivery_fixture,
        },
    };
    use tonic::Code;

    use super::*;

    static TEST_SEQUENCE: AtomicU64 = AtomicU64::new(1);

    type AssignmentFixture = (Vec<u8>, Job, Vec<(ArtifactRef, Vec<u8>)>);

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let sequence = TEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "mindclade-ingestion-worker-{}-{sequence}",
                std::process::id()
            ));
            std::fs::create_dir(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn fixture(configuration_content: &[u8], input_content: &[u8]) -> AssignmentFixture {
        let configuration = artifact_fixture(configuration_content, "application/json");
        let input = artifact_fixture(input_content, "application/json");
        let envelope =
            job_requested_delivery_fixture(&configuration.digest, "tenant-1", "project-1", 1, None);
        let job = job_fixture(
            "tenant-1",
            "project-1",
            configuration.clone(),
            Some(input.clone()),
        );
        (
            envelope,
            job,
            vec![
                (configuration, configuration_content.to_vec()),
                (input, input_content.to_vec()),
            ],
        )
    }

    fn client(transport: Arc<dyn RpcTransport>) -> Client {
        let identity = Identity::new("tenant-1", "project-1", "ingestion-worker-1").unwrap();
        let config = Config::local_insecure_builder(identity).build().unwrap();
        Client::with_transport(config, transport)
    }

    #[tokio::test]
    async fn routes_verified_assignment_through_sdk_and_reuses_files() {
        let configuration = br#"{"source":"pdb"}"#;
        let input = b"manifest";
        let (envelope, job, artifacts) = fixture(configuration, input);
        let fake = Arc::new(ScriptedJobArtifactTransport::new(job, artifacts));
        let recording = Arc::new(RecordingTransport::new(fake));
        let fetcher = SourceFetcher::new(
            client(recording.clone()),
            Identity::new("tenant-1", "project-1", "ingestion-worker-1").unwrap(),
            Duration::from_secs(1),
            None,
        )
        .unwrap();
        let destination = TestDir::new();
        let result =
            Box::pin(fetcher.materialize(&envelope, &destination.0, Duration::from_secs(2)))
                .await
                .unwrap();
        assert_eq!(
            tokio::fs::read(result.configuration_path).await.unwrap(),
            configuration
        );
        assert_eq!(
            tokio::fs::read(result.input_path.unwrap()).await.unwrap(),
            input
        );
        Box::pin(fetcher.materialize(&envelope, &destination.0, Duration::from_secs(2)))
            .await
            .unwrap();
        let methods = recording
            .calls()
            .into_iter()
            .map(|call| call.method)
            .collect::<Vec<_>>();
        assert_eq!(
            methods,
            [
                "/mindclade.internal.job.v1.JobService/GetJob",
                "/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact",
                "/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact",
                "/mindclade.internal.job.v1.JobService/GetJob",
            ]
        );
    }

    #[tokio::test]
    async fn preserves_sdk_error_classification() {
        let (envelope, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> = Arc::new(
            ScriptedJobArtifactTransport::new(job, artifacts)
                .failing_get_job(Code::PermissionDenied),
        );
        let fetcher = SourceFetcher::new(
            client(transport),
            Identity::new("tenant-1", "project-1", "ingestion-worker-1").unwrap(),
            Duration::from_secs(1),
            None,
        )
        .unwrap();
        let destination = TestDir::new();
        let error =
            Box::pin(fetcher.materialize(&envelope, &destination.0, Duration::from_secs(2)))
                .await
                .unwrap_err();
        assert_eq!(error.sdk_kind(), Some(ErrorKind::Remote));
        assert!(!error.to_string().contains("redacted fake failure"));
    }

    #[tokio::test]
    async fn total_deadline_cancels_blocked_transport() {
        let (envelope, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> =
            Arc::new(ScriptedJobArtifactTransport::new(job, artifacts).blocking_get_job());
        let fetcher = SourceFetcher::new(
            client(transport),
            Identity::new("tenant-1", "project-1", "ingestion-worker-1").unwrap(),
            Duration::from_secs(1),
            None,
        )
        .unwrap();
        let destination = TestDir::new();
        let error =
            Box::pin(fetcher.materialize(&envelope, &destination.0, Duration::from_millis(5)))
                .await
                .unwrap_err();
        assert!(
            matches!(error, AssignmentError::Deadline)
                || error.sdk_kind() == Some(ErrorKind::DeadlineExceeded)
        );
    }

    #[test]
    fn rejects_identity_that_does_not_match_the_sdk_client() {
        let (_, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> =
            Arc::new(ScriptedJobArtifactTransport::new(job, artifacts));
        let result = SourceFetcher::new(
            client(transport),
            Identity::new("other-tenant", "project-1", "ingestion-worker-1").unwrap(),
            Duration::from_secs(1),
            None,
        );
        assert!(matches!(
            result,
            Err(AssignmentError::Rejected(
                "worker identity does not match SDK client scope"
            ))
        ));
    }

    #[test]
    fn unknown_versions_fail_before_service_io() {
        let (_, job, _) = fixture(b"config", b"input");
        let envelope = job_requested_delivery_fixture(
            &job.configuration.unwrap().digest,
            "tenant-1",
            "project-1",
            2,
            None,
        );
        let error = decode_job_requested(&envelope, "tenant-1", "project-1").unwrap_err();
        assert!(matches!(error, AssignmentError::Event(_)));
    }
}
