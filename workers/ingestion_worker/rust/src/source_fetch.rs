use std::{
    fmt, io,
    path::{Path, PathBuf},
};

use mindclade_internal_sdk::{
    ArtifactRef, CallOptions, Client, Error, ErrorKind, EventRejectedError, Identity,
    decode_job_requested_delivery,
};
use sha2::{Digest, Sha256};
use tokio::io::AsyncReadExt;

const DEFAULT_ARTIFACT_LIMIT: u64 = 16 << 20;

/// A safe worker-boundary error. Server payloads and credentials are never rendered.
///
/// Remote failures are never reclassified here: the SDK error hierarchy stays
/// authoritative and is reachable through [`AssignmentError::sdk_kind`],
/// [`AssignmentError::stable_code`], and [`AssignmentError::is_retryable`].
/// The remaining variants describe only conditions the SDK does not model:
/// local intake policy, event-envelope rejection, and worker-owned file I/O.
#[derive(Debug)]
pub enum AssignmentError {
    Rejected(&'static str),
    Event(EventRejectedError),
    Sdk(Error),
    Io(io::Error),
}

impl AssignmentError {
    /// The SDK's stable failure classification, when the failure came from the SDK.
    #[must_use]
    pub fn sdk_kind(&self) -> Option<ErrorKind> {
        match self {
            Self::Sdk(error) => Some(error.kind()),
            Self::Rejected(_) | Self::Event(_) | Self::Io(_) => None,
        }
    }

    /// The SDK's stable, log-safe classification code for an SDK failure.
    ///
    /// The value is pinned to the SDK error hierarchy and never derived from
    /// remote text, so it is safe to record and safe to branch on.
    #[must_use]
    pub fn stable_code(&self) -> Option<&'static str> {
        match self {
            Self::Sdk(error) => Some(error.stable_code()),
            Self::Rejected(_) | Self::Event(_) | Self::Io(_) => None,
        }
    }

    /// The SDK's single retry-eligibility predicate for this failure.
    ///
    /// The worker never derives retryability from a transport status of its
    /// own; a local rejection, a rejected event, and local I/O are all
    /// terminal for this delivery.
    #[must_use]
    pub fn is_retryable(&self) -> bool {
        match self {
            Self::Sdk(error) => error.is_retryable(),
            Self::Rejected(_) | Self::Event(_) | Self::Io(_) => false,
        }
    }
}

impl fmt::Display for AssignmentError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Rejected(message) => write!(formatter, "assignment rejected: {message}"),
            Self::Event(error) => write!(formatter, "assignment event rejected: {error}"),
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
            Self::Rejected(_) => None,
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
///
/// Deadlines, retries, and correlation metadata are the SDK's: every call
/// carries the delivery's request and trace identifiers and inherits the
/// deadline configured on the client's [`mindclade_internal_sdk::Config`]. The
/// worker layers no timer of its own over the facade.
pub struct SourceFetcher {
    client: Client,
    identity: Identity,
    maximum_artifact_bytes: u64,
}

