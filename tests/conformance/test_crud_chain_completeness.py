#!/usr/bin/env python3.12
"""Hold every create/read/update/delete chain in the descriptor to closure.

A client that has just created a resource holds exactly one thing: the create
response. If reading, updating, or deleting that resource then demands an
identifier the create response never carried, the chain is broken -- and it
breaks in the place hardest to see from inside the contract, because each
method reads perfectly well on its own. The caller discovers it, in every
language at once, when the obvious two-line sequence cannot be written.

Nothing in the estate checked this. The retry-safety gate binds each method's
replay classification to the descriptor, and the RPC-coverage projection binds
each method's existence to it, but no gate asked whether the methods compose.

This test does. For every resource with a `Create`, it takes each sibling
`Get`, `Update`, and `Delete`, collects the identity the caller must supply at
that method's own surface, and requires each one to be obtainable from the
create response -- or to be something the caller itself chose when it called
create, and therefore still holds.

What the descriptor can and cannot prove, stated plainly, because a gate that
overstates its evidence is worse than none:

- Proto3 has no `required`, and this repository expresses requiredness in
  server-side validation rather than in a field option, so requiredness here is
  read off an identity vocabulary -- `name`, `parent`, `etag`, `uid`, and
  `*_id` -- at the caller's own surface. That surface is the request message,
  unwrapped once through a lone `command` field where the service uses that
  idiom, plus `name` one level into a singular embedded resource message. The
  resource identifier is genuinely required; the `uid`, `tenant_id`, and
  `schema_id` sitting beside it inside a resource body are server-assigned
  echoes a caller may leave empty, and treating them as obligations reports
  failures that are not real. `UpdateDataset` is the worked example: its
  repository validation reads `dataset.name` and `etag` and never looks at
  `dataset.uid`.
- Discharge is matched on leaf field name, not on path. A create response that
  offered `name` somewhere unrelated would satisfy an obligation for `name`,
  and the descriptor cannot distinguish the two. Two exclusions keep that from
  becoming vacuous: `CommandContext` is the caller's own input rather than
  anything the server returned, and `ErrorDetail` is the failure branch -- a
  caller cannot chain a successful call off the identity in an error. Without
  the second, `operation.error.subject.name` alone would discharge every read
  chain in the estate, and `test_a_failure_branch_cannot_discharge_an_obligation`
  is the proof that it does not.
"""

from __future__ import annotations

import base64
import hashlib
import json
import unittest
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from google.protobuf import descriptor_pb2

REPOSITORY = Path(__file__).resolve().parents[2]
CANDIDATE = REPOSITORY / "protocols/compatibility/baselines/protobuf.candidate.json"
GENERATED_FILES = REPOSITORY / "protocols/generated/generated-files.manifest.json"

TYPE_MESSAGE = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
LABEL_REPEATED = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

COMMAND_CONTEXT = "mindclade.common.v1.CommandContext"
ERROR_DETAIL = "mindclade.common.v1.ErrorDetail"

IDENTITY_FIELDS = frozenset({"name", "parent", "etag", "uid"})
RESOURCE_IDENTIFIER = "name"

CREATE = "Create"
CHAINED_VERBS = ("Get", "Update", "Delete")

# The estate this gate covers, pinned so a service that stops declaring a read
# cannot quietly shrink what is checked.
EXPECTED_RESOURCES = 12
EXPECTED_CHAINS = 18


def identity_field(name: str) -> bool:
    return name in IDENTITY_FIELDS or name.endswith("_id")


