"""Private Mindclade SDK over authoritative generated Protobuf/gRPC clients."""

from mindclade.artifact.v1.artifact_reference_pb2 import ArtifactRef

from ._metadata import (
    CREDENTIAL_METADATA_KEYS,
    SAFE_RESPONSE_METADATA_KEYS,
    is_credential_metadata_key,
)
from ._raw import (
    AsyncRawResponseProxy,
    AsyncWithRawResponse,
    RawResponse,
    RawResponseProxy,
    WithRawResponse,
)
from ._retry import DEFAULT_JITTER, FixedJitter, JitterSource, SystemJitter
from .admin import Admin, AsyncAdmin
from .agents import Agents, AsyncAgents
from .artifacts import Artifacts, AsyncArtifacts
from .auth import (
    AccessToken,
    AsyncGoogleWorkloadIdentityProvider,
    AsyncTokenProvider,
    GoogleWorkloadIdentityProvider,
    SyncTokenProvider,
)
from .calls import CallOptions, Observer, PaginationLimits, RpcObservation, apaginate, paginate
from .client import AsyncClient, Client
from .config import ClientConfig, ConfigurationError, Environment, RetryPolicy
from .datasets import AsyncDatasets, Datasets
from .errors import (
    AuthenticationError,
    AuthorizationError,
    CancelledError,
    ConflictError,
    DeadlineExceededError,
    FenceState,
    FieldViolation,
    InvalidRequestError,
    MindcladeError,
    NotFoundError,
    OperationFailedError,
    OperationTimeoutError,
    PaginationLimitError,
    PreconditionViolation,
    ProtocolError,
    QuotaError,
    QuotaState,
    RateLimitError,
    RetryableServiceError,
    RetryTrace,
    TransportError,
    UnavailableError,
    ValidationError,
    WorkflowRunFailedError,
    error_from_detail,
)
from .evaluations import AsyncEvaluations, Evaluations
from .events import (
    EventRejectedError,
    JobRequestedDelivery,
    decode_job_requested_delivery,
)
from .experiments import AsyncExperiments, Experiments
from .generated import AsyncGeneratedRPCs, GeneratedRPCs
from .inference import AsyncInference, Inference
from .jobs import AsyncJobs, Jobs
from .models import AsyncModels, Models
from .operations import AsyncOperations, Operations
from .pagination import AsyncPage, Page, PageBudget
from .policies import AsyncPolicies, Policies
from .runs import AsyncRuns, AttemptLease, LeaseCredential, Runs
from .training import AsyncTraining, Training
from .workflows import Approvals, AsyncApprovals, AsyncWorkflows, Workflows

__all__ = [
    "CREDENTIAL_METADATA_KEYS",
    "DEFAULT_JITTER",
    "SAFE_RESPONSE_METADATA_KEYS",
    "AccessToken",
    "Admin",
    "Agents",
    "Approvals",
    "ArtifactRef",
    "Artifacts",
    "AsyncAdmin",
    "AsyncAgents",
    "AsyncApprovals",
    "AsyncArtifacts",
    "AsyncClient",
    "AsyncDatasets",
    "AsyncEvaluations",
    "AsyncExperiments",
    "AsyncGeneratedRPCs",
    "AsyncGoogleWorkloadIdentityProvider",
    "AsyncInference",
    "AsyncJobs",
    "AsyncModels",
    "AsyncOperations",
    "AsyncPage",
    "AsyncPolicies",
    "AsyncRawResponseProxy",
    "AsyncRuns",
    "AsyncTokenProvider",
    "AsyncTraining",
    "AsyncWithRawResponse",
    "AsyncWorkflows",
    "AttemptLease",
    "AuthenticationError",
    "AuthorizationError",
    "CallOptions",
    "CancelledError",
    "Client",
    "ClientConfig",
    "ConfigurationError",
    "ConflictError",
    "Datasets",
    "DeadlineExceededError",
    "Environment",
    "Evaluations",
    "EventRejectedError",
    "Experiments",
    "FenceState",
    "FieldViolation",
    "FixedJitter",
    "GeneratedRPCs",
    "GoogleWorkloadIdentityProvider",
    "Inference",
    "InvalidRequestError",
    "JitterSource",
    "JobRequestedDelivery",
    "Jobs",
    "LeaseCredential",
    "MindcladeError",
    "Models",
    "NotFoundError",
    "Observer",
    "OperationFailedError",
    "OperationTimeoutError",
    "Operations",
    "Page",
    "PageBudget",
    "PaginationLimitError",
    "PaginationLimits",
    "Policies",
    "PreconditionViolation",
    "ProtocolError",
    "QuotaError",
    "QuotaState",
    "RateLimitError",
    "RawResponse",
    "RawResponseProxy",
    "RetryPolicy",
    "RetryTrace",
    "RetryableServiceError",
    "RpcObservation",
    "Runs",
    "SyncTokenProvider",
    "SystemJitter",
    "Training",
    "TransportError",
    "UnavailableError",
    "ValidationError",
    "WithRawResponse",
    "WorkflowRunFailedError",
    "Workflows",
    "apaginate",
    "decode_job_requested_delivery",
    "error_from_detail",
    "is_credential_metadata_key",
    "paginate",
]
