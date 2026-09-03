"""Private Mindclade SDK over authoritative generated Protobuf/gRPC clients."""

from mindclade.artifact.v1.artifact_reference_pb2 import ArtifactRef

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
    InvalidRequestError,
    MindcladeError,
    NotFoundError,
    OperationFailedError,
    OperationTimeoutError,
    PaginationLimitError,
    ProtocolError,
    RateLimitError,
    TransportError,
    UnavailableError,
    WorkflowRunFailedError,
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
from .policies import AsyncPolicies, Policies
from .runs import AsyncRuns, AttemptLease, LeaseCredential, Runs
from .training import AsyncTraining, Training
from .workflows import Approvals, AsyncApprovals, AsyncWorkflows, Workflows

__all__ = [
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
    "AsyncPolicies",
    "AsyncRuns",
    "AsyncTokenProvider",
    "AsyncTraining",
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
    "GeneratedRPCs",
    "GoogleWorkloadIdentityProvider",
    "Inference",
    "InvalidRequestError",
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
    "PaginationLimitError",
    "PaginationLimits",
    "Policies",
    "ProtocolError",
    "RateLimitError",
    "RetryPolicy",
    "RpcObservation",
    "Runs",
    "SyncTokenProvider",
    "Training",
    "TransportError",
    "UnavailableError",
    "WorkflowRunFailedError",
    "Workflows",
    "apaginate",
    "decode_job_requested_delivery",
    "paginate",
]
