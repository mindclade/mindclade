"""Admit and observe one bounded analysis-agent run through the private SDK.

Despite its historical ``simulate.py`` blueprint name, this module does not
simulate protocol state.  It is a small client application for an already
registered, policy-reviewed agent definition.  It cannot expand tools or
budgets and provides only start, status, and cancel actions.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from mindclade_internal_sdk import (
    CallOptions,
    Client,
    ClientConfig,
    Environment,
    GoogleWorkloadIdentityProvider,
)
from mindclade_internal_sdk.resources import (
    AgentDefinition,
    AgentRun,
    ApprovalRequest,
    Operation,
    agent_definition_is_active,
    approval_is_current_and_approved,
    cancel_agent_run_request,
    start_agent_run_request,
)

_DIGEST_PREFIX = "sha256:"
_ACTIONS = frozenset({"start", "status", "cancel"})


@dataclass(frozen=True, slots=True)
class AgentLimits:
    maximum_model_tokens: int
    maximum_iterations: int
    maximum_tool_calls: int
    maximum_concurrent_branches: int
    maximum_storage_bytes: int
    maximum_external_spend_micros: int
    maximum_wall_seconds: int
    maximum_depth: int
    maximum_fan_out: int
    maximum_observations_per_step: int
    maximum_artifact_references_per_call: int


@dataclass(frozen=True, slots=True)
class BoundedAgentConfiguration:
    definition_name: str
    definition_document_digest: str
    budget_reservation_name: str
    approval_request_name: str
    approval_binding_digest: str
    workflow_run_name: str
    allowed_tools: frozenset[str]
    limits: AgentLimits
    maximum_status_reads: int
    minimum_independent_approvers: int


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _read_object(path: Path, label: str) -> Mapping[str, object]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load {label}: {error}") from error
    return _object(value, label)


def _closed(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise ValueError(
            f"{label} fields differ: missing={sorted(expected - actual)!r}, "
            f"unknown={sorted(actual - expected)!r}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty trimmed text")
    if len(value) > 2048 or any(character in value for character in "\r\n\x00"):
        raise ValueError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    digest = _text(value, label)
    if len(digest) != 71 or not digest.startswith(_DIGEST_PREFIX):
        raise ValueError(f"{label} must be a canonical SHA-256 digest")
    try:
        bytes.fromhex(digest.removeprefix(_DIGEST_PREFIX))
    except ValueError as error:
        raise ValueError(f"{label} must be a canonical SHA-256 digest") from error
    if digest.lower() != digest:
        raise ValueError(f"{label} must be lowercase")
    return digest


def _positive(value: object, label: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    minimum = 0 if allow_zero else 1
    if not minimum <= value <= 2**63 - 1:
        raise ValueError(f"{label} is outside its bounded range")
    return value


def _string_set(value: object, label: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    raw_items = cast(list[object], value)
    items = frozenset(_text(item, label) for item in raw_items)
    if not items or len(items) != len(raw_items):
        raise ValueError(f"{label} must be non-empty and unique")
    return items


def load_configuration(agent_path: Path, workflow_path: Path) -> BoundedAgentConfiguration:
    """Load the closed JSON-compatible YAML configuration and fail closed."""

    agent = _read_object(agent_path, "agent configuration")
    workflow = _read_object(workflow_path, "workflow configuration")
    _closed(
        agent,
        frozenset(
            {
                "schema_version",
                "definition_name",
                "definition_document_digest",
                "budget_reservation_name",
                "approval_request_name",
                "approval_binding_digest",
                "allowed_tools",
                "limits",
                "safety",
            }
        ),
        "agent configuration",
    )
    _closed(
        workflow,
        frozenset(
            {
                "schema_version",
                "workflow_run_name",
                "allowed_actions",
                "maximum_status_reads",
                "approval_required",
                "minimum_independent_approvers",
            }
        ),
        "workflow configuration",
    )
    if agent["schema_version"] != "mindclade.example-bounded-agent/v1":
        raise ValueError("unsupported agent configuration version")
    if workflow["schema_version"] != "mindclade.example-bounded-agent-workflow/v1":
        raise ValueError("unsupported workflow configuration version")
    if _string_set(workflow["allowed_actions"], "allowed actions") != _ACTIONS:
        raise ValueError("the bounded workflow exposes only start, status, and cancel")
    if workflow["approval_required"] is not True:
        raise ValueError("bounded agent admission requires approval")

    safety = _object(agent["safety"], "agent safety")
    _closed(
        safety,
        frozenset({"network_access", "wet_lab_actions", "synthesis_instructions", "clinical_use"}),
        "agent safety",
    )
    if any(value is not False for value in safety.values()):
        raise ValueError("all prohibited agent capabilities must remain disabled")

    limits_value = _object(agent["limits"], "agent limits")
    limit_names = frozenset(AgentLimits.__dataclass_fields__)
    _closed(limits_value, limit_names, "agent limits")
    limits = AgentLimits(
        maximum_model_tokens=_positive(
            limits_value["maximum_model_tokens"], "maximum model tokens"
        ),
        maximum_iterations=_positive(limits_value["maximum_iterations"], "maximum iterations"),
        maximum_tool_calls=_positive(limits_value["maximum_tool_calls"], "maximum tool calls"),
        maximum_concurrent_branches=_positive(
            limits_value["maximum_concurrent_branches"], "maximum concurrent branches"
        ),
        maximum_storage_bytes=_positive(
            limits_value["maximum_storage_bytes"], "maximum storage bytes"
        ),
        maximum_external_spend_micros=_positive(
            limits_value["maximum_external_spend_micros"],
            "maximum external spend",
            allow_zero=True,
        ),
        maximum_wall_seconds=_positive(limits_value["maximum_wall_seconds"], "maximum wall time"),
        maximum_depth=_positive(limits_value["maximum_depth"], "maximum depth"),
        maximum_fan_out=_positive(limits_value["maximum_fan_out"], "maximum fan out"),
        maximum_observations_per_step=_positive(
            limits_value["maximum_observations_per_step"],
            "maximum observations per step",
        ),
        maximum_artifact_references_per_call=_positive(
            limits_value["maximum_artifact_references_per_call"],
            "maximum artifact references per call",
        ),
    )
    return BoundedAgentConfiguration(
        definition_name=_text(agent["definition_name"], "definition name"),
        definition_document_digest=_digest(
            agent["definition_document_digest"], "definition document digest"
        ),
        budget_reservation_name=_text(agent["budget_reservation_name"], "budget reservation name"),
        approval_request_name=_text(agent["approval_request_name"], "approval request name"),
        approval_binding_digest=_digest(
            agent["approval_binding_digest"], "approval binding digest"
        ),
        workflow_run_name=_text(workflow["workflow_run_name"], "workflow run name"),
        allowed_tools=_string_set(agent["allowed_tools"], "allowed tools"),
        limits=limits,
        maximum_status_reads=_positive(workflow["maximum_status_reads"], "maximum status reads"),
        minimum_independent_approvers=_positive(
            workflow["minimum_independent_approvers"],
            "minimum independent approvers",
        ),
    )


def _duration_seconds(value: object) -> float:
    seconds = cast(object, getattr(value, "seconds", None))
    nanos = cast(object, getattr(value, "nanos", None))
    if not isinstance(seconds, int) or not isinstance(nanos, int):
        return 0.0
    return float(seconds) + float(nanos) / 1_000_000_000


class BoundedAgentWorkflow:
    """Closed action set over an existing reviewed agent definition."""

    def __init__(self, client: Client, configuration: BoundedAgentConfiguration) -> None:
        self._client = client
        self._configuration = configuration
        self._status_reads = 0
        self._lock = threading.Lock()

    def _validate_definition(self, definition: AgentDefinition) -> None:
        expected = self._configuration
        if definition.name != expected.definition_name or not agent_definition_is_active(
            definition
        ):
            raise ValueError("agent definition is not the expected active revision")
        if not hmac.compare_digest(
            definition.definition.digest, expected.definition_document_digest
        ):
            raise ValueError("agent definition document digest changed")
        if frozenset(tool.name for tool in definition.eligible_tools) != expected.allowed_tools:
            raise ValueError("agent definition tool allowlist changed")
        budget = definition.budget
        limits = definition.limits
        constraints = (
            (budget.maximum_model_tokens, expected.limits.maximum_model_tokens),
            (budget.maximum_iterations, expected.limits.maximum_iterations),
            (budget.maximum_tool_calls, expected.limits.maximum_tool_calls),
            (
                budget.maximum_concurrent_branches,
                expected.limits.maximum_concurrent_branches,
            ),
            (budget.maximum_storage_bytes, expected.limits.maximum_storage_bytes),
            (limits.maximum_depth, expected.limits.maximum_depth),
            (limits.maximum_fan_out, expected.limits.maximum_fan_out),
            (
                limits.maximum_observations_per_step,
                expected.limits.maximum_observations_per_step,
            ),
            (
                limits.maximum_artifact_references_per_call,
                expected.limits.maximum_artifact_references_per_call,
            ),
        )
        if any(actual <= 0 or actual > maximum for actual, maximum in constraints):
            raise ValueError("agent definition exceeds or omits a configured budget")
        if budget.maximum_external_spend_micros > expected.limits.maximum_external_spend_micros:
            raise ValueError("agent definition external-spend budget exceeds the configured limit")
        wall_seconds = _duration_seconds(budget.maximum_wall_time)
        if not 0 < wall_seconds <= expected.limits.maximum_wall_seconds:
            raise ValueError("agent definition wall-time budget is invalid")

    def _validate_approval(self, approval: ApprovalRequest) -> None:
        expected = self._configuration
        if not approval_is_current_and_approved(approval):
            raise ValueError("agent start approval is absent, expired, or not approved")
        if approval.minimum_independent_approvers < expected.minimum_independent_approvers:
            raise ValueError("agent start approval has insufficient independent review")
        if approval.binding.action != "agent.run.start" or not hmac.compare_digest(
            approval.binding.binding_digest, expected.approval_binding_digest
        ):
            raise ValueError("agent start approval does not bind the configured intent")

    def start(self, agent_run_id: str, *, idempotency_key: str) -> Operation:
        """Start a run only after exact definition and approval preflight."""

        definition = self._client.agents.get_definition(self._configuration.definition_name)
        approval = self._client.approvals.get(self._configuration.approval_request_name)
        self._validate_definition(definition)
        self._validate_approval(approval)
        request = start_agent_run_request(
            agent_run_id=agent_run_id,
            definition_name=self._configuration.definition_name,
            budget_reservation_name=self._configuration.budget_reservation_name,
            workflow_run_name=self._configuration.workflow_run_name,
        )
        return self._client.agents.start_run(
            request,
            options=CallOptions(idempotency_key=idempotency_key),
        )

    def status(self, run_name: str) -> AgentRun:
        """Read bounded durable status without starting a model/tool loop."""

        with self._lock:
            if self._status_reads >= self._configuration.maximum_status_reads:
                raise RuntimeError("agent status-read budget exhausted")
            self._status_reads += 1
        return self._client.agents.get_run(run_name)

    def cancel(
        self,
        run_name: str,
        *,
        etag: str,
        reason: str,
        idempotency_key: str,
    ) -> Operation:
        """Request monotonic cancellation under an ETag and idempotency key."""

        return self._client.agents.cancel_run(
            cancel_agent_run_request(name=run_name, etag=etag, reason=reason),
            options=CallOptions(idempotency_key=idempotency_key),
        )


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _client_from_environment() -> Client:
    environment = Environment(os.environ.get("MINDCLADE_ENVIRONMENT", "development"))
    endpoint = os.environ.get("MINDCLADE_ENDPOINT") or None
    tenant_id = _required_environment("MINDCLADE_TENANT_ID")
    project_id = _required_environment("MINDCLADE_PROJECT_ID")
    principal_id = _required_environment("MINDCLADE_PRINCIPAL_ID")
    if environment is Environment.LOCAL:
        config = ClientConfig(
            tenant_id=tenant_id,
            project_id=project_id,
            principal_id=principal_id,
            environment=environment,
            endpoint=endpoint or "127.0.0.1:9443",
            insecure_for_testing=True,
        )
    else:
        config = ClientConfig(
            tenant_id=tenant_id,
            project_id=project_id,
            principal_id=principal_id,
            environment=environment,
            endpoint=endpoint,
            token_provider=GoogleWorkloadIdentityProvider(
                _required_environment("MINDCLADE_AUDIENCE")
            ),
        )
    return Client(config)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    directory = Path(__file__).resolve().parent
    parser.add_argument("--agent-config", type=Path, default=directory / "agent.yaml")
    parser.add_argument("--workflow-config", type=Path, default=directory / "workflow.yaml")
    subparsers = parser.add_subparsers(dest="action", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--run-id", required=True)
    start.add_argument("--idempotency-key", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--run-name", required=True)
    cancel = subparsers.add_parser("cancel")
    cancel.add_argument("--run-name", required=True)
    cancel.add_argument("--etag", required=True)
    cancel.add_argument("--reason", required=True)
    cancel.add_argument("--idempotency-key", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configuration = load_configuration(args.agent_config, args.workflow_config)
    with _client_from_environment() as client:
        workflow = BoundedAgentWorkflow(client, configuration)
        if args.action == "start":
            operation = workflow.start(args.run_id, idempotency_key=args.idempotency_key)
            output: Mapping[str, object] = {"operation_id": operation.operation_id}
        elif args.action == "status":
            run = workflow.status(args.run_name)
            output = {"name": run.name, "revision": run.revision, "state": run.state}
        else:
            operation = workflow.cancel(
                args.run_name,
                etag=args.etag,
                reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
            output = {"operation_id": operation.operation_id}
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
