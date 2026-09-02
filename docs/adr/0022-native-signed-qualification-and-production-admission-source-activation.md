# ADR-0022: Native signed qualification and production admission source activation

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-02
- Effective date: Pending connected ratification; source-only development authorized 2026-09-02
- Compatibility window: No production runtime compatibility is granted by this decision
- Supersedes: None
- Superseded by: None
- Owners: Architecture, Contract Governance
- Reviewers: Security, ML Systems Performance, Release Engineering

## Context

ADR-0016 activated the five operation-local Pairformer packages but correctly
left generic native infrastructure in target status until it had a concrete
policy closure. The native component now has an explicit Bazel policy-input
closure and focused tests for immutable qualification receipts, detached
Ed25519 trust, revocation, rollback, exact capability inspection, callable
node contracts, and fail-closed loading.

Source implementation is not qualification. This checkout has no trusted K4
hardware evidence, no K5 release root, no production signature, no promoted
capability, and no nonempty native selector table.

## Decision

Activate the exact signed-qualification, capability-index, and loader source
paths listed by this ADR under `//kernels/native:native_policy_inputs` and the
focused qualification, capability-index, and loader tests. Govern the new
callable-node ABI sources as target inputs and its derived compact selector
table as generated output until their owning qualification lane promotes an
exact capability.

The signed Python index is a validation, explanation, and pre-load authority
only. It cannot select an adapter for `torch.ops` execution. Native execution
requires a build-time generated immutable table whose rows reconcile exactly
with a trusted, non-revoked K5 release projection. The loader rejects every
nonempty Python-only admission until that native selection and reconciliation
path is implemented and qualified.

K4 and K5 receipts bind native manifest schema 4, generator 8, and
BuildReceipt v4. Earlier receipts remain non-executable even when signed.
AutogradPolicy.REQUIRED capabilities bind forward and backward artifacts
atomically. Rollback is a new immutable signed record selecting a prior
qualified capability; neither promotion nor rollback mutates a prior record.

The checked-in trust index and generated native table contain zero capability
rows. Deterministic CPU test keys are confined to test code, are named
`test-only`, and cannot sign or verify production evidence. Production trust
roots must be supplied explicitly through protected runtime configuration.

The protected release source lane cannot read a private key. It accepts only a
detached ECDSA P-256 signature from an allowlisted `gcp-kms://` or
`pkcs11-hsm://` key identity declaring HSM protection, verifies that signature
against an explicitly supplied public key, and binds canonical K4 and K5
approval-record digests into the release payload. K4 and K5 require different
reviewer identities and approval IDs; the external signer must be a third
identity. Signature attachment appends a canonical hash-chained transparency
record. Verification requires that record and rejects any later revocation.

The protected Buildkite release definition exercises external-signature,
independent-approval, verification, transparency-chain, revocation, and
rollback-selection behavior before stopping with a connected-not-qualified
gate. The drill revokes one immutable release digest and selects a distinct
previously signed digest without rebuilding it or mutating history. This is
source evidence only: no connected KMS/HSM, protected approval system,
append-only service, signing identity, promotion, or production capability is
asserted, and the checked-in capability tables remain empty.

## Consequences

The repository can validate the source contracts and exercise test-only
signing without claiming accelerator qualification. A future promotion must
provide exact K0-K5 receipt roots, runtime compatibility, artifact and bundle
digests, SBOM and provenance digests, a protected Ed25519 signature, and a
matching native table projection. Signature, digest, compatibility,
revocation, forward/backward completeness, or native-table mismatch fails
closed before library loading.

## Rejected alternatives

Allowing Python selection to invoke `torch.ops` was rejected because runtime
execution must use immutable native adapter pointers. Checking in a sample
promotion was rejected because CPU or fabricated evidence cannot establish K4
or K5. Repository private keys and ambient trust-root discovery were rejected
because production signing authority belongs to protected infrastructure.
Mutable revocation flags were rejected in favor of signed append-only control
records.

## Qualification and rollback

Source verification covers canonical JSON, digest stability, exact schemas,
test-only Ed25519 verification, atomic REQUIRED artifacts, deterministic
selection, revocation, rollback, callable-node projection, and fail-closed
loading. It does not satisfy GPU numerical, performance, or release gates.
Rollback of this source activation restores the affected manifest entries to
target and supersedes this ADR. Runtime rollback becomes available only after
a signed prior K5 capability and matching native projection exist.

## Decision record metadata

- Affected invariants: no unqualified native execution; immutable signed evidence; FWD/BWD co-promotion; native-only execution selection; no checked-in private keys
- Affected paths: `kernels/native/python/`; `kernels/native/manifests/`; `kernels/native/tests/`; `kernels/native/generated/qualified_capabilities.generated.json`; `kernels/native/generated/qualified_capabilities.generated.cpp`
- Affected contracts: native manifest schema 4; generator 8; BuildReceipt v4; K4/K5 receipts; detached Ed25519 envelope; qualified capability index; native compact capability table
- Security and safety impact: explicit trust roots, exact digest and revocation checks, and native-table reconciliation fail closed before load; no production authority is granted
- Migration: activate only the declared source/test closure; retain zero capability rows; require exact schema-4/generator-8/BuildReceipt-v4 evidence for future admission
- Rollback: supersede this ADR and return activated source paths to target; runtime records remain immutable and require a separately signed rollback receipt
- Required evidence: repository manifest validation; CODEOWNERS coverage; focused source tests; external KMS/HSM signature verification; independent K4/K5 approval binding; append-only transparency-chain validation; exercised source revocation/rollback drill; clean generated-table parity; connected signer, approval, transparency, and target-GPU K0-K5 evidence before any promotion
