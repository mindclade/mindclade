from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from kernels.native.python.capability_index import (
    BundleBinding,
    CapabilityIndexError,
    CapabilityRequest,
    canonical_json,
    load_native_capability_table,
    load_native_capability_table_identity,
    load_signed_capability_index,
    reconcile_exported_native_capability_identity,
    reconcile_signed_native_capability_table,
    select_capability,
    subject_digest,
)
from kernels.native.python.qualification import (
    K4QualificationReceipt,
    K5ReleaseReceipt,
    RollbackReceipt,
    RevocationReceipt,
    TEST_ONLY_EVIDENCE,
    build_signed_capability_index,
    capability_identity,
    sign_receipt,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))


def _k4(*, artifact: str = "a") -> K4QualificationReceipt:
    return K4QualificationReceipt(
        operation="mindclade::triangle_attention",
        architecture="sm90a",
        workload_digest=_digest("1"),
        specialization_digest=_digest("2"),
        dimensions=(("head_dim", 32), ("residues", 64)),
        attributes=(
            ("causal", "bool", False),
            ("scale", "float64", 0.125),
            ("variant", "string", "starting"),
        ),
        hardware_fingerprint_digest=_digest("3"),
        compile_environment_digest=_digest("4"),
        runtime_compatibility_digest=_digest("5"),
        numerical_receipt_digest=_digest("6"),
        performance_receipt_digest=_digest("7"),
        benchmark_protocol_digest=_digest("8"),
        raw_samples_digest=_digest("9"),
        forward_artifact_digest=_digest(artifact),
        backward_artifact_digest=_digest("b"),
        native_manifest_schema_version=4,
        native_manifest_generator_version=8,
        build_receipt_schema_version=4,
        autograd_policy="required",
        status="TEST_ONLY",
        evidence_class=TEST_ONLY_EVIDENCE,
    )


def _k5(k4_digest: str, *, artifact: str = "a", bundle: str = "c") -> K5ReleaseReceipt:
    return K5ReleaseReceipt(
        release_id=f"test-only.release-{bundle}",
        operation="mindclade::triangle_attention",
        operation_version=1,
        implementation="triangle_attention_tiled",
        implementation_version=1,
        tier="specialized",
        priority=10,
        architecture="sm90a",
        dtype="bfloat16",
        layout="contiguous",
        mode="starting_node",
        workload_digest=_digest("1"),
        specialization_digest=_digest("2"),
        dimensions=(("head_dim", 32), ("residues", 64)),
        attributes=(
            ("causal", "bool", False),
            ("scale", "float64", 0.125),
            ("variant", "string", "starting"),
        ),
        schedule_digest=_digest("d"),
        numerical_envelope_digest=_digest("e"),
        k0_receipt_digest=_digest("0"),
        k1_receipt_digest=_digest("1"),
        k2_receipt_digest=_digest("2"),
        k3_receipt_digest=_digest("3"),
        k4_receipt_digest=k4_digest,
        bundle_digest=_digest(bundle),
        native_manifest_digest=_digest("f"),
        library_digest=_digest(artifact),
        executable_plan_digest=_digest("d"),
        forward_artifact_digest=_digest(artifact),
        backward_artifact_digest=_digest("b"),
        runtime_compatibility_digest=_digest("5"),
        compile_environment_digest=_digest("4"),
        sbom_digest=_digest("6"),
        provenance_digest=_digest("7"),
        qualification_identity="test-only.qualification",
        repository_revision="a" * 40,
        native_manifest_schema_version=4,
        native_manifest_generator_version=8,
        build_receipt_schema_version=4,
        autograd_policy="required",
        status="TEST_ONLY",
        evidence_class=TEST_ONLY_EVIDENCE,
    )


def _signed_release(*, artifact: str = "a", bundle: str = "c"):
    key = _private_key()
    k4 = sign_receipt(_k4(artifact=artifact), private_key=key, key_id="test-only.qualifier")
    k5 = sign_receipt(
        _k5(k4.receipt_digest, artifact=artifact, bundle=bundle),
        private_key=key,
        key_id="test-only.qualifier",
    )
    return key, k4, k5


