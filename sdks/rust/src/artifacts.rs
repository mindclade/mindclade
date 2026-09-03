use std::{
    fs::OpenOptions,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;

use mindclade_protocols::{
    artifact::v1::{ArtifactRef, CommitArtifactCommand},
    common::v1::{CommandContext, ResourceRef},
    internal::artifact::v1::{
        AbortArtifactUploadRequest, AbortArtifactUploadResponse, AcquireArtifactLeaseRequest,
        ArtifactStagingReceipt, ArtifactUploadSession, ArtifactUploadState,
        BeginArtifactUploadRequest, CommitArtifactRequest, DownloadArtifactRequest,
        FinalizeArtifactUploadRequest, GetArtifactRequest, GetArtifactUploadRequest,
        ListArtifactsRequest, ListArtifactsResponse, QuarantineArtifactRequest,
        QuarantineArtifactUploadRequest, ReleaseArtifactLeaseRequest, ResolveArtifactAliasRequest,
        UploadArtifactChunkRequest,
    },
    job::v1::{Operation, OperationState},
};
use prost::Message;
use prost_types::Timestamp;
use sha2::{Digest, Sha256};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tonic::{Code, codegen::tokio_stream::StreamExt};

use crate::{
    CallOptions, ClientCore, Error, SubmitOptions,
    request::{generate_request_id, validate_resource_value},
    retry::registered_method_safety,
};

const RESOLVE_ARTIFACT_ALIAS: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias";
const BEGIN_ARTIFACT_UPLOAD: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/BeginArtifactUpload";
const UPLOAD_ARTIFACT_CHUNK: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/UploadArtifactChunk";
const GET_ARTIFACT_UPLOAD: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/GetArtifactUpload";
const FINALIZE_ARTIFACT_UPLOAD: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/FinalizeArtifactUpload";
const ABORT_ARTIFACT_UPLOAD: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/AbortArtifactUpload";
const QUARANTINE_ARTIFACT_UPLOAD: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifactUpload";
const COMMIT_ARTIFACT: &str = "/mindclade.internal.artifact.v1.ArtifactService/CommitArtifact";
const DOWNLOAD_ARTIFACT: &str = "/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact";
const GET_ARTIFACT: &str = "/mindclade.internal.artifact.v1.ArtifactService/GetArtifact";
const LIST_ARTIFACTS: &str = "/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts";
const QUARANTINE_ARTIFACT: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact";
const ACQUIRE_ARTIFACT_LEASE: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease";
const RELEASE_ARTIFACT_LEASE: &str =
    "/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease";

const DEFAULT_CHUNK_BYTES: usize = 1 << 20;
const MAX_CHUNK_BYTES: usize = 4 << 20;
const DEFAULT_SESSION_TTL: Duration = Duration::from_hours(2);
const MAX_SESSION_TTL: Duration = Duration::from_hours(24);
const DEFAULT_RECEIPT_TTL: Duration = Duration::from_hours(24);
const MAX_RECEIPT_TTL: Duration = Duration::from_hours(24 * 7);
const MAX_LEASE_TTL: Duration = Duration::from_hours(24 * 30);
const MAX_ARTIFACT_PAGE_SIZE: u32 = 100;

/// Behavioral policy for one resumable artifact upload. All resource and wire
/// values remain generated protobuf messages.
#[derive(Clone, Debug)]
pub struct ArtifactUploadOptions {
    upload_id: String,
    chunk_bytes: usize,
    session_ttl: Duration,
    receipt_ttl: Duration,
    call: CallOptions,
}

impl ArtifactUploadOptions {
    /// Creates transfer policy for a caller-stable upload identifier. Reusing
    /// this identifier allows a fresh process to resume the durable session.
    ///
    /// # Errors
    ///
    /// Returns an error when the identifier is unsafe for a canonical resource
    /// name.
    pub fn new(upload_id: impl Into<String>) -> Result<Self, Error> {
        let upload_id = upload_id.into();
        validate_upload_id(&upload_id)?;
        Ok(Self {
            upload_id,
            chunk_bytes: DEFAULT_CHUNK_BYTES,
            session_ttl: DEFAULT_SESSION_TTL,
            receipt_ttl: DEFAULT_RECEIPT_TTL,
            call: CallOptions::new(),
        })
    }

    /// Sets the independently checksummed chunk size.
    ///
    /// # Errors
    ///
    /// Returns an error outside the service limit of one byte through four
    /// MiB.
    pub fn with_chunk_bytes(mut self, value: usize) -> Result<Self, Error> {
        if !(1..=MAX_CHUNK_BYTES).contains(&value) {
            return Err(Error::invalid_argument(
                "artifact upload chunks must be between one byte and four MiB",
            ));
        }
        self.chunk_bytes = value;
        Ok(self)
    }

    /// Sets the durable session lifetime.
    ///
    /// # Errors
    ///
    /// Returns an error for a zero or greater-than-one-day lifetime.
    pub fn with_session_ttl(mut self, value: Duration) -> Result<Self, Error> {
        validate_lifetime("artifact upload session", value, MAX_SESSION_TTL)?;
        self.session_ttl = value;
        Ok(self)
    }

    /// Sets the staging receipt lifetime.
    ///
    /// # Errors
    ///
    /// Returns an error for a zero or greater-than-seven-day lifetime.
    pub fn with_receipt_ttl(mut self, value: Duration) -> Result<Self, Error> {
        validate_lifetime("artifact staging receipt", value, MAX_RECEIPT_TTL)?;
        self.receipt_ttl = value;
        Ok(self)
    }

    #[must_use]
    pub fn with_call_options(mut self, value: CallOptions) -> Self {
        self.call = value;
        self
    }

    fn submit(&self, phase: &str) -> Result<SubmitOptions, Error> {
        Ok(SubmitOptions::new(phase_key(&self.upload_id, phase))?
            .with_call_options(self.call.clone()))
    }
}

/// Artifact catalog and transfer helpers over generated artifact clients.
#[derive(Clone)]
pub struct Artifacts {
    core: Arc<ClientCore>,
}

impl Artifacts {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Reads immutable metadata by canonical project-scoped name or digest.
    ///
    /// # Errors
    ///
    /// Returns an error for ambiguous identity, cross-project names, RPC
    /// failure, or inconsistent response content.
    pub async fn get(
        &self,
        request: GetArtifactRequest,
        options: CallOptions,
    ) -> Result<ArtifactRef, Error> {
        if request.name.is_empty() == request.digest.is_empty() {
            return Err(Error::invalid_argument(
                "artifact get requires exactly one canonical name or digest",
            ));
        }
        let expected_digest = if request.name.is_empty() {
            request.digest.clone()
        } else {
            artifact_digest_from_name(&self.core.config, &request.name)?
        };
        if !is_sha256_digest(&expected_digest) {
            return Err(Error::invalid_argument(
                "artifact digest must be canonical sha256",
            ));
        }
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(GET_ARTIFACT),
                None,
                |transport, request| Box::pin(async move { transport.get_artifact(request).await }),
            )
            .await?;
        let artifact = response
            .into_inner()
            .artifact
            .ok_or_else(|| Error::protocol("GetArtifact response omitted its artifact"))?;
        validate_transfer_artifact(&artifact)
            .map_err(|_| Error::protocol("GetArtifact returned invalid immutable metadata"))?;
        if artifact.digest != expected_digest {
            return Err(Error::protocol(
                "GetArtifact returned a different immutable identity",
            ));
        }
        Ok(artifact)
    }

    /// Returns one bounded, project-scoped page while preserving opaque
    /// pagination state.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid parent/page size, RPC failure, or
    /// malformed artifact metadata.
    pub async fn list(
        &self,
        mut request: ListArtifactsRequest,
        options: CallOptions,
    ) -> Result<ListArtifactsResponse, Error> {
        let parent = project_parent(&self.core.config);
        if !request.parent.is_empty() && request.parent != parent {
            return Err(Error::invalid_argument(
                "artifact list parent must match the configured project",
            ));
        }
        if request
            .page
            .as_ref()
            .is_some_and(|page| page.page_size > MAX_ARTIFACT_PAGE_SIZE)
        {
            return Err(Error::invalid_argument(
                "artifact page size cannot exceed 100",
            ));
        }
        request.parent = parent;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(LIST_ARTIFACTS),
                None,
                |transport, request| {
                    Box::pin(async move { transport.list_artifacts(request).await })
                },
            )
            .await?
            .into_inner();
        for artifact in &response.artifacts {
            validate_transfer_artifact(artifact)
                .map_err(|_| Error::protocol("ListArtifacts returned invalid metadata"))?;
        }
        Ok(response)
    }

    /// Records a governed quarantine transition under deterministic command
    /// identity and returns its durable operation.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed evidence, unsafe scope, or RPC failure.
    pub async fn quarantine(
        &self,
        mut request: QuarantineArtifactRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let artifact = request
            .artifact
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("artifact quarantine requires an artifact"))?;
        validate_transfer_artifact(artifact)?;
        if !valid_reason_code(&request.reason_code) || request.evidence.len() > 100 {
            return Err(Error::invalid_argument(
                "artifact quarantine reason or evidence is invalid",
            ));
        }
        for evidence in &request.evidence {
            if !is_sha256_digest(&evidence.digest)
                || evidence.subject_digest != artifact.digest
                || evidence.evidence_kind.is_empty()
                || evidence.evidence_kind.len() > 128
                || (!evidence.policy_digest.is_empty()
                    && !is_sha256_digest(&evidence.policy_digest))
            {
                return Err(Error::invalid_argument(
                    "artifact quarantine evidence is invalid",
                ));
            }
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(QUARANTINE_ARTIFACT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.quarantine_artifact(request).await })
                },
            )
            .await?;
        validate_artifact_operation(&self.core, response.into_inner().operation)
    }

    /// Creates or extends a bounded retention lease for immutable content.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid content/expiration, RPC failure, or a
    /// malformed lease resource.
    pub async fn acquire_lease(
        &self,
        mut request: AcquireArtifactLeaseRequest,
        options: SubmitOptions,
    ) -> Result<ResourceRef, Error> {
        validate_transfer_artifact(
            request
                .artifact
                .as_ref()
                .ok_or_else(|| Error::invalid_argument("artifact lease requires an artifact"))?,
        )?;
        let expiry = request
            .expire_time
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("artifact lease expiration is required"))?;
        let expiry = UNIX_EPOCH
            .checked_add(
                timestamp_duration(expiry)
                    .map_err(|_| Error::invalid_argument("artifact lease expiration is invalid"))?,
            )
            .ok_or_else(|| Error::invalid_argument("artifact lease expiration overflowed"))?;
        let now = SystemTime::now();
        if expiry <= now
            || expiry
                .duration_since(now)
                .map_or(true, |ttl| ttl > MAX_LEASE_TTL)
        {
            return Err(Error::invalid_argument(
                "artifact lease expiration must be within 30 days",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(ACQUIRE_ARTIFACT_LEASE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.acquire_artifact_lease(request).await })
                },
            )
            .await?;
        validate_artifact_lease(
            &self.core,
            response
                .into_inner()
                .lease
                .ok_or_else(|| Error::protocol("AcquireArtifactLease omitted its lease"))?,
        )
    }

    /// Idempotently releases a scoped retention lease under its `ETag`.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/ETag or RPC failure.
    pub async fn release_lease(
        &self,
        mut request: ReleaseArtifactLeaseRequest,
        options: SubmitOptions,
    ) -> Result<(), Error> {
        let lease = validate_artifact_lease(
            &self.core,
            request
                .lease
                .clone()
                .ok_or_else(|| Error::invalid_argument("artifact lease is required"))?,
        )
        .map_err(|_| Error::invalid_argument("artifact lease release resource is invalid"))?;
        validate_resource_value("artifact lease ETag", &request.etag)?;
        if !lease.etag.is_empty() && lease.etag != request.etag {
            return Err(Error::invalid_argument(
                "artifact lease and release ETags differ",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let key = options.idempotency_key.clone();
        self.core
            .unary(
                request,
                &prepared,
                registered_method_safety(RELEASE_ARTIFACT_LEASE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.release_artifact_lease(request).await })
                },
            )
            .await?;
        Ok(())
    }

    /// Resolves a mutable catalog alias to an authoritative immutable
    /// [`ArtifactRef`].
    ///
    /// # Errors
    ///
    /// Returns an error for invalid names, credentials, exhausted retries, or
    /// a response that omits the required artifact.
    pub async fn resolve_alias(
        &self,
        parent: impl Into<String>,
        alias: impl Into<String>,
        options: CallOptions,
    ) -> Result<ArtifactRef, Error> {
        let parent = parent.into();
        let alias = alias.into();
        validate_resource_value("artifact alias parent", &parent)?;
        validate_resource_value("artifact alias", &alias)?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                ResolveArtifactAliasRequest { parent, alias },
                &prepared,
                registered_method_safety(RESOLVE_ARTIFACT_ALIAS),
                None,
                |transport, request| {
                    Box::pin(async move { transport.resolve_artifact_alias(request).await })
                },
            )
            .await?;
        response
            .into_inner()
            .artifact
            .ok_or_else(|| Error::protocol("ResolveArtifactAlias response omitted its artifact"))
    }

    /// Reads authoritative resumable upload progress.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid name, remote status, or malformed
    /// generated response.
    pub async fn get_upload(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<ArtifactUploadSession, Error> {
        let name = name.into();
        validate_resource_value("artifact upload name", &name)?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetArtifactUploadRequest { name },
                &prepared,
                registered_method_safety(GET_ARTIFACT_UPLOAD),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_artifact_upload(request).await })
                },
            )
            .await?;
        let upload = response
            .into_inner()
            .upload
            .ok_or_else(|| Error::protocol("GetArtifactUpload response omitted its session"))?;
        validate_upload(&upload, None)?;
        Ok(upload)
    }

    /// Resumes or begins a generated transfer session, appends contiguous
    /// digest-verified chunks, and returns the opaque staging receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid content identity, source length/digest
    /// mismatch, credentials, remote conflict, or malformed progress.
    pub async fn upload<Reader>(
        &self,
        artifact: ArtifactRef,
        source: &mut Reader,
        options: ArtifactUploadOptions,
    ) -> Result<ArtifactStagingReceipt, Error>
    where
        Reader: AsyncRead + Unpin + Send,
    {
        validate_transfer_artifact(&artifact)?;
        validate_upload_id(&options.upload_id)?;
        let parent = project_parent(&self.core.config);
        let mut upload = self
            .resume_or_begin_upload(&parent, &artifact, &options)
            .await?;
        if upload.state == ArtifactUploadState::Finalized as i32 {
            return validate_receipt(
                upload.staging_receipt.ok_or_else(|| {
                    Error::protocol("finalized artifact upload omitted its staging receipt")
                })?,
                Some(&artifact),
            );
        }
        if upload.state != ArtifactUploadState::Open as i32 {
            return Err(Error::invalid_argument(
                "artifact upload session cannot be resumed",
            ));
        }

        let mut full_digest = Sha256::new();
        let prefix = usize::try_from(upload.committed_offset).map_err(|_| {
            Error::protocol("artifact upload committed offset exceeds client limits")
        })?;
        hash_exact(source, prefix, &mut full_digest).await?;
        let expected_size = usize::try_from(artifact.size_bytes)
            .map_err(|_| Error::invalid_argument("artifact size exceeds client limits"))?;
        let mut offset = prefix;
        while offset < expected_size {
            let length = options.chunk_bytes.min(expected_size - offset);
            let mut data = vec![0_u8; length];
            source.read_exact(&mut data).await.map_err(|_| {
                Error::invalid_argument("artifact upload source ended before its declared size")
            })?;
            full_digest.update(&data);
            let chunk_digest = digest_bytes(&data);
            let phase = format!("chunk:{}:{}", upload.next_chunk_index, chunk_digest);
            let submit = options.submit(&phase)?;
            let prepared = submit.call.prepare(&self.core.config);
            let mut request = UploadArtifactChunkRequest {
                context: None,
                name: upload.name.clone(),
                chunk_index: upload.next_chunk_index,
                offset: i64::try_from(offset)
                    .map_err(|_| Error::invalid_argument("artifact offset exceeds i64"))?,
                data,
                chunk_digest,
                etag: upload.etag.clone(),
            };
            request.context = Some(command_context(&self.core, &prepared, &submit, &request)?);
            let idempotency_key = submit.idempotency_key.clone();
            let expected_offset = offset + length;
            let expected_index = upload.next_chunk_index + 1;
            let response = self
                .core
                .unary(
                    request,
                    &prepared,
                    registered_method_safety(UPLOAD_ARTIFACT_CHUNK),
                    Some(&idempotency_key),
                    |transport, request| {
                        Box::pin(async move { transport.upload_artifact_chunk(request).await })
                    },
                )
                .await?;
            upload = response.into_inner().upload.ok_or_else(|| {
                Error::protocol("UploadArtifactChunk response omitted its session")
            })?;
            validate_upload(&upload, Some(&artifact))?;
            if upload.state != ArtifactUploadState::Open as i32
                || upload.committed_offset
                    != i64::try_from(expected_offset).map_err(|_| {
                        Error::invalid_argument("artifact offset exceeds protocol range")
                    })?
                || upload.next_chunk_index != expected_index
            {
                return Err(Error::protocol(
                    "artifact upload progress did not advance contiguously",
                ));
            }
            offset = expected_offset;
        }
        let mut extra = [0_u8; 1];
        if source
            .read(&mut extra)
            .await
            .map_err(|_| Error::invalid_argument("artifact upload source failed"))?
            != 0
        {
            return Err(Error::invalid_argument(
                "artifact upload source exceeds its declared size",
            ));
        }
        if digest_output(full_digest.finalize().as_slice()) != artifact.digest {
            return Err(Error::invalid_argument(
                "artifact upload source digest differs from ArtifactRef",
            ));
        }
        self.finalize_upload(upload, &artifact, &options).await
    }

    async fn resume_or_begin_upload(
        &self,
        parent: &str,
        artifact: &ArtifactRef,
        options: &ArtifactUploadOptions,
    ) -> Result<ArtifactUploadSession, Error> {
        let upload_name = format!("{parent}/artifactUploads/{}", options.upload_id);
        let upload = match self.get_upload(upload_name, options.call.clone()).await {
            Ok(existing) => existing,
            Err(error) if error.code() == Some(Code::NotFound) => {
                self.begin_upload(parent, artifact, options).await?
            }
            Err(error) => return Err(error),
        };
        validate_upload(&upload, Some(artifact))?;
        Ok(upload)
    }

    async fn begin_upload(
        &self,
        parent: &str,
        artifact: &ArtifactRef,
        options: &ArtifactUploadOptions,
    ) -> Result<ArtifactUploadSession, Error> {
        let submit = options.submit("begin")?;
        let prepared = submit.call.prepare(&self.core.config);
        let mut request = BeginArtifactUploadRequest {
            context: None,
            parent: parent.to_owned(),
            artifact: Some(artifact.clone()),
            upload_id: options.upload_id.clone(),
            expire_time: Some(timestamp_after(options.session_ttl)?),
        };
        request.context = Some(command_context(&self.core, &prepared, &submit, &request)?);
        let idempotency_key = submit.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(BEGIN_ARTIFACT_UPLOAD),
                Some(&idempotency_key),
                |transport, request| {
                    Box::pin(async move { transport.begin_artifact_upload(request).await })
                },
            )
            .await;
        match response {
            Ok(response) => response
                .into_inner()
                .upload
                .ok_or_else(|| Error::protocol("BeginArtifactUpload omitted its session")),
            Err(error) if matches!(error.code(), Some(Code::AlreadyExists | Code::Aborted)) => {
                let name = format!("{parent}/artifactUploads/{}", options.upload_id);
                self.get_upload(name, options.call.clone()).await
            }
            Err(error) => Err(error),
        }
    }

    async fn finalize_upload(
        &self,
        upload: ArtifactUploadSession,
        artifact: &ArtifactRef,
        options: &ArtifactUploadOptions,
    ) -> Result<ArtifactStagingReceipt, Error> {
        let submit = options.submit("finalize")?;
        let prepared = submit.call.prepare(&self.core.config);
        let receipt_base = upload
            .create_time
            .as_ref()
            .filter(|value| value.seconds > 0)
            .copied()
            .unwrap_or(timestamp_now()?);
        let mut request = FinalizeArtifactUploadRequest {
            context: None,
            name: upload.name,
            etag: upload.etag,
            receipt_expire_time: Some(timestamp_add(&receipt_base, options.receipt_ttl)?),
        };
        request.context = Some(command_context(&self.core, &prepared, &submit, &request)?);
        let idempotency_key = submit.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(FINALIZE_ARTIFACT_UPLOAD),
                Some(&idempotency_key),
                |transport, request| {
                    Box::pin(async move { transport.finalize_artifact_upload(request).await })
                },
            )
            .await?
            .into_inner();
        let finalized = response.upload.ok_or_else(|| {
            Error::protocol("FinalizeArtifactUpload response omitted its session")
        })?;
        validate_upload(&finalized, Some(artifact))?;
        if finalized.state != ArtifactUploadState::Finalized as i32 {
            return Err(Error::protocol(
                "FinalizeArtifactUpload did not return a finalized session",
            ));
        }
        validate_receipt(
            response.staging_receipt.ok_or_else(|| {
                Error::protocol("FinalizeArtifactUpload omitted its staging receipt")
            })?,
            Some(artifact),
        )
    }

    /// Permanently aborts an incomplete upload using its optimistic `ETag`.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid input, remote conflict, or malformed
    /// terminal state.
    pub async fn abort_upload(
        &self,
        name: impl Into<String>,
        etag: impl Into<String>,
        reason_code: impl Into<String>,
        options: SubmitOptions,
    ) -> Result<ArtifactUploadSession, Error> {
        let name = name.into();
        let etag = etag.into();
        let reason_code = reason_code.into();
        validate_resource_value("artifact upload name", &name)?;
        validate_resource_value("artifact upload ETag", &etag)?;
        validate_resource_value("artifact upload reason", &reason_code)?;
        let prepared = options.call.prepare(&self.core.config);
        let mut request = AbortArtifactUploadRequest {
            context: None,
            name,
            etag,
            reason_code,
        };
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let idempotency_key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(ABORT_ARTIFACT_UPLOAD),
                Some(&idempotency_key),
                |transport, request| {
                    Box::pin(async move { transport.abort_artifact_upload(request).await })
                },
            )
            .await?;
        terminal_upload(
            response.into_inner(),
            ArtifactUploadState::Aborted,
            "AbortArtifactUpload",
        )
    }

    /// Permanently quarantines an upload after an integrity or governance
    /// failure.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid input, remote conflict, or malformed
    /// terminal state.
    pub async fn quarantine_upload(
        &self,
        name: impl Into<String>,
        etag: impl Into<String>,
        reason_code: impl Into<String>,
        options: SubmitOptions,
    ) -> Result<ArtifactUploadSession, Error> {
        let name = name.into();
        let etag = etag.into();
        let reason_code = reason_code.into();
        validate_resource_value("artifact upload name", &name)?;
        validate_resource_value("artifact upload ETag", &etag)?;
        validate_resource_value("artifact upload reason", &reason_code)?;
        let prepared = options.call.prepare(&self.core.config);
        let mut request = QuarantineArtifactUploadRequest {
            context: None,
            name,
            etag,
            reason_code,
        };
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let idempotency_key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(QUARANTINE_ARTIFACT_UPLOAD),
                Some(&idempotency_key),
                |transport, request| {
                    Box::pin(async move { transport.quarantine_artifact_upload(request).await })
                },
            )
            .await?;
        let response = response.into_inner();
        let upload = response.upload.ok_or_else(|| {
            Error::protocol("QuarantineArtifactUpload response omitted its session")
        })?;
        validate_upload(&upload, None)?;
        if upload.state != ArtifactUploadState::Quarantined as i32 {
            return Err(Error::protocol(
                "QuarantineArtifactUpload returned a non-quarantined session",
            ));
        }
        Ok(upload)
    }

    /// Commits a verified staging receipt into the immutable artifact catalog.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid receipt, remote conflict, or identity
    /// mismatch.
    pub async fn commit(
        &self,
        receipt: ArtifactStagingReceipt,
        options: SubmitOptions,
    ) -> Result<ArtifactRef, Error> {
        let receipt = validate_receipt(receipt, None)?;
        let artifact = receipt
            .artifact
            .clone()
            .ok_or_else(|| Error::protocol("artifact staging receipt omitted its artifact"))?;
        let prepared = options.call.prepare(&self.core.config);
        let mut command = CommitArtifactCommand {
            context: None,
            artifact: Some(artifact.clone()),
            staging_receipt_digest: receipt.receipt_digest,
        };
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let idempotency_key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CommitArtifactRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(COMMIT_ARTIFACT),
                Some(&idempotency_key),
                |transport, request| {
                    Box::pin(async move { transport.commit_artifact(request).await })
                },
            )
            .await?;
        let committed = response
            .into_inner()
            .artifact
            .ok_or_else(|| Error::protocol("CommitArtifact response omitted its artifact"))?;
        validate_transfer_artifact(&committed)?;
        if committed != artifact {
            return Err(Error::protocol(
                "CommitArtifact returned a different content identity",
            ));
        }
        Ok(committed)
    }

    /// Streams one generation-pinned immutable object to a caller-owned
    /// destination while checking identity, offsets, chunk digests, final size,
    /// and full digest.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid identity, cancellation/deadline, remote
    /// failure, short writes, or any content mismatch.
    pub async fn download<Writer>(
        &self,
        artifact: &ArtifactRef,
        destination: &mut Writer,
        options: CallOptions,
    ) -> Result<u64, Error>
    where
        Writer: AsyncWrite + Unpin + Send,
    {
        validate_transfer_artifact(artifact)?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                DownloadArtifactRequest {
                    name: String::new(),
                    digest: artifact.digest.clone(),
                    offset: 0,
                    max_chunk_bytes: i32::try_from(DEFAULT_CHUNK_BYTES)
                        .map_err(|_| Error::invalid_argument("download chunk size exceeds i32"))?,
                },
                &prepared,
                registered_method_safety(DOWNLOAD_ARTIFACT),
                None,
                |transport, request| {
                    Box::pin(async move { transport.download_artifact(request).await })
                },
            )
            .await?;
        let mut stream = response.into_inner();
        let mut digest = Sha256::new();
        let mut offset = 0_i64;
        let mut complete = false;
        loop {
            let remaining = prepared
                .deadline
                .checked_duration_since(std::time::Instant::now())
                .ok_or_else(Error::deadline_exceeded)?;
            let item = tokio::time::timeout(remaining, stream.next())
                .await
                .map_err(|_| Error::deadline_exceeded())?;
            let Some(item) = item else { break };
            let response = item.map_err(|status| Error::from_status(&status))?;
            if complete {
                return Err(Error::protocol(
                    "artifact download yielded a response after completion",
                ));
            }
            let streamed = response
                .artifact
                .ok_or_else(|| Error::protocol("artifact download omitted its identity"))?;
            if streamed != *artifact || response.offset != offset {
                return Err(Error::protocol(
                    "artifact download stream changed identity or offset",
                ));
            }
            if response.chunk_digest != digest_bytes(&response.data) {
                return Err(Error::protocol(
                    "artifact download chunk digest verification failed",
                ));
            }
            destination
                .write_all(&response.data)
                .await
                .map_err(|_| Error::protocol("artifact destination write failed"))?;
            digest.update(&response.data);
            offset = offset
                .checked_add(i64::try_from(response.data.len()).map_err(|_| {
                    Error::protocol("artifact download chunk exceeds protocol range")
                })?)
                .ok_or_else(|| Error::protocol("artifact download offset overflowed"))?;
            complete = response.complete;
            if complete {
                break;
            }
        }
        destination
            .flush()
            .await
            .map_err(|_| Error::protocol("artifact destination flush failed"))?;
        if !complete || offset != artifact.size_bytes {
            return Err(Error::protocol(
                "artifact download ended before its declared size",
            ));
        }
        if digest_output(digest.finalize().as_slice()) != artifact.digest {
            return Err(Error::protocol(
                "artifact download full digest verification failed",
            ));
        }
        u64::try_from(offset)
            .map_err(|_| Error::protocol("artifact download byte count was negative"))
    }

    /// Downloads, verifies, and atomically publishes a new mode-0600 file.
    ///
    /// Same-directory hard-link publication never overwrites an existing
    /// destination, including under a racing writer. Successful link creation
    /// is the commit point; later best-effort staging cleanup cannot turn a
    /// committed file into an ambiguous failure result.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid path, an existing destination, any
    /// download/integrity failure, or a filesystem failure before publication.
    pub async fn download_file(
        &self,
        artifact: &ArtifactRef,
        destination: impl AsRef<Path>,
        options: CallOptions,
    ) -> Result<u64, Error> {
        let destination = destination.as_ref();
        if destination.as_os_str().is_empty()
            || destination.as_os_str().as_encoded_bytes().contains(&0)
        {
            return Err(Error::invalid_argument(
                "artifact destination must be a non-empty NUL-free filesystem path",
            ));
        }
        let target = if destination.is_absolute() {
            destination.to_path_buf()
        } else {
            std::env::current_dir()
                .map_err(|_| Error::filesystem("artifact destination directory is unavailable"))?
                .join(destination)
        };
        let directory = target.parent().ok_or_else(|| {
            Error::invalid_argument("artifact destination must have a parent directory")
        })?;
        let staging = directory.join(format!(".mindclade-download-{}", generate_request_id()));
        let mut open_options = OpenOptions::new();
        open_options.create_new(true).read(true).write(true);
        #[cfg(unix)]
        open_options.mode(0o600);
        let standard_file = open_options.open(&staging).map_err(|_| {
            Error::filesystem("artifact destination staging file could not be created")
        })?;
        let mut cleanup = StagedArtifactFile::new(staging.clone());
        let mut file = tokio::fs::File::from_std(standard_file);
        let written = self.download(artifact, &mut file, options).await?;
        file.sync_all()
            .await
            .map_err(|_| Error::filesystem("artifact destination sync failed"))?;
        drop(file);
        match std::fs::hard_link(&staging, &target) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                return Err(Error::already_exists("artifact destination already exists"));
            }
            Err(_) => {
                return Err(Error::filesystem("artifact destination publication failed"));
            }
        }
        // Hard-link success is the commit point. From here onward every
        // operation is best effort so cancellation or cleanup support cannot
        // produce an error while leaving a valid destination behind.
        sync_artifact_directory(directory);
        cleanup.remove();
        sync_artifact_directory(directory);
        Ok(written)
    }
}

