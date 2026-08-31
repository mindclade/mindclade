from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "generated").is_dir():
            return candidate
    raise RuntimeError("cannot locate generated protocol bindings")


class GeneratedClientsContractTest(unittest.TestCase):
    def test_generated_bindings_are_current_and_compilable(self) -> None:
        repository = root()
        subprocess.run(
            [sys.executable, "tools/codegen/verify_generated_drift.py", "--root", "."],
            cwd=repository,
            check=True,
        )
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        generated_python = repository / "protocols/generated/python"
        modules = sorted(
            ".".join(path.relative_to(generated_python).with_suffix("").parts)
            for path in generated_python.glob("**/*_pb2.py")
        )
        self.assertTrue(modules)
        imported = {name: importlib.import_module(name) for name in modules}
        module = imported["common.v1.identifiers_pb2"]
        self.assertEqual(module.Identifiers(tenant_id="tenant").tenant_id, "tenant")
        if "TEST_SRCDIR" not in os.environ:
            subprocess.run(
                ["go", "test", "./protocols/generated/go/..."], cwd=repository, check=True
            )
            subprocess.run(
                ["cargo", "test", "--locked", "-p", "mindclade-protocols"],
                cwd=repository,
                check=True,
            )
        typescript = (
            repository / "protocols/generated/typescript/common/v1/identifiers_pb.ts"
        ).read_text()
        self.assertIn(
            'export type Identifiers = Message<"mindclade.common.v1.Identifiers"> & {',
            typescript,
        )
        self.assertIn(
            "export const IdentifiersSchema: GenMessage<Identifiers> = /*@__PURE__*/",
            typescript,
        )

    def test_python_foundations_consume_generated_contract_types(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        sys.path.insert(0, str(repository / "libs/python"))

        artifact_module = importlib.import_module("artifact.v1.artifact_reference_pb2")
        evidence_module = importlib.import_module("artifact.v1.evidence_reference_pb2")
        resource_module = importlib.import_module("common.v1.resource_reference_pb2")
        artifacts = importlib.import_module("artifacts")
        contracts = importlib.import_module("contracts")
        identifiers = importlib.import_module("identifiers")
        serialization = importlib.import_module("serialization")

        self.assertIs(artifacts.ArtifactRef, artifact_module.ArtifactRef)
        self.assertIs(artifacts.EvidenceRef, evidence_module.EvidenceRef)
        self.assertEqual(
            contracts.ErrorDetail.DESCRIPTOR.full_name,
            "mindclade.common.v1.ErrorDetail",
        )
        self.assertIs(identifiers.ResourceRef, resource_module.ResourceRef)

        digest = "sha256:" + "a" * 64
        subject_digest = "sha256:" + "b" * 64
        policy_digest = "sha256:" + "c" * 64
        artifact = artifacts.make_artifact_ref(
            digest=digest,
            media_type="application/octet-stream",
            size_bytes=7,
            artifact_kind="fixture",
        )
        evidence = artifacts.make_evidence_ref(
            digest=digest,
            subject_digest=subject_digest,
            evidence_kind="qualification",
            policy_digest=policy_digest,
        )
        resource = identifiers.make_resource_ref(
            tenant_id=identifiers.Identifier("tenant", "tenant_1"),
            project_id=identifiers.Identifier("project", "project_1"),
            resource_type="jobs",
            resource_id=identifiers.Identifier("job", "job_1"),
            resource_version=identifiers.ResourceVersion(2),
        )

        self.assertEqual(artifact.digest, digest)
        self.assertEqual(evidence.subject_digest, subject_digest)
        error_detail = contracts.to_error_detail(
            contracts.ContractError(
                contracts.ErrorCode.UNAVAILABLE,
                "try again",
                retryable=True,
            ),
            subject=resource,
        )
        self.assertEqual(error_detail.subject.name, resource.name)
        self.assertTrue(contracts.from_error_detail(error_detail).retryable)
        self.assertEqual(
            identifiers.resource_key(resource),
            "tenants/tenant_1/projects/project_1/jobs/job_1@2",
        )
        self.assertEqual(
            resource.SerializeToString(deterministic=True),
            resource_module.ResourceRef.FromString(
                resource.SerializeToString(deterministic=True)
            ).SerializeToString(deterministic=True),
        )

        event_module = importlib.import_module("job.v1.job_requested_pb2")
        payload = event_module.JobRequested(
            job_id="job_1",
            configuration_digest="sha256:" + "d" * 64,
        )
        envelope = serialization.make_event_envelope(
            payload,
            event_id="event_1",
            event_version=1,
            tenant_id="tenant_1",
            project_id="project_1",
            producer="control-plane",
            occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
            subject=resource,
            job_id="job_1",
        )
        decoded = serialization.parse_event_payload(envelope, event_module.JobRequested)
        self.assertEqual(decoded, payload)
        envelope.payload_digest = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            serialization.parse_event_payload(envelope, event_module.JobRequested)


if __name__ == "__main__":
    unittest.main()