def _index_document(*, releases, k4_receipts, revocations=(), rollbacks=()):
    key = _private_key()
    return build_signed_capability_index(
        releases=tuple(releases),
        k4_receipts=k4_receipts,
        revocations=tuple(revocations),
        rollbacks=tuple(rollbacks),
        trust_roots={"test-only.qualifier": key.public_key()},
        evidence_class=TEST_ONLY_EVIDENCE,
        index_private_key=key,
        index_key_id="test-only.index",
    )


def _request() -> CapabilityRequest:
    return CapabilityRequest(
        operation="mindclade::triangle_attention",
        architecture="sm90a",
        dtype="bfloat16",
        layout="contiguous",
        mode="starting_node",
        workload_digest=_digest("1"),
        training=True,
    )


def test_signed_workload_bindings_are_canonical_and_strictly_typed():
    with pytest.raises(ValueError, match="canonical order"):
        replace(_k4(), dimensions=(("residues", 64), ("head_dim", 32)))
    with pytest.raises(ValueError, match="scalar type"):
        replace(_k4(), attributes=(("causal", "int64", False),))
    with pytest.raises(ValueError, match="disjoint"):
        replace(_k4(), attributes=(("residues", "int64", 64),))
    with pytest.raises(ValueError, match="non-REQUIRED"):
        replace(_k4(), autograd_policy="composite")


def _binding(*, library: str = "a") -> BundleBinding:
    return BundleBinding(
        repository_revision="a" * 40,
        library_digest=_digest(library),
        native_manifest_digest=_digest("f"),
        executable_plan_digest=_digest("d"),
        qualification_identity="test-only.qualification",
    )


def test_signed_test_index_is_never_production_eligible():
    key, k4, k5 = _signed_release()
    document = _index_document(
        releases=(k5,), k4_receipts={k4.receipt_digest: k4}
    )
    index = load_signed_capability_index(
        document,
        trust_roots={"test-only.index": key.public_key()},
        expected_key_id="test-only.index",
        allow_test_evidence=True,
    )
    assert index.production_eligible is False
    with pytest.raises(CapabilityIndexError, match="K4/K5"):
        select_capability(index, _request(), _binding())
    receipt = select_capability(
        index, _request(), _binding(), require_production=False
    )
    assert receipt.fallback is False
    assert receipt.selection_reason.startswith("exact qualified envelope")


def test_index_signature_and_subject_digest_fail_closed():
    key, k4, k5 = _signed_release()
    document = json.loads(
        _index_document(
            releases=(k5,), k4_receipts={k4.receipt_digest: k4}
        )
    )
    document["index"]["capabilities"][0]["priority"] += 1
    with pytest.raises(CapabilityIndexError, match="digest mismatch"):
        load_signed_capability_index(
            json.dumps(document).encode(),
            trust_roots={"test-only.index": key.public_key()},
            expected_key_id="test-only.index",
            allow_test_evidence=True,
        )


def test_exact_envelope_and_bundle_binding_reject_near_matches():
    key, k4, k5 = _signed_release()
    index = load_signed_capability_index(
        _index_document(
            releases=(k5,), k4_receipts={k4.receipt_digest: k4}
        ),
        trust_roots={"test-only.index": key.public_key()},
        expected_key_id="test-only.index",
        allow_test_evidence=True,
    )
    with pytest.raises(CapabilityIndexError, match="no exact"):
        select_capability(
            index,
            replace(_request(), architecture="sm100a"),
            _binding(),
            require_production=False,
        )
    with pytest.raises(CapabilityIndexError, match="no exact"):
        select_capability(
            index,
            _request(),
            replace(_binding(), native_manifest_digest=_digest("0")),
            require_production=False,
        )