struct StagedArtifactFile {
    path: Option<PathBuf>,
}

impl StagedArtifactFile {
    fn new(path: PathBuf) -> Self {
        Self { path: Some(path) }
    }

    fn remove(&mut self) {
        if let Some(path) = self.path.take() {
            let _ = std::fs::remove_file(path);
        }
    }
}

impl Drop for StagedArtifactFile {
    fn drop(&mut self) {
        self.remove();
    }
}

fn sync_artifact_directory(directory: &Path) {
    if let Ok(handle) = std::fs::File::open(directory) {
        let _ = handle.sync_all();
    }
}

fn terminal_upload(
    response: AbortArtifactUploadResponse,
    expected: ArtifactUploadState,
    method: &str,
) -> Result<ArtifactUploadSession, Error> {
    let upload = response
        .upload
        .ok_or_else(|| Error::protocol(format!("{method} response omitted its session")))?;
    validate_upload(&upload, None)?;
    if upload.state != expected as i32 {
        return Err(Error::protocol(format!(
            "{method} returned an unexpected session state"
        )));
    }
    Ok(upload)
}

fn command_context<MessageType: Message>(
    core: &ClientCore,
    prepared: &crate::request::PreparedCall,
    options: &SubmitOptions,
    message: &MessageType,
) -> Result<CommandContext, Error> {
    let mut context = prepared.command_context(&core.config, options)?;
    context.canonical_request_digest = digest_bytes(&message.encode_to_vec());
    Ok(context)
}

