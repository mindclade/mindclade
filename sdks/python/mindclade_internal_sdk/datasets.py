"""Private Dataset lifecycle façade over generated protobuf/gRPC contracts."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import cast

from mindclade.common.v1 import resource_reference_pb2
from mindclade.dataset.v1 import dataset_commands_pb2, dataset_pb2, dataset_release_pb2
from mindclade.internal.dataset.v1 import dataset_service_pb2
from mindclade.operation.v1 import operation_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._validation import required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .transport import (
    CREATE_DATASET,
    GET_DATASET,
    GET_DATASET_RELEASE,
    LIST_DATASET_RELEASES,
    LIST_DATASETS,
    PUBLISH_DATASET_RELEASE,
    REVOKE_DATASET_RELEASE,
    UPDATE_DATASET,
)


def _project_name(invoker: SyncInvoker | AsyncInvoker) -> str:
    return invoker.config.project_parent


def _project_ref(invoker: SyncInvoker | AsyncInvoker) -> resource_reference_pb2.ResourceRef:
    config = invoker.config
    return resource_reference_pb2.ResourceRef(
        resource_type="project",
        resource_id=config.project_id,
        tenant_id=config.tenant_id,
        project_id=config.project_id,
        name=config.project_parent,
    )


def _mutation_options(command_key: str, options: CallOptions | None) -> CallOptions | None:
    if not command_key or (options is not None and options.idempotency_key is not None):
        return options
    return (
        replace(options, idempotency_key=command_key)
        if options
        else CallOptions(idempotency_key=command_key)
    )


def _dataset_name(invoker: SyncInvoker | AsyncInvoker, name: str) -> str:
    value = required_text("dataset name", name)
    prefix = f"{_project_name(invoker)}/datasets/"
    suffix = value.removeprefix(prefix)
    if not value.startswith(prefix) or not suffix or "/" in suffix:
        raise ValueError("dataset name must be scoped to the configured project")
    return value


def _release_name(invoker: SyncInvoker | AsyncInvoker, name: str) -> str:
    value = required_text("dataset release name", name)
    prefix = f"{_project_name(invoker)}/datasets/"
    suffix = value.removeprefix(prefix)
    parts = suffix.split("/releases/")
    if (
        not value.startswith(prefix)
        or len(parts) != 2
        or not all(parts)
        or any("/" in part for part in parts)
    ):
        raise ValueError("dataset release name must be scoped to the configured project")
    return value


def _normalize_reference(
    invoker: SyncInvoker | AsyncInvoker,
    reference: resource_reference_pb2.ResourceRef,
    *,
    resource_type: str,
    release: bool,
) -> None:
    name = (
        _release_name(invoker, reference.name)
        if release
        else _dataset_name(invoker, reference.name)
    )
    resource_id = name.rsplit("/", 1)[-1]
    config = invoker.config
    if reference.resource_type and reference.resource_type != resource_type:
        raise ValueError("resource reference type does not match the command")
    if reference.resource_id and reference.resource_id != resource_id:
        raise ValueError("resource reference id does not match its name")
    if reference.tenant_id and reference.tenant_id != config.tenant_id:
        raise ValueError("resource reference tenant does not match client scope")
    if reference.project_id and reference.project_id != config.project_id:
        raise ValueError("resource reference project does not match client scope")
    reference.resource_type = resource_type
    reference.resource_id = resource_id
    reference.tenant_id = config.tenant_id
    reference.project_id = config.project_id


def _operation(response: object, *, label: str) -> operation_pb2.Operation:
    value = required_response_message(
        cast(dataset_service_pb2.CreateDatasetResponse, response),
        "operation",
        operation_pb2.Operation,
        label=label,
    )
    required_text("operation id", value.operation_id)
    return value


def _prepare_command[
    CommandT: (
        dataset_commands_pb2.CreateDatasetCommand,
        dataset_commands_pb2.UpdateDatasetCommand,
        dataset_commands_pb2.PublishDatasetReleaseCommand,
        dataset_commands_pb2.RevokeDatasetReleaseCommand,
    )
](
    invoker: SyncInvoker | AsyncInvoker,
    command: CommandT,
    options: CallOptions | None,
) -> tuple[CommandT, PreparedCall]:
    materialized = copy.deepcopy(command)
    key = materialized.context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    materialized.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(materialized))
    )
    return materialized, call


class Datasets:
    """Synchronous generated-type-only Dataset lifecycle API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def create(
        self,
        command: dataset_commands_pb2.CreateDatasetCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = dataset_commands_pb2.CreateDatasetCommand()
        materialized.CopyFrom(command)
        if materialized.HasField("project"):
            if materialized.project.name != _project_name(self._invoker):
                raise ValueError("dataset project must match the configured project")
        else:
            materialized.project.CopyFrom(_project_ref(self._invoker))
        materialized, call = _prepare_command(self._invoker, materialized, options)
        response = self._invoker.unary(
            CREATE_DATASET,
            dataset_service_pb2.CreateDatasetRequest(command=materialized),
            call=call,
            retry_safe=True,
        )
        return _operation(response, label="dataset create")

    def get(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> dataset_pb2.Dataset:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            dataset_service_pb2.GetDatasetResponse,
            self._invoker.unary(
                GET_DATASET,
                dataset_service_pb2.GetDatasetRequest(
                    name=_dataset_name(self._invoker, name), if_none_match=if_none_match.strip()
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "dataset", dataset_pb2.Dataset, label="dataset get"
        )

    def list(
        self,
        request: dataset_service_pb2.ListDatasetsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> dataset_service_pb2.ListDatasetsResponse:
        materialized = dataset_service_pb2.ListDatasetsRequest()
        if request is not None:
            materialized.CopyFrom(request)
        parent = _project_name(self._invoker)
        if materialized.parent and materialized.parent != parent:
            raise ValueError("dataset list parent must match the configured project")
        materialized.parent = parent
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("dataset page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            dataset_service_pb2.ListDatasetsResponse,
            self._invoker.unary(LIST_DATASETS, materialized, call=call, retry_safe=True),
        )

    def update(
        self,
        command: dataset_commands_pb2.UpdateDatasetCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("dataset"):
            raise ValueError("update command requires a generated dataset")
        _dataset_name(self._invoker, command.dataset.name)
        materialized, call = _prepare_command(self._invoker, command, options)
        response = self._invoker.unary(
            UPDATE_DATASET,
            dataset_service_pb2.UpdateDatasetRequest(command=materialized),
            call=call,
            retry_safe=True,
        )
        return _operation(response, label="dataset update")

    def publish_release(
        self,
        command: dataset_commands_pb2.PublishDatasetReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("dataset"):
            raise ValueError("publish command requires a generated dataset reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker, materialized.dataset, resource_type="dataset", release=False
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        response = self._invoker.unary(
            PUBLISH_DATASET_RELEASE,
            dataset_service_pb2.PublishDatasetReleaseRequest(command=materialized),
            call=call,
            retry_safe=True,
        )
        return _operation(response, label="dataset release publication")

    def revoke_release(
        self,
        command: dataset_commands_pb2.RevokeDatasetReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("dataset_release"):
            raise ValueError("revoke command requires a generated dataset release reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker,
            materialized.dataset_release,
            resource_type="dataset_release",
            release=True,
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        response = self._invoker.unary(
            REVOKE_DATASET_RELEASE,
            dataset_service_pb2.RevokeDatasetReleaseRequest(command=materialized),
            call=call,
            retry_safe=True,
        )
        return _operation(response, label="dataset release revocation")

    def get_release(
        self, name: str, *, options: CallOptions | None = None
    ) -> dataset_release_pb2.DatasetRelease:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            dataset_service_pb2.GetDatasetReleaseResponse,
            self._invoker.unary(
                GET_DATASET_RELEASE,
                dataset_service_pb2.GetDatasetReleaseRequest(
                    name=_release_name(self._invoker, name)
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "dataset_release",
            dataset_release_pb2.DatasetRelease,
            label="dataset release get",
        )

    def list_releases(
        self,
        request: dataset_service_pb2.ListDatasetReleasesRequest,
        *,
        options: CallOptions | None = None,
    ) -> dataset_service_pb2.ListDatasetReleasesResponse:
        materialized = dataset_service_pb2.ListDatasetReleasesRequest()
        materialized.CopyFrom(request)
        _dataset_name(self._invoker, materialized.parent)
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("dataset release page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            dataset_service_pb2.ListDatasetReleasesResponse,
            self._invoker.unary(LIST_DATASET_RELEASES, materialized, call=call, retry_safe=True),
        )


class AsyncDatasets:
    """Asyncio generated-type-only Dataset lifecycle API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def create(
        self,
        command: dataset_commands_pb2.CreateDatasetCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = dataset_commands_pb2.CreateDatasetCommand()
        materialized.CopyFrom(command)
        if materialized.HasField("project") and materialized.project.name != _project_name(
            self._invoker
        ):
            raise ValueError("dataset project must match the configured project")
        if not materialized.HasField("project"):
            materialized.project.CopyFrom(_project_ref(self._invoker))
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            await self._invoker.unary(
                CREATE_DATASET,
                dataset_service_pb2.CreateDatasetRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="dataset create",
        )

    async def get(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> dataset_pb2.Dataset:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            dataset_service_pb2.GetDatasetResponse,
            await self._invoker.unary(
                GET_DATASET,
                dataset_service_pb2.GetDatasetRequest(
                    name=_dataset_name(self._invoker, name), if_none_match=if_none_match.strip()
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "dataset", dataset_pb2.Dataset, label="dataset get"
        )

    async def list(
        self,
        request: dataset_service_pb2.ListDatasetsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> dataset_service_pb2.ListDatasetsResponse:
        materialized = dataset_service_pb2.ListDatasetsRequest()
        materialized.CopyFrom(request or dataset_service_pb2.ListDatasetsRequest())
        parent = _project_name(self._invoker)
        if materialized.parent and materialized.parent != parent:
            raise ValueError("dataset list parent must match the configured project")
        materialized.parent = parent
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("dataset page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            dataset_service_pb2.ListDatasetsResponse,
            await self._invoker.unary(LIST_DATASETS, materialized, call=call, retry_safe=True),
        )

    async def update(
        self,
        command: dataset_commands_pb2.UpdateDatasetCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("dataset"):
            raise ValueError("update command requires a generated dataset")
        _dataset_name(self._invoker, command.dataset.name)
        materialized, call = _prepare_command(self._invoker, command, options)
        return _operation(
            await self._invoker.unary(
                UPDATE_DATASET,
                dataset_service_pb2.UpdateDatasetRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="dataset update",
        )

    async def publish_release(
        self,
        command: dataset_commands_pb2.PublishDatasetReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("dataset"):
            raise ValueError("publish command requires a generated dataset reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker, materialized.dataset, resource_type="dataset", release=False
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            await self._invoker.unary(
                PUBLISH_DATASET_RELEASE,
                dataset_service_pb2.PublishDatasetReleaseRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="dataset release publication",
        )

    async def revoke_release(
        self,
        command: dataset_commands_pb2.RevokeDatasetReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("dataset_release"):
            raise ValueError("revoke command requires a generated dataset release reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker,
            materialized.dataset_release,
            resource_type="dataset_release",
            release=True,
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            await self._invoker.unary(
                REVOKE_DATASET_RELEASE,
                dataset_service_pb2.RevokeDatasetReleaseRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="dataset release revocation",
        )

    async def get_release(
        self, name: str, *, options: CallOptions | None = None
    ) -> dataset_release_pb2.DatasetRelease:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            dataset_service_pb2.GetDatasetReleaseResponse,
            await self._invoker.unary(
                GET_DATASET_RELEASE,
                dataset_service_pb2.GetDatasetReleaseRequest(
                    name=_release_name(self._invoker, name)
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "dataset_release",
            dataset_release_pb2.DatasetRelease,
            label="dataset release get",
        )

    async def list_releases(
        self,
        request: dataset_service_pb2.ListDatasetReleasesRequest,
        *,
        options: CallOptions | None = None,
    ) -> dataset_service_pb2.ListDatasetReleasesResponse:
        materialized = dataset_service_pb2.ListDatasetReleasesRequest()
        materialized.CopyFrom(request)
        _dataset_name(self._invoker, materialized.parent)
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("dataset release page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            dataset_service_pb2.ListDatasetReleasesResponse,
            await self._invoker.unary(
                LIST_DATASET_RELEASES, materialized, call=call, retry_safe=True
            ),
        )