def test_signed_revocation_and_rollback_select_prior_qualified_record():
    key, old_k4, old_k5 = _signed_release(artifact="a", bundle="c")
    _, new_k4, new_k5 = _signed_release(artifact="8", bundle="9")
    old_identity = capability_identity(old_k5)
    new_identity = capability_identity(new_k5)
    revocation = sign_receipt(
        RevocationReceipt(
            capability_digest=new_identity,
            release_receipt_digest=new_k5.receipt_digest,
            reason_code="numerical-regression",
            revocation_policy_identity="test-only.revocation",
            sequence=1,
            evidence_class=TEST_ONLY_EVIDENCE,
        ),
        private_key=key,
        key_id="test-only.qualifier",
    )
    rollback = sign_receipt(
        RollbackReceipt(
            revoked_capability_digest=new_identity,
            replacement_capability_digest=old_identity,
            replacement_release_receipt_digest=old_k5.receipt_digest,
            reason_code="restore-prior-qualified",
            sequence=2,
            evidence_class=TEST_ONLY_EVIDENCE,
        ),
        private_key=key,
        key_id="test-only.qualifier",
    )
    index = load_signed_capability_index(
        _index_document(
            releases=(old_k5, new_k5),
            k4_receipts={
                old_k4.receipt_digest: old_k4,
                new_k4.receipt_digest: new_k4,
            },
            revocations=(revocation,),
            rollbacks=(rollback,),
        ),
        trust_roots={"test-only.index": key.public_key()},
        expected_key_id="test-only.index",
        allow_test_evidence=True,
    )
    assert new_identity in index.revoked_capability_digests
    receipt = select_capability(
        index, _request(), _binding(library="a"), require_production=False
    )
    assert receipt.capability_digest == old_identity
    assert receipt.rollback_receipt_digest == rollback.receipt_digest
    assert "rollback" in receipt.selection_reason


def test_receipts_and_signed_index_match_exact_checked_in_schemas():
    manifests = Path(__file__).resolve().parents[1] / "manifests"
    receipt_schema = json.loads(
        (manifests / "qualification_release.schema.json").read_text()
    )
    index_schema = json.loads(
        (manifests / "qualified_capability_index.schema.json").read_text()
    )
    Draft202012Validator.check_schema(receipt_schema)
    Draft202012Validator.check_schema(index_schema)
    key, k4, k5 = _signed_release()
    Draft202012Validator(receipt_schema).validate(k4.payload())
    Draft202012Validator(receipt_schema).validate(k5.payload())
    signed_document = json.loads(
        _index_document(
            releases=(k5,), k4_receipts={k4.receipt_digest: k4}
        )
    )
    Draft202012Validator(index_schema).validate(signed_document)

    source_empty = json.loads(
        (manifests / "qualified_capability_index.json").read_text()
    )
    Draft202012Validator(index_schema).validate(source_empty)
    assert source_empty["capabilities"] == []
    with pytest.raises(CapabilityIndexError):
        load_signed_capability_index(
            json.dumps(source_empty).encode(),
            trust_roots={"test-only.index": key.public_key()},
            expected_key_id="test-only.index",
            allow_test_evidence=True,
        )


def test_empty_native_table_parity_contract_is_exact_and_fail_closed():
    table_body = {
        "schema_version": 1,
        "generator": {
            "id": "kernels.native.codegen.generate",
            "version": 8,
        },
        "selection": "exact_qualified_only",
        "row_fields": [
            "operation",
            "phase",
            "workload_digest",
            "specialization_digest",
            "capability_digest",
            "artifact_digest",
            "architecture",
            "dtype",
            "layout",
            "mode",
            "dimensions",
            "attributes",
            "specificity",
            "priority",
            "adapter_symbols",
        ],
        "sort_order": [
            "operation",
            "phase",
            "-specificity",
            "-priority",
            "capability_digest",
        ],
        "rows": [],
        "row_count": 0,
        "rows_digest": subject_digest([]),
    }
    table = {**table_body, "table_digest": subject_digest(table_body)}
    identity = load_native_capability_table_identity(canonical_json(table))
    assert identity.row_count == 0
    assert identity.table_digest == table["table_digest"]
    generated = (
        Path(__file__).resolve().parents[1]
        / "generated"
        / "qualified_capabilities.generated.json"
    )
    assert load_native_capability_table_identity(generated.read_bytes()) == identity

    table["rows"] = [{}]
    table["row_count"] = 1
    table["rows_digest"] = subject_digest(table["rows"])
    body = dict(table)
    body.pop("table_digest")
    table["table_digest"] = subject_digest(body)
    with pytest.raises(CapabilityIndexError, match="missing or unknown"):
        load_native_capability_table_identity(canonical_json(table))