fn validate_transfer_artifact(artifact: &ArtifactRef) -> Result<(), Error> {
    if !is_sha256_digest(&artifact.digest)
        || artifact.media_type.trim().is_empty()
        || artifact.size_bytes < 0
        || !artifact.uri.is_empty()
        || (!artifact.integrity_digest.is_empty() && artifact.integrity_digest != artifact.digest)
        || artifact.schema_id.is_empty() != artifact.schema_version.is_empty()
    {
        return Err(Error::invalid_argument(
            "a complete immutable ArtifactRef without a provider URI is required",
        ));
    }
    Ok(())
}

fn validate_upload(
    upload: &ArtifactUploadSession,
    expected: Option<&ArtifactRef>,
) -> Result<(), Error> {
    validate_resource_value("artifact upload name", &upload.name)?;
    let artifact = upload
        .artifact
        .as_ref()
        .ok_or_else(|| Error::protocol("artifact upload omitted its artifact"))?;
    validate_transfer_artifact(artifact)?;
    if expected.is_some_and(|expected| expected != artifact) {
        return Err(Error::protocol(
            "artifact upload returned a different content identity",
        ));
    }
    if ArtifactUploadState::try_from(upload.state).is_err()
        || upload.state == ArtifactUploadState::Unspecified as i32
        || upload.committed_offset < 0
        || upload.committed_offset > artifact.size_bytes
        || upload.next_chunk_index < 0
        || upload.revision <= 0
        || upload.etag.is_empty()
    {
        return Err(Error::protocol(
            "artifact upload returned invalid lifecycle metadata",
        ));
    }
    Ok(())
}

