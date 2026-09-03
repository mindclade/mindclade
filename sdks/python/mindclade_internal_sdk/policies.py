"""Private Policy lifecycle and fail-closed authorization façade."""

from __future__ import annotations

import copy
import re
from dataclasses import replace
from typing import cast

from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.internal.policy.v1 import policy_service_pb2
from mindclade.operation.v1 import operation_pb2
from mindclade.policy.v1 import authorization_decision_pb2, policy_reference_pb2, use_policy_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._validation import required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .transport import (
    ACTIVATE_USE_POLICY,
    CREATE_USE_POLICY,
    EVALUATE_AUTHORIZATION,
    GET_USE_POLICY,
    LIST_USE_POLICIES,
    RESOLVE_POLICY_SNAPSHOT,
    REVOKE_USE_POLICY,
    UPDATE_USE_POLICY,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _project(invoker: SyncInvoker | AsyncInvoker) -> str:
    return invoker.config.project_parent


def _policy_name(invoker: SyncInvoker | AsyncInvoker, value: str) -> str:
    name = required_text("policy name", value)
    prefix = f"{_project(invoker)}/usePolicies/"
    suffix = name.removeprefix(prefix)
    if not name.startswith(prefix) or not suffix or "/" in suffix:
        raise ValueError("policy name must be scoped to the configured project")
    return name


def _mutation_options(key: str, options: CallOptions | None) -> CallOptions | None:
    if not key or (options is not None and options.idempotency_key is not None):
        return options
    return replace(options, idempotency_key=key) if options else CallOptions(idempotency_key=key)


def _prepare_mutation[
    RequestT: (
        policy_service_pb2.CreateUsePolicyRequest,
        policy_service_pb2.UpdateUsePolicyRequest,
        policy_service_pb2.ActivateUsePolicyRequest,
        policy_service_pb2.RevokeUsePolicyRequest,
    )
](
    invoker: SyncInvoker | AsyncInvoker,
    request: RequestT,
    options: CallOptions | None,
) -> tuple[RequestT, PreparedCall]:
    materialized = copy.deepcopy(request)
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


def _operation(response: object, label: str) -> operation_pb2.Operation:
    operation = required_response_message(
        cast(policy_service_pb2.CreateUsePolicyResponse, response),
        "operation",
        operation_pb2.Operation,
        label=label,
    )
    required_text("operation id", operation.operation_id)
    return operation


def _prepare_evaluation(
    invoker: SyncInvoker | AsyncInvoker,
    request: policy_service_pb2.EvaluateAuthorizationRequest,
    options: CallOptions | None,
) -> tuple[policy_service_pb2.EvaluateAuthorizationRequest, PreparedCall]:
    materialized = copy.deepcopy(request)
    if not materialized.action.strip() or not materialized.HasField("resource"):
        raise ValueError("authorization evaluation requires an action and resource")
    if not _DIGEST.fullmatch(materialized.intent_digest):
        raise ValueError("authorization intent_digest must be lowercase sha256")
    project = _project(invoker)
    if materialized.resource.name != project and not materialized.resource.name.startswith(
        f"{project}/"
    ):
        raise ValueError("authorization resource is outside the configured project")
    config = invoker.config
    if materialized.resource.tenant_id not in ("", config.tenant_id) or (
        materialized.resource.project_id not in ("", config.project_id)
    ):
        raise ValueError("authorization resource scope conflicts with client identity")
    materialized.tenant_id = config.tenant_id
    materialized.project_id = config.project_id
    materialized.principal_ref = config.principal_id
    materialized.resource.tenant_id = config.tenant_id
    materialized.resource.project_id = config.project_id
    key = materialized.context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=config.default_timeout,
        require_idempotency=True,
    )
    authoritative = command_context(config, call, request_digest="")
    materialized.deadline.CopyFrom(authoritative.deadline)
    authoritative.canonical_request_digest = canonical_digest(materialized)
    materialized.context.CopyFrom(authoritative)
    return materialized, call