def test_nonempty_native_table_must_exactly_project_signed_k5_and_exports():
    key, k4, k5 = _signed_release()
    document = _index_document(
        releases=(k5,), k4_receipts={k4.receipt_digest: k4}
    )
    index = load_signed_capability_index(
        document,
        trust_roots={"test-only.index": key.public_key()},
        expected_key_id="test-only.index",
        allow_test_evidence=True,
    )
    capability = index.capabilities[0]
    adapters = {
        (capability.operation, "forward"): ("mindclade_triangle_attention_fwd",),
        (capability.operation, "backward"): ("mindclade_triangle_attention_bwd",),
    }
    common = {
        "operation": capability.operation,
        "workload_digest": capability.workload_digest,
        "specialization_digest": capability.specialization_digest,
        "capability_digest": capability.capability_digest,
        "architecture": capability.architecture,
        "dtype": capability.dtype,
        "layout": capability.layout,
        "mode": capability.mode,
        "dimensions": [
            {"name": name, "value": value}
            for name, value in capability.dimensions
        ],
        "attributes": [
            {"name": name, "type": scalar_type, "value": value}
            for name, scalar_type, value in capability.attributes
        ],
        "specificity": len(capability.dimensions) + len(capability.attributes),
        "priority": capability.priority,
    }
    rows = [
        {
            **common,
            "phase": "forward",
            "artifact_digest": capability.forward_artifact_digest,
            "adapter_symbols": list(adapters[(capability.operation, "forward")]),
        },
        {
            **common,
            "phase": "backward",
            "artifact_digest": capability.backward_artifact_digest,
            "adapter_symbols": list(adapters[(capability.operation, "backward")]),
        },
    ]
    body = {
        "schema_version": 1,
        "generator": {"id": "kernels.native.codegen.generate", "version": 8},
        "selection": "exact_qualified_only",
        "row_fields": [
            "operation", "phase", "workload_digest", "specialization_digest",
            "capability_digest", "artifact_digest", "architecture", "dtype",
            "layout", "mode", "dimensions", "attributes", "specificity",
            "priority", "adapter_symbols",
        ],
        "sort_order": [
            "operation", "phase", "-specificity", "-priority", "capability_digest",
        ],
        "rows": rows,
        "row_count": len(rows),
        "rows_digest": subject_digest(rows),
    }
    table = load_native_capability_table(
        canonical_json({**body, "table_digest": subject_digest(body)})
    )
    identity = reconcile_signed_native_capability_table(index, table, adapters)
    reconcile_exported_native_capability_identity(
        identity,
        row_count=identity.row_count,
        rows_digest=identity.rows_digest,
        table_digest=identity.table_digest,
    )
    with pytest.raises(CapabilityIndexError, match="does not match"):
        reconcile_exported_native_capability_identity(
            identity,
            row_count=identity.row_count,
            rows_digest=identity.rows_digest,
            table_digest=_digest("f"),
        )
    with pytest.raises(CapabilityIndexError, match="exactly project"):
        reconcile_signed_native_capability_table(
            index,
            replace(
                table,
                rows=(
                    replace(table.rows[0], artifact_digest=_digest("f")),
                    table.rows[1],
                ),
            ),
            adapters,
        )
    reconcile_exported_native_capability_identity,
    reconcile_signed_native_capability_table,