fn validate_receipt(
    receipt: ArtifactStagingReceipt,
    expected: Option<&ArtifactRef>,
) -> Result<ArtifactStagingReceipt, Error> {
    if !is_sha256_digest(&receipt.receipt_digest) {
        return Err(Error::protocol(
            "artifact staging receipt digest is invalid",
        ));
    }
    let artifact = receipt
        .artifact
        .as_ref()
        .ok_or_else(|| Error::protocol("artifact staging receipt omitted its artifact"))?;
    validate_transfer_artifact(artifact)?;
    if expected.is_some_and(|expected| expected != artifact) {
        return Err(Error::protocol(
            "artifact staging receipt returned a different content identity",
        ));
    }
    let verified = receipt
        .verified_at
        .as_ref()
        .ok_or_else(|| Error::protocol("artifact staging receipt omitted verified_at"))?;
    let expires = receipt
        .expire_time
        .as_ref()
        .ok_or_else(|| Error::protocol("artifact staging receipt omitted expire_time"))?;
    if timestamp_duration(expires)? <= timestamp_duration(verified)? {
        return Err(Error::protocol(
            "artifact staging receipt validity interval is invalid",
        ));
    }
    Ok(receipt)
}

async fn hash_exact<Reader>(
    source: &mut Reader,
    length: usize,
    digest: &mut Sha256,
) -> Result<(), Error>
where
    Reader: AsyncRead + Unpin,
{
    let mut remaining = length;
    let mut buffer = vec![0_u8; DEFAULT_CHUNK_BYTES.min(length.max(1))];
    while remaining > 0 {
        let count = remaining.min(buffer.len());
        source.read_exact(&mut buffer[..count]).await.map_err(|_| {
            Error::invalid_argument(
                "artifact upload source is shorter than its durable resume offset",
            )
        })?;
        digest.update(&buffer[..count]);
        remaining -= count;
    }
    Ok(())
}

