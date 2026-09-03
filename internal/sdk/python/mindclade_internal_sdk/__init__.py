"""Private Mindclade SDK over authoritative generated Protobuf/gRPC clients.

``resources`` and ``testing`` are re-exported as attributes of this package
because they are part of its supported surface: consumers build generated
resource values through the first and drive hermetic tests through the second,
and both are documented in ``README.md``. Importing the package therefore makes
``mindclade_internal_sdk.resources`` and ``mindclade_internal_sdk.testing``
usable without a separate submodule import.
"""

from mindclade.artifact.v1.artifact_reference_pb2 import ArtifactRef

from . import resources, testing
from ._env import ENVIRONMENT_VARIABLES, config_from_env
from ._logging import LOG_LEVELS, LOGGER_NAME, LoggingObserver, default_observer, log_level_from_env
from ._metadata import (
    CREDENTIAL_METADATA_KEYS,
    SAFE_RESPONSE_METADATA_KEYS,
    is_credential_metadata_key,
)
from ._middleware import AsyncCredentialShield, CredentialShield
from ._platform import PlatformMetadata
from ._raw import (
    AsyncRawResponseProxy,
    AsyncWithRawResponse,
    RawResponse,
    RawResponseProxy,
    WithRawResponse,
)
from ._retry import DEFAULT_JITTER, FixedJitter, JitterSource, SystemJitter
from ._version import SDK_NAME, USER_AGENT, __version__
from ._watch import AsyncWatchStream, WatchSpec, WatchStream
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
from .cross_field_generated import (
    CROSS_FIELD_RULES,
    CrossFieldError,
    validate_cross_field,
)
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
    "CROSS_FIELD_RULES",
    "DEFAULT_JITTER",
    "ENVIRONMENT_VARIABLES",
    "LOGGER_NAME",
    "LOG_LEVELS",
    "SAFE_RESPONSE_METADATA_KEYS",
    "SDK_NAME",
    "USER_AGENT",
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
    "AsyncCredentialShield",
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
    "AsyncWatchStream",
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
    "CredentialShield",
    "CrossFieldError",
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
    "LoggingObserver",
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
    "PlatformMetadata",
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
    "WatchSpec",
    "WatchStream",
    "WithRawResponse",
    "WorkflowRunFailedError",
    "Workflows",
    "__version__",
    "apaginate",
    "config_from_env",
    "decode_job_requested_delivery",
    "default_observer",
    "error_from_detail",
    "is_credential_metadata_key",
    "log_level_from_env",
    "paginate",
    "resources",
    "testing",
    "validate_cross_field",
]