class Descriptor:
    """The committed candidate descriptor, indexed by message full name."""

    def __init__(self, file_set: descriptor_pb2.FileDescriptorSet) -> None:
        self.messages: dict[str, descriptor_pb2.DescriptorProto] = {}
        for file in file_set.file:
            self._index(file.package, file.message_type)
        self.file_set = file_set

    def _index(self, prefix: str, messages: Iterable[descriptor_pb2.DescriptorProto]) -> None:
        for message in messages:
            full_name = f"{prefix}.{message.name}"
            self.messages[full_name] = message
            self._index(full_name, message.nested_type)

    def surface(self, type_name: str) -> list[descriptor_pb2.FieldDescriptorProto]:
        """The fields the caller fills, unwrapping a lone `command` message once."""

        message = self.messages.get(type_name)
        if message is None:
            return []
        fields = list(message.field)
        if len(fields) == 1 and fields[0].type == TYPE_MESSAGE:
            inner = self.messages.get(fields[0].type_name.lstrip("."))
            if inner is not None:
                return list(inner.field)
        return fields

    def obligations(self, request_type: str) -> set[str]:
        """The identity the caller must supply to invoke this method."""

        fields = self.surface(request_type)
        required = self.caller_supplied(request_type)
        for field in fields:
            if field.type != TYPE_MESSAGE or field.label == LABEL_REPEATED:
                continue
            nested_name = field.type_name.lstrip(".")
            if nested_name == COMMAND_CONTEXT:
                continue
            nested = self.messages.get(nested_name)
            if nested is None:
                continue
            if any(
                inner.type != TYPE_MESSAGE and inner.name == RESOURCE_IDENTIFIER
                for inner in nested.field
            ):
                required.add(RESOURCE_IDENTIFIER)
        return required

    def caller_supplied(self, request_type: str) -> set[str]:
        """The identity the caller typed itself, and therefore still holds.

        Scalars only. A create that embeds the resource message does not hand
        the caller its `name` -- the server derives that from `parent` and the
        client-chosen id -- so descending for `name` here would let a create
        discharge an obligation it never satisfied.
        """

        return {
            field.name
            for field in self.surface(request_type)
            if field.type != TYPE_MESSAGE and identity_field(field.name)
        }

    def success_closure(self, type_name: str, depth: int = 6) -> set[str]:
        """Every leaf name a caller can read out of a successful response."""

        reachable: set[str] = set()

        def walk(current: str, seen: frozenset[str], remaining: int) -> None:
            if remaining < 0:
                return
            message = self.messages.get(current)
            if message is None:
                return
            for field in message.field:
                if field.type != TYPE_MESSAGE:
                    reachable.add(field.name)
                    continue
                nested = field.type_name.lstrip(".")
                if nested in {COMMAND_CONTEXT, ERROR_DETAIL} or nested in seen:
                    continue
                walk(nested, seen | {nested}, remaining - 1)

        walk(type_name, frozenset({type_name}), depth)
        return reachable

    def chains(self) -> dict[tuple[str, str], dict[str, descriptor_pb2.MethodDescriptorProto]]:
        """Methods grouped by service and resource, keyed by CRUD verb."""

        grouped: dict[tuple[str, str], dict[str, descriptor_pb2.MethodDescriptorProto]] = (
            defaultdict(dict)
        )
        for file in self.file_set.file:
            for service in file.service:
                service_name = f"{file.package}.{service.name}"
                for method in service.method:
                    for verb in (CREATE, *CHAINED_VERBS):
                        if method.name.startswith(verb) and len(method.name) > len(verb):
                            grouped[(service_name, method.name[len(verb) :])][verb] = method
                            break
        return {key: verbs for key, verbs in grouped.items() if CREATE in verbs}

    def undischarged(
        self,
        create: descriptor_pb2.MethodDescriptorProto,
        method: descriptor_pb2.MethodDescriptorProto,
    ) -> set[str]:
        """Identity the sibling method demands that create never hands back."""

        discharged = self.success_closure(create.output_type.lstrip(".")) | self.caller_supplied(
            create.input_type.lstrip(".")
        )
        return self.obligations(method.input_type.lstrip(".")) - discharged


def load_descriptor_bytes() -> bytes:
    document: dict[str, Any] = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    return base64.b64decode(document["descriptor_set"]["base64"])