fn validate_upload_id(value: &str) -> Result<(), Error> {
    let valid = !value.is_empty()
        && value.len() <= 128
        && value.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_alphanumeric() || (index > 0 && matches!(byte, b'.' | b'_' | b'-'))
        });
    if !valid {
        return Err(Error::invalid_argument("artifact upload ID is invalid"));
    }
    Ok(())
}

fn validate_lifetime(name: &str, value: Duration, maximum: Duration) -> Result<(), Error> {
    if value.is_zero() || value > maximum {
        return Err(Error::invalid_argument(format!(
            "{name} lifetime is outside policy"
        )));
    }
    Ok(())
}

fn project_parent(config: &crate::Config) -> String {
    let tenant = config.identity.tenant_id();
    let project = config.identity.project_id();
    let tenant = if tenant.starts_with("tenants/") {
        tenant.to_owned()
    } else {
        format!("tenants/{tenant}")
    };
    if project.starts_with("tenants/") {
        project.to_owned()
    } else if project.starts_with("projects/") {
        format!("{tenant}/{project}")
    } else {
        format!("{tenant}/projects/{project}")
    }
}

fn artifact_digest_from_name(config: &crate::Config, name: &str) -> Result<String, Error> {
    let prefix = format!("{}/artifacts/", project_parent(config));
    let digest = name.strip_prefix(&prefix).ok_or_else(|| {
        Error::invalid_argument("artifact name must be in the configured project")
    })?;
    if !is_sha256_digest(digest) {
        return Err(Error::invalid_argument(
            "artifact name must end in a canonical sha256 digest",
        ));
    }
    Ok(digest.to_owned())
}

