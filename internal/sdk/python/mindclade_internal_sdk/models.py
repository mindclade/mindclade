"""Private Model lifecycle façade over generated protobuf/gRPC contracts."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import cast

from mindclade.common.v1 import resource_reference_pb2
from mindclade.internal.model.v1 import model_service_pb2
from mindclade.job.v1 import operation_pb2
from mindclade.model.v1 import model_commands_pb2, model_pb2, model_release_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._validation import required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .transport import (
    GET_MODEL,
    GET_MODEL_RELEASE,
    LIST_MODEL_RELEASES,
    LIST_MODELS,
    PROMOTE_MODEL_RELEASE,
    REGISTER_MODEL,
    REGISTER_MODEL_RELEASE,
    REVOKE_MODEL_RELEASE,
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


def _model_name(invoker: SyncInvoker | AsyncInvoker, name: str) -> str:
    value = required_text("model name", name)
    prefix = f"{_project_name(invoker)}/models/"
    suffix = value.removeprefix(prefix)
    if not value.startswith(prefix) or not suffix or "/" in suffix:
        raise ValueError("model name must be scoped to the configured project")
    return value


def _release_name(invoker: SyncInvoker | AsyncInvoker, name: str) -> str:
    value = required_text("model release name", name)
    prefix = f"{_project_name(invoker)}/models/"
    suffix = value.removeprefix(prefix)
    parts = suffix.split("/releases/")
    if (
        not value.startswith(prefix)
        or len(parts) != 2
        or not all(parts)
        or any("/" in part for part in parts)
    ):
        raise ValueError("model release name must be scoped to the configured project")
    return value


def _normalize_reference(
    invoker: SyncInvoker | AsyncInvoker,
    reference: resource_reference_pb2.ResourceRef,
    *,
    resource_type: str,
    release: bool,
) -> None:
    name = (
        _release_name(invoker, reference.name) if release else _model_name(invoker, reference.name)
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
        cast(model_service_pb2.RegisterModelResponse, response),
        "operation",
        operation_pb2.Operation,
        label=label,
    )
    required_text("operation id", value.operation_id)
    return value


def _prepare_command[
    CommandT: (
        model_commands_pb2.RegisterModelCommand,
        model_commands_pb2.RegisterModelReleaseCommand,
        model_commands_pb2.PromoteModelReleaseCommand,
        model_commands_pb2.RevokeModelReleaseCommand,
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


class Models:
    """Synchronous generated-type-only Model lifecycle API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def register(
        self,
        command: model_commands_pb2.RegisterModelCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = model_commands_pb2.RegisterModelCommand()
        materialized.CopyFrom(command)
        if materialized.HasField("project") and materialized.project.name != _project_name(
            self._invoker
        ):
            raise ValueError("model project must match the configured project")
        if not materialized.HasField("project"):
            materialized.project.CopyFrom(_project_ref(self._invoker))
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            self._invoker.unary(
                REGISTER_MODEL,
                model_service_pb2.RegisterModelRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="model registration",
        )

    def get(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> model_pb2.Model:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            model_service_pb2.GetModelResponse,
            self._invoker.unary(
                GET_MODEL,
                model_service_pb2.GetModelRequest(
                    name=_model_name(self._invoker, name), if_none_match=if_none_match.strip()
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(response, "model", model_pb2.Model, label="model get")

    def list(
        self,
        request: model_service_pb2.ListModelsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> model_service_pb2.ListModelsResponse:
        materialized = model_service_pb2.ListModelsRequest()
        materialized.CopyFrom(request or model_service_pb2.ListModelsRequest())
        parent = _project_name(self._invoker)
        if materialized.parent and materialized.parent != parent:
            raise ValueError("model list parent must match the configured project")
        materialized.parent = parent
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("model page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            model_service_pb2.ListModelsResponse,
            self._invoker.unary(LIST_MODELS, materialized, call=call, retry_safe=True),
        )

    def register_release(
        self,
        command: model_commands_pb2.RegisterModelReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("model"):
            raise ValueError("release command requires a generated model reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker, materialized.model, resource_type="model", release=False
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            self._invoker.unary(
                REGISTER_MODEL_RELEASE,
                model_service_pb2.RegisterModelReleaseRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="model release registration",
        )

    def get_release(
        self, name: str, *, options: CallOptions | None = None
    ) -> model_release_pb2.ModelRelease:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            model_service_pb2.GetModelReleaseResponse,
            self._invoker.unary(
                GET_MODEL_RELEASE,
                model_service_pb2.GetModelReleaseRequest(name=_release_name(self._invoker, name)),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "model_release", model_release_pb2.ModelRelease, label="model release get"
        )

    def list_releases(
        self,
        request: model_service_pb2.ListModelReleasesRequest,
        *,
        options: CallOptions | None = None,
    ) -> model_service_pb2.ListModelReleasesResponse:
        materialized = model_service_pb2.ListModelReleasesRequest()
        materialized.CopyFrom(request)
        _model_name(self._invoker, materialized.parent)
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("model release page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            model_service_pb2.ListModelReleasesResponse,
            self._invoker.unary(LIST_MODEL_RELEASES, materialized, call=call, retry_safe=True),
        )

    def promote_release(
        self,
        command: model_commands_pb2.PromoteModelReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("model_release"):
            raise ValueError("promotion command requires a generated model release reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker,
            materialized.model_release,
            resource_type="model_release",
            release=True,
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            self._invoker.unary(
                PROMOTE_MODEL_RELEASE,
                model_service_pb2.PromoteModelReleaseRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="model release promotion",
        )

    def revoke_release(
        self,
        command: model_commands_pb2.RevokeModelReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("model_release"):
            raise ValueError("revocation command requires a generated model release reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker,
            materialized.model_release,
            resource_type="model_release",
            release=True,
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            self._invoker.unary(
                REVOKE_MODEL_RELEASE,
                model_service_pb2.RevokeModelReleaseRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="model release revocation",
        )


class AsyncModels:
    """Asyncio generated-type-only Model lifecycle API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def register(
        self,
        command: model_commands_pb2.RegisterModelCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = model_commands_pb2.RegisterModelCommand()
        materialized.CopyFrom(command)
        if materialized.HasField("project") and materialized.project.name != _project_name(
            self._invoker
        ):
            raise ValueError("model project must match the configured project")
        if not materialized.HasField("project"):
            materialized.project.CopyFrom(_project_ref(self._invoker))
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            await self._invoker.unary(
                REGISTER_MODEL,
                model_service_pb2.RegisterModelRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="model registration",
        )

    async def get(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> model_pb2.Model:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            model_service_pb2.GetModelResponse,
            await self._invoker.unary(
                GET_MODEL,
                model_service_pb2.GetModelRequest(
                    name=_model_name(self._invoker, name), if_none_match=if_none_match.strip()
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(response, "model", model_pb2.Model, label="model get")

    async def list(
        self,
        request: model_service_pb2.ListModelsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> model_service_pb2.ListModelsResponse:
        materialized = model_service_pb2.ListModelsRequest()
        materialized.CopyFrom(request or model_service_pb2.ListModelsRequest())
        parent = _project_name(self._invoker)
        if materialized.parent and materialized.parent != parent:
            raise ValueError("model list parent must match the configured project")
        materialized.parent = parent
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("model page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            model_service_pb2.ListModelsResponse,
            await self._invoker.unary(LIST_MODELS, materialized, call=call, retry_safe=True),
        )

    async def register_release(
        self,
        command: model_commands_pb2.RegisterModelReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("model"):
            raise ValueError("release command requires a generated model reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker, materialized.model, resource_type="model", release=False
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            await self._invoker.unary(
                REGISTER_MODEL_RELEASE,
                model_service_pb2.RegisterModelReleaseRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="model release registration",
        )

    async def get_release(
        self, name: str, *, options: CallOptions | None = None
    ) -> model_release_pb2.ModelRelease:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            model_service_pb2.GetModelReleaseResponse,
            await self._invoker.unary(
                GET_MODEL_RELEASE,
                model_service_pb2.GetModelReleaseRequest(name=_release_name(self._invoker, name)),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "model_release", model_release_pb2.ModelRelease, label="model release get"
        )

    async def list_releases(
        self,
        request: model_service_pb2.ListModelReleasesRequest,
        *,
        options: CallOptions | None = None,
    ) -> model_service_pb2.ListModelReleasesResponse:
        materialized = model_service_pb2.ListModelReleasesRequest()
        materialized.CopyFrom(request)
        _model_name(self._invoker, materialized.parent)
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("model release page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            model_service_pb2.ListModelReleasesResponse,
            await self._invoker.unary(
                LIST_MODEL_RELEASES, materialized, call=call, retry_safe=True
            ),
        )

    async def promote_release(
        self,
        command: model_commands_pb2.PromoteModelReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("model_release"):
            raise ValueError("promotion command requires a generated model release reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker,
            materialized.model_release,
            resource_type="model_release",
            release=True,
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            await self._invoker.unary(
                PROMOTE_MODEL_RELEASE,
                model_service_pb2.PromoteModelReleaseRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="model release promotion",
        )

    async def revoke_release(
        self,
        command: model_commands_pb2.RevokeModelReleaseCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if not command.HasField("model_release"):
            raise ValueError("revocation command requires a generated model release reference")
        materialized = copy.deepcopy(command)
        _normalize_reference(
            self._invoker,
            materialized.model_release,
            resource_type="model_release",
            release=True,
        )
        materialized, call = _prepare_command(self._invoker, materialized, options)
        return _operation(
            await self._invoker.unary(
                REVOKE_MODEL_RELEASE,
                model_service_pb2.RevokeModelReleaseRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
            label="model release revocation",
        )
