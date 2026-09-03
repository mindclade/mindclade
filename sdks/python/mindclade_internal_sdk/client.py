"""Private synchronous and asynchronous Mindclade client façades."""

from __future__ import annotations

from types import TracebackType
from typing import Any

from ._env import config_from_env
from ._invocation import AsyncInvoker, SyncInvoker
from ._logging import default_observer
from .admin import Admin, AsyncAdmin
from .agents import Agents, AsyncAgents
from .artifacts import Artifacts, AsyncArtifacts
from .auth import AsyncTokenProvider, SyncTokenProvider
from .calls import Observer
from .config import ClientConfig
from .datasets import AsyncDatasets, Datasets
from .evaluations import AsyncEvaluations, Evaluations
from .experiments import AsyncExperiments, Experiments
from .generated import AsyncGeneratedRPCs, GeneratedRPCs
from .inference import AsyncInference, Inference
from .jobs import AsyncJobs, Jobs
from .models import AsyncModels, Models
from .operations import AsyncOperations, Operations
from .policies import AsyncPolicies, Policies
from .runs import AsyncRuns, Runs
from .training import AsyncTraining, Training
from .transport import (
    AsyncTransport,
    GrpcAsyncTransport,
    GrpcSyncTransport,
    SyncTransport,
)
from .workflows import Approvals, AsyncApprovals, AsyncWorkflows, Workflows


class Client:
    """Thread-safe façade when its injected token provider/transport are thread-safe."""

    def __init__(
        self,
        config: ClientConfig,
        *,
        transport: SyncTransport | None = None,
        observer: Observer | None = None,
        close_transport: bool = True,
    ) -> None:
        self.config = config
        self._transport = transport or GrpcSyncTransport(config)
        self._close_transport = close_transport
        invoker = SyncInvoker(config, self._transport, observer=observer)
        self.admin = Admin(invoker)
        self.agents = Agents(invoker)
        self.operations = Operations(invoker)
        self.policies = Policies(invoker)
        self.artifacts = Artifacts(invoker)
        self.training = Training(invoker)
        self.datasets = Datasets(invoker)
        self.evaluations = Evaluations(invoker)
        self.experiments = Experiments(invoker)
        self.models = Models(invoker)
        self.inference = Inference(invoker)
        self.jobs = Jobs(invoker)
        self.runs = Runs(invoker)
        self.workflows = Workflows(invoker)
        self.approvals = Approvals(invoker)
        self.generated = GeneratedRPCs(invoker)
        self._closed = False

    @classmethod
    def from_env(
        cls,
        *,
        token_provider: SyncTokenProvider | None = None,
        transport: SyncTransport | None = None,
        observer: Observer | None = None,
        close_transport: bool = True,
        **overrides: Any,
    ) -> Client:
        """Build a client from ``MINDCLADE_*`` variables.

        This classmethod is the SDK's only environment-reading path: the
        ordinary constructor reads nothing, so an explicitly built
        :class:`ClientConfig` is never quietly overridden by the shell. There
        is no credential variable — ``token_provider`` stays an explicit
        argument. Keyword ``overrides`` beat the environment.
        """

        return cls(
            config_from_env(token_provider=token_provider, **overrides),
            transport=transport,
            observer=observer if observer is not None else default_observer(),
            close_transport=close_transport,
        )

    def close(self) -> None:
        if not self._closed and self._close_transport:
            self._transport.close()
        self._closed = True

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()


class AsyncClient:
    """Asyncio-native façade; it never runs blocking RPC or credential calls."""

    def __init__(
        self,
        config: ClientConfig,
        *,
        transport: AsyncTransport | None = None,
        observer: Observer | None = None,
        close_transport: bool = True,
    ) -> None:
        self.config = config
        self._transport = transport or GrpcAsyncTransport(config)
        self._close_transport = close_transport
        invoker = AsyncInvoker(config, self._transport, observer=observer)
        self.admin = AsyncAdmin(invoker)
        self.agents = AsyncAgents(invoker)
        self.operations = AsyncOperations(invoker)
        self.policies = AsyncPolicies(invoker)
        self.artifacts = AsyncArtifacts(invoker)
        self.training = AsyncTraining(invoker)
        self.datasets = AsyncDatasets(invoker)
        self.evaluations = AsyncEvaluations(invoker)
        self.experiments = AsyncExperiments(invoker)
        self.models = AsyncModels(invoker)
        self.inference = AsyncInference(invoker)
        self.jobs = AsyncJobs(invoker)
        self.runs = AsyncRuns(invoker)
        self.workflows = AsyncWorkflows(invoker)
        self.approvals = AsyncApprovals(invoker)
        self.generated = AsyncGeneratedRPCs(invoker)
        self._closed = False

    @classmethod
    def from_env(
        cls,
        *,
        token_provider: AsyncTokenProvider | None = None,
        transport: AsyncTransport | None = None,
        observer: Observer | None = None,
        close_transport: bool = True,
        **overrides: Any,
    ) -> AsyncClient:
        """Build an asyncio client from ``MINDCLADE_*`` variables.

        The same rules as :meth:`Client.from_env` apply: this is the only
        environment-reading path, and no variable may ever supply a credential.
        """

        return cls(
            config_from_env(token_provider=token_provider, **overrides),
            transport=transport,
            observer=observer if observer is not None else default_observer(),
            close_transport=close_transport,
        )

    async def close(self) -> None:
        if not self._closed and self._close_transport:
            await self._transport.close()
        self._closed = True

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        await self.close()