fn validate_artifact_lease(core: &ClientCore, lease: ResourceRef) -> Result<ResourceRef, Error> {
    let expected_name = format!(
        "{}/artifactLeases/{}",
        project_parent(&core.config),
        lease.resource_id
    );
    if lease.resource_type != "artifact_lease"
        || lease.resource_id.is_empty()
        || lease.tenant_id != core.config.identity.tenant_id()
        || lease.project_id != core.config.identity.project_id()
        || lease.name != expected_name
        || lease.resource_version <= 0
        || lease.etag.is_empty()
    {
        return Err(Error::protocol(
            "artifact lease resource is invalid or outside the configured project",
        ));
    }
    Ok(lease)
}

fn validate_artifact_operation(
    core: &ClientCore,
    operation: Option<Operation>,
) -> Result<Operation, Error> {
    let operation = operation
        .ok_or_else(|| Error::protocol("QuarantineArtifact omitted its durable operation"))?;
    if operation.operation_id.is_empty()
        || operation.tenant_id != core.config.identity.tenant_id()
        || operation.project_id != core.config.identity.project_id()
        || operation.state == OperationState::Unspecified as i32
    {
        return Err(Error::protocol(
            "QuarantineArtifact returned invalid or cross-project operation state",
        ));
    }
    Ok(operation)
}