def parse(raw: bytes) -> Descriptor:
    file_set = descriptor_pb2.FileDescriptorSet()
    file_set.ParseFromString(raw)
    return Descriptor(file_set)


class CrudChainCompletenessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = load_descriptor_bytes()
        cls.descriptor = parse(cls.raw)
        cls.chains = cls.descriptor.chains()

    def test_the_checked_descriptor_is_the_governed_candidate(self) -> None:
        """Bind this gate to the same descriptor the contract transaction produced."""

        digest = "sha256:" + hashlib.sha256(self.raw).hexdigest()
        candidate: dict[str, Any] = json.loads(CANDIDATE.read_text(encoding="utf-8"))
        generated: dict[str, Any] = json.loads(GENERATED_FILES.read_text(encoding="utf-8"))
        self.assertEqual(candidate["descriptor_set"]["digest"], digest)
        self.assertEqual(generated["descriptor_digest"], digest)

    def test_the_covered_estate_is_the_expected_size(self) -> None:
        chained = [
            (key, verb)
            for key, verbs in self.chains.items()
            for verb in CHAINED_VERBS
            if verb in verbs
        ]
        self.assertEqual(len(self.chains), EXPECTED_RESOURCES)
        self.assertEqual(len(chained), EXPECTED_CHAINS)

    def test_every_chain_from_create_is_closed(self) -> None:
        for (service, resource), verbs in sorted(self.chains.items()):
            for verb in CHAINED_VERBS:
                method = verbs.get(verb)
                if method is None:
                    continue
                with self.subTest(service=service, resource=resource, verb=verb):
                    missing = self.descriptor.undischarged(verbs[CREATE], method)
                    self.assertEqual(
                        missing,
                        set(),
                        f"{service}.{method.name} requires {sorted(missing)}, which "
                        f"Create{resource} neither returns nor was given",
                    )

    def test_every_read_requires_the_resource_identifier(self) -> None:
        """A read that asks for no identity at all would pass vacuously."""

        for (service, resource), verbs in sorted(self.chains.items()):
            method = verbs.get("Get")
            if method is None:
                continue
            with self.subTest(service=service, resource=resource):
                obligations = self.descriptor.obligations(method.input_type.lstrip("."))
                self.assertIn(RESOURCE_IDENTIFIER, obligations)

    def test_an_unreachable_obligation_is_detected(self) -> None:
        """The gate must fail when a chain is genuinely broken."""

        broken = parse(self.raw)
        request = broken.messages["mindclade.internal.admin.v1.GetProjectRequest"]
        added = request.field.add()
        added.name = "workspace_id"
        added.number = 900
        added.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
        added.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

        verbs = broken.chains()[("mindclade.internal.admin.v1.AdminService", "Project")]
        self.assertEqual(
            broken.undischarged(verbs[CREATE], verbs["Get"]),
            {"workspace_id"},
        )

    def test_a_failure_branch_cannot_discharge_an_obligation(self) -> None:
        """Identity reachable only through ErrorDetail must not close a chain.

        Removing `Operation.target` leaves `operation.error.subject.name` as the
        only `name` in the create response. Every operation-returning read chain
        must break, which is what proves the ErrorDetail exclusion is carrying
        weight rather than decorating the walk.
        """

        stripped = parse(self.raw)
        operation = stripped.messages["mindclade.job.v1.Operation"]
        retained = [field for field in operation.field if field.name != "target"]
        self.assertEqual(len(retained), len(operation.field) - 1)
        del operation.field[:]
        operation.field.extend(retained)

        broken = {
            f"{service}.{verbs['Get'].name}"
            for (service, _resource), verbs in stripped.chains().items()
            if "Get" in verbs and stripped.undischarged(verbs[CREATE], verbs["Get"])
        }
        self.assertIn("mindclade.internal.admin.v1.AdminService.GetProject", broken)
        self.assertGreaterEqual(len(broken), 8)


if __name__ == "__main__":
    unittest.main()
