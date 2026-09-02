"""Source-qualified, connected-blocked protected release pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [
        Step(
            key="release-signing-source-contract",
            label=":closed_lock_with_key: External signing source contract",
            command="bazel test //tests:release_signing_test",
            timeout_minutes=15,
            env={
                "MINDCLADE_REQUIRED_APPROVAL_GATES": "K4,K5",
                "MINDCLADE_SIGNING_KEY_CUSTODY": "external-only",
                "MINDCLADE_SIGNING_KEY_PROVIDERS": "gcp-kms,pkcs11-hsm",
                "MINDCLADE_TRANSPARENCY_MODE": "append-only-hash-chain",
            },
        ),
        Step(
            key="release-connected-not-qualified",
            label=":no_entry: Connected signing and promotion are not qualified",
            command=(
                "echo 'Source contracts passed; connected KMS/HSM, protected approvals, "
                "transparency service, signing, and promotion remain unavailable' >&2; exit 78"
            ),
            timeout_minutes=5,
            depends_on=("release-signing-source-contract",),
        ),
    ]