fn valid_reason_code(value: &str) -> bool {
    let bytes = value.as_bytes();
    (2..=64).contains(&bytes.len())
        && bytes[0].is_ascii_uppercase()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || *byte == b'_')
}

fn phase_key(identity: &str, phase: &str) -> String {
    digest_bytes(format!("{identity}\0{phase}").as_bytes()).replacen(
        "sha256:",
        "artifact-transfer:",
        1,
    )
}

fn digest_bytes(value: &[u8]) -> String {
    digest_output(Sha256::digest(value).as_slice())
}

fn digest_output(value: &[u8]) -> String {
    let mut result = String::with_capacity(71);
    result.push_str("sha256:");
    for byte in value {
        use std::fmt::Write as _;
        let _ = write!(result, "{byte:02x}");
    }
    result
}

fn is_sha256_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn timestamp_now() -> Result<Timestamp, Error> {
    timestamp_from_system_time(SystemTime::now())
}

fn timestamp_after(value: Duration) -> Result<Timestamp, Error> {
    timestamp_from_system_time(
        SystemTime::now()
            .checked_add(value)
            .ok_or_else(|| Error::invalid_argument("artifact lifetime overflowed"))?,
    )
}

fn timestamp_add(value: &Timestamp, duration: Duration) -> Result<Timestamp, Error> {
    let base = UNIX_EPOCH
        .checked_add(timestamp_duration(value)?)
        .ok_or_else(|| Error::invalid_argument("artifact timestamp overflowed"))?;
    timestamp_from_system_time(
        base.checked_add(duration)
            .ok_or_else(|| Error::invalid_argument("artifact lifetime overflowed"))?,
    )
}

fn timestamp_duration(value: &Timestamp) -> Result<Duration, Error> {
    if value.seconds < 0 || !(0..1_000_000_000).contains(&value.nanos) {
        return Err(Error::protocol("artifact timestamp is invalid"));
    }
    Ok(Duration::new(
        u64::try_from(value.seconds)
            .map_err(|_| Error::protocol("artifact timestamp exceeds client range"))?,
        u32::try_from(value.nanos)
            .map_err(|_| Error::protocol("artifact timestamp nanos are invalid"))?,
    ))
}

fn timestamp_from_system_time(value: SystemTime) -> Result<Timestamp, Error> {
    let value = value
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::invalid_argument("artifact timestamp precedes Unix epoch"))?;
    Ok(Timestamp {
        seconds: i64::try_from(value.as_secs())
            .map_err(|_| Error::invalid_argument("artifact timestamp exceeds protocol range"))?,
        nanos: i32::try_from(value.subsec_nanos()).map_err(|_| {
            Error::invalid_argument("artifact timestamp nanos exceed protocol range")
        })?,
    })
}