class Policies:
    """Synchronous generated-type-only Policy API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def evaluate(
        self,
        request: policy_service_pb2.EvaluateAuthorizationRequest,
        *,
        options: CallOptions | None = None,
    ) -> authorization_decision_pb2.AuthorizationDecision:
        materialized, call = _prepare_evaluation(self._invoker, request, options)
        response = cast(
            policy_service_pb2.EvaluateAuthorizationResponse,
            self._invoker.unary(EVALUATE_AUTHORIZATION, materialized, call=call, retry_safe=True),
        )
        return required_response_message(
            response,
            "decision",
            authorization_decision_pb2.AuthorizationDecision,
            label="authorization evaluation",
        )

    def create(
        self,
        request: policy_service_pb2.CreateUsePolicyRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        if not materialized.HasField("use_policy") or not materialized.use_policy_id.strip():
            raise ValueError("policy create requires a generated policy and policy ID")
        parent = _project(self._invoker)
        if materialized.parent not in ("", parent):
            raise ValueError("policy parent must match the configured project")
        materialized.parent = parent
        materialized, call = _prepare_mutation(self._invoker, materialized, options)
        return _operation(
            self._invoker.unary(CREATE_USE_POLICY, materialized, call=call, retry_safe=True),
            "policy create",
        )

    def update(
        self,
        request: policy_service_pb2.UpdateUsePolicyRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if (
            not request.HasField("use_policy")
            or not request.HasField("update_mask")
            or not request.etag.strip()
        ):
            raise ValueError("policy update requires a policy, field mask, and etag")
        _policy_name(self._invoker, request.use_policy.name)
        materialized, call = _prepare_mutation(self._invoker, request, options)
        return _operation(
            self._invoker.unary(UPDATE_USE_POLICY, materialized, call=call, retry_safe=True),
            "policy update",
        )

    def get(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> use_policy_pb2.UsePolicy:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            policy_service_pb2.GetUsePolicyResponse,
            self._invoker.unary(
                GET_USE_POLICY,
                policy_service_pb2.GetUsePolicyRequest(
                    name=_policy_name(self._invoker, name), if_none_match=if_none_match.strip()
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "use_policy", use_policy_pb2.UsePolicy, label="policy get"
        )

    def list(
        self,
        request: policy_service_pb2.ListUsePoliciesRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> policy_service_pb2.ListUsePoliciesResponse:
        materialized = policy_service_pb2.ListUsePoliciesRequest()
        if request is not None:
            materialized.CopyFrom(request)
        parent = _project(self._invoker)
        if materialized.parent not in ("", parent):
            raise ValueError("policy list parent must match the configured project")
        materialized.parent = parent
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("policy page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            policy_service_pb2.ListUsePoliciesResponse,
            self._invoker.unary(LIST_USE_POLICIES, materialized, call=call, retry_safe=True),
        )

    def activate(
        self, name: str, etag: str, *, options: CallOptions | None = None
    ) -> operation_pb2.Operation:
        request = policy_service_pb2.ActivateUsePolicyRequest(
            name=_policy_name(self._invoker, name), etag=required_text("etag", etag)
        )
        request, call = _prepare_mutation(self._invoker, request, options)
        return _operation(
            self._invoker.unary(ACTIVATE_USE_POLICY, request, call=call, retry_safe=True),
            "policy activation",
        )

    def revoke(
        self,
        name: str,
        etag: str,
        reason_code: str,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        request = policy_service_pb2.RevokeUsePolicyRequest(
            name=_policy_name(self._invoker, name),
            etag=required_text("etag", etag),
            reason_code=required_text("reason_code", reason_code),
        )
        request, call = _prepare_mutation(self._invoker, request, options)
        return _operation(
            self._invoker.unary(REVOKE_USE_POLICY, request, call=call, retry_safe=True),
            "policy revocation",
        )

    def resolve_snapshot(
        self,
        name: str,
        effective_time: Timestamp,
        *,
        options: CallOptions | None = None,
    ) -> policy_reference_pb2.PolicyReference:
        effective_time.ToDatetime()
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            policy_service_pb2.ResolvePolicySnapshotResponse,
            self._invoker.unary(
                RESOLVE_POLICY_SNAPSHOT,
                policy_service_pb2.ResolvePolicySnapshotRequest(
                    name=_policy_name(self._invoker, name), effective_time=effective_time
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "policy_snapshot",
            policy_reference_pb2.PolicyReference,
            label="policy snapshot resolution",
        )


class AsyncPolicies:
    """Asyncio variant of the generated-type-only Policy API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def evaluate(
        self,
        request: policy_service_pb2.EvaluateAuthorizationRequest,
        *,
        options: CallOptions | None = None,
    ) -> authorization_decision_pb2.AuthorizationDecision:
        materialized, call = _prepare_evaluation(self._invoker, request, options)
        response = cast(
            policy_service_pb2.EvaluateAuthorizationResponse,
            await self._invoker.unary(
                EVALUATE_AUTHORIZATION, materialized, call=call, retry_safe=True
            ),
        )
        return required_response_message(
            response,
            "decision",
            authorization_decision_pb2.AuthorizationDecision,
            label="authorization evaluation",
        )

    async def create(
        self,
        request: policy_service_pb2.CreateUsePolicyRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        if not materialized.HasField("use_policy") or not materialized.use_policy_id.strip():
            raise ValueError("policy create requires a generated policy and policy ID")
        parent = _project(self._invoker)
        if materialized.parent not in ("", parent):
            raise ValueError("policy parent must match the configured project")
        materialized.parent = parent
        materialized, call = _prepare_mutation(self._invoker, materialized, options)
        return _operation(
            await self._invoker.unary(CREATE_USE_POLICY, materialized, call=call, retry_safe=True),
            "policy create",
        )

    async def update(
        self,
        request: policy_service_pb2.UpdateUsePolicyRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if (
            not request.HasField("use_policy")
            or not request.HasField("update_mask")
            or not request.etag.strip()
        ):
            raise ValueError("policy update requires a policy, field mask, and etag")
        _policy_name(self._invoker, request.use_policy.name)
        materialized, call = _prepare_mutation(self._invoker, request, options)
        return _operation(
            await self._invoker.unary(UPDATE_USE_POLICY, materialized, call=call, retry_safe=True),
            "policy update",
        )

    async def get(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> use_policy_pb2.UsePolicy:
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            policy_service_pb2.GetUsePolicyResponse,
            await self._invoker.unary(
                GET_USE_POLICY,
                policy_service_pb2.GetUsePolicyRequest(
                    name=_policy_name(self._invoker, name), if_none_match=if_none_match.strip()
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "use_policy", use_policy_pb2.UsePolicy, label="policy get"
        )

    async def list(
        self,
        request: policy_service_pb2.ListUsePoliciesRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> policy_service_pb2.ListUsePoliciesResponse:
        materialized = policy_service_pb2.ListUsePoliciesRequest()
        if request is not None:
            materialized.CopyFrom(request)
        parent = _project(self._invoker)
        if materialized.parent not in ("", parent):
            raise ValueError("policy list parent must match the configured project")
        materialized.parent = parent
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("policy page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            policy_service_pb2.ListUsePoliciesResponse,
            await self._invoker.unary(LIST_USE_POLICIES, materialized, call=call, retry_safe=True),
        )

    async def activate(
        self, name: str, etag: str, *, options: CallOptions | None = None
    ) -> operation_pb2.Operation:
        request, call = _prepare_mutation(
            self._invoker,
            policy_service_pb2.ActivateUsePolicyRequest(
                name=_policy_name(self._invoker, name), etag=required_text("etag", etag)
            ),
            options,
        )
        return _operation(
            await self._invoker.unary(ACTIVATE_USE_POLICY, request, call=call, retry_safe=True),
            "policy activation",
        )

    async def revoke(
        self, name: str, etag: str, reason_code: str, *, options: CallOptions | None = None
    ) -> operation_pb2.Operation:
        request, call = _prepare_mutation(
            self._invoker,
            policy_service_pb2.RevokeUsePolicyRequest(
                name=_policy_name(self._invoker, name),
                etag=required_text("etag", etag),
                reason_code=required_text("reason_code", reason_code),
            ),
            options,
        )
        return _operation(
            await self._invoker.unary(REVOKE_USE_POLICY, request, call=call, retry_safe=True),
            "policy revocation",
        )

    async def resolve_snapshot(
        self, name: str, effective_time: Timestamp, *, options: CallOptions | None = None
    ) -> policy_reference_pb2.PolicyReference:
        effective_time.ToDatetime()
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            policy_service_pb2.ResolvePolicySnapshotResponse,
            await self._invoker.unary(
                RESOLVE_POLICY_SNAPSHOT,
                policy_service_pb2.ResolvePolicySnapshotRequest(
                    name=_policy_name(self._invoker, name), effective_time=effective_time
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "policy_snapshot",
            policy_reference_pb2.PolicyReference,
            label="policy snapshot resolution",
        )