impl SourceFetcher {
    /// Creates a fetcher with a bounded artifact intake policy.
    ///
    /// # Errors
    ///
    /// Returns an error when client and worker identity differ or the byte
    /// bound is zero or unreasonably large.
    pub fn new(
        client: Client,
        identity: Identity,
        maximum_artifact_bytes: Option<u64>,
    ) -> Result<Self, AssignmentError> {
        if client.identity() != &identity {
            return Err(AssignmentError::Rejected(
                "worker identity does not match SDK client scope",
            ));
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
            maximum_artifact_bytes,
        })
    }

    /// Materializes generation-pinned artifacts under a job-specific directory.
    ///
    /// # Errors
    ///
    /// Returns a normalized SDK, validation, or local I/O error. A deadline is
    /// surfaced as the SDK's own `DeadlineExceeded` classification.
    pub async fn materialize(
        &self,
        serialized_envelope: &[u8],
        destination: &Path,
    ) -> Result<MaterializedAssignment, AssignmentError> {
        let decoded = decode_job_requested_delivery(
            serialized_envelope,
            self.identity.tenant_id(),
            self.identity.project_id(),
        )?;
        let options = CallOptions::new()
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

    /// Publishes one artifact through the SDK's verified download-and-publish
    /// helper, reusing an already-materialized file with the same digest.
    async fn download(
        &self,
        artifact: &ArtifactRef,
        destination: &Path,
        options: CallOptions,
    ) -> Result<(), AssignmentError> {
        // Only the worker's own intake cap lives here. Digest shape, negative
        // sizes, offsets, chunk digests, and the full-content digest are all
        // verified inside the SDK download path.
        let size = u64::try_from(artifact.size_bytes)
            .map_err(|_| AssignmentError::Rejected("artifact size is invalid"))?;
        if size > self.maximum_artifact_bytes {
            return Err(AssignmentError::Rejected("artifact exceeds intake policy"));
        }
        if tokio::fs::try_exists(destination).await? {
            return Box::pin(self.reuse(artifact, destination)).await;
        }
        match self
            .client
            .artifacts()
            .download_file(artifact, destination, options)
            .await
        {
            Ok(_) => Ok(()),
            // A racing writer published first. The SDK never overwrites, so
            // this is the same idempotent case as the pre-check above.
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                Box::pin(self.reuse(artifact, destination)).await
            }
            Err(error) => Err(error.into()),
        }
    }

    async fn reuse(
        &self,
        artifact: &ArtifactRef,
        destination: &Path,
    ) -> Result<(), AssignmentError> {
        let digest = file_digest(destination, self.maximum_artifact_bytes).await?;
        if digest == artifact.digest {
            Ok(())
        } else {
            Err(AssignmentError::Rejected(
                "existing worker artifact has a different digest",
            ))
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

#[cfg(test)]
mod tests {
    use std::{
        sync::{
            Arc,
            atomic::{AtomicU64, Ordering},
        },
        time::Duration,
    };

    use mindclade_internal_sdk::{
        ArtifactRef, Config, Identity, Job, RecordingTransport, RetryPolicy, RpcTransport,
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

    /// Builds a client whose SDK-owned deadline and retry budget are the only
    /// ones in play; the worker adds neither.
    fn client_with(transport: Arc<dyn RpcTransport>, rpc_timeout: Duration) -> Client {
        let identity = Identity::new("tenant-1", "project-1", "ingestion-worker-1").unwrap();
        let config = Config::local_insecure_builder(identity)
            .default_rpc_timeout(rpc_timeout)
            .retry_policy(
                RetryPolicy::new(1, Duration::from_millis(1), Duration::from_millis(2)).unwrap(),
            )
            .build()
            .unwrap();
        Client::with_transport(config, transport)
    }

    fn client(transport: Arc<dyn RpcTransport>) -> Client {
        client_with(transport, Duration::from_secs(2))
    }

    fn fetcher(client: Client) -> SourceFetcher {
        SourceFetcher::new(
            client,
            Identity::new("tenant-1", "project-1", "ingestion-worker-1").unwrap(),
            None,
        )
        .unwrap()
    }

    #[tokio::test]
    async fn routes_verified_assignment_through_sdk_and_reuses_files() {
        let configuration = br#"{"source":"pdb"}"#;
        let input = b"manifest";
        let (envelope, job, artifacts) = fixture(configuration, input);
        let fake = Arc::new(ScriptedJobArtifactTransport::new(job, artifacts));
        let recording = Arc::new(RecordingTransport::new(fake));
        let fetcher = fetcher(client(recording.clone()));
        let destination = TestDir::new();
        let result = Box::pin(fetcher.materialize(&envelope, &destination.0))
            .await
            .unwrap();
        assert_eq!(
            tokio::fs::read(&result.configuration_path).await.unwrap(),
            configuration
        );
        assert_eq!(
            tokio::fs::read(result.input_path.clone().unwrap())
                .await
                .unwrap(),
            input
        );
        Box::pin(fetcher.materialize(&envelope, &destination.0))
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

    /// The SDK's verified publisher owns file creation, so a materialized
    /// artifact carries the SDK's restrictive mode and leaves no staging file.
    #[cfg(unix)]
    #[tokio::test]
    async fn publishes_artifacts_through_the_sdk_verified_publisher() {
        use std::os::unix::fs::PermissionsExt;

        let (envelope, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> =
            Arc::new(ScriptedJobArtifactTransport::new(job, artifacts));
        let fetcher = fetcher(client(transport));
        let destination = TestDir::new();
        let result = Box::pin(fetcher.materialize(&envelope, &destination.0))
            .await
            .unwrap();
        let mode = tokio::fs::metadata(&result.configuration_path)
            .await
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600);
        let root = result.configuration_path.parent().unwrap();
        let mut entries = tokio::fs::read_dir(root).await.unwrap();
        let mut names = Vec::new();
        while let Some(entry) = entries.next_entry().await.unwrap() {
            names.push(entry.file_name().to_string_lossy().into_owned());
        }
        names.sort();
        assert_eq!(names, ["configuration.artifact", "input.artifact"]);
    }

    #[tokio::test]
    async fn rejects_an_existing_file_whose_digest_differs() {
        let (envelope, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> =
            Arc::new(ScriptedJobArtifactTransport::new(job, artifacts));
        let fetcher = fetcher(client(transport));
        let destination = TestDir::new();
        let root = destination.0.join("job-1");
        tokio::fs::create_dir_all(&root).await.unwrap();
        tokio::fs::write(
            root.join("configuration.artifact"),
            b"not the configuration",
        )
        .await
        .unwrap();
        let error = Box::pin(fetcher.materialize(&envelope, &destination.0))
            .await
            .unwrap_err();
        assert!(matches!(
            error,
            AssignmentError::Rejected("existing worker artifact has a different digest")
        ));
    }

    #[tokio::test]
    async fn preserves_sdk_error_classification() {
        let (envelope, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> = Arc::new(
            ScriptedJobArtifactTransport::new(job, artifacts)
                .failing_get_job(Code::PermissionDenied),
        );
        let fetcher = fetcher(client(transport));
        let destination = TestDir::new();
        let error = Box::pin(fetcher.materialize(&envelope, &destination.0))
            .await
            .unwrap_err();
        assert_eq!(error.sdk_kind(), Some(ErrorKind::Authorization));
        assert_eq!(error.stable_code(), Some("mindclade.authorization_denied"));
        assert!(!error.is_retryable());
        assert!(!error.to_string().contains("redacted fake failure"));
    }

    /// Retryability is read from the SDK error, never re-derived from a status.
    #[tokio::test]
    async fn retryability_comes_from_the_sdk_error_hierarchy() {
        let (envelope, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> = Arc::new(
            ScriptedJobArtifactTransport::new(job, artifacts).failing_get_job(Code::Unavailable),
        );
        let fetcher = fetcher(client(transport));
        let destination = TestDir::new();
        let error = Box::pin(fetcher.materialize(&envelope, &destination.0))
            .await
            .unwrap_err();
        assert_eq!(error.sdk_kind(), Some(ErrorKind::RetryableService));
        assert_eq!(error.stable_code(), Some("mindclade.service_unavailable"));
        assert!(error.is_retryable());
    }

    /// The worker holds no timer of its own: the deadline that cancels a
    /// blocked transport is the SDK's, and it arrives classified.
    #[tokio::test]
    async fn sdk_deadline_cancels_a_blocked_transport() {
        let (envelope, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> =
            Arc::new(ScriptedJobArtifactTransport::new(job, artifacts).blocking_get_job());
        let fetcher = fetcher(client_with(transport, Duration::from_millis(20)));
        let destination = TestDir::new();
        let error = Box::pin(fetcher.materialize(&envelope, &destination.0))
            .await
            .unwrap_err();
        assert_eq!(error.sdk_kind(), Some(ErrorKind::DeadlineExceeded));
        assert_eq!(error.stable_code(), Some("mindclade.deadline_exceeded"));
    }

    /// Local intake policy stays the worker's; SDK classification does not apply.
    #[tokio::test]
    async fn rejects_artifacts_over_the_intake_byte_cap() {
        let (envelope, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> =
            Arc::new(ScriptedJobArtifactTransport::new(job, artifacts));
        let fetcher = SourceFetcher::new(
            client(transport),
            Identity::new("tenant-1", "project-1", "ingestion-worker-1").unwrap(),
            Some(1),
        )
        .unwrap();
        let destination = TestDir::new();
        let error = Box::pin(fetcher.materialize(&envelope, &destination.0))
            .await
            .unwrap_err();
        assert!(matches!(
            error,
            AssignmentError::Rejected("artifact exceeds intake policy")
        ));
        assert_eq!(error.sdk_kind(), None);
        assert_eq!(error.stable_code(), None);
        assert!(!error.is_retryable());
    }

    #[test]
    fn rejects_identity_that_does_not_match_the_sdk_client() {
        let (_, job, artifacts) = fixture(b"config", b"input");
        let transport: Arc<dyn RpcTransport> =
            Arc::new(ScriptedJobArtifactTransport::new(job, artifacts));
        let result = SourceFetcher::new(
            client(transport),
            Identity::new("other-tenant", "project-1", "ingestion-worker-1").unwrap(),
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
