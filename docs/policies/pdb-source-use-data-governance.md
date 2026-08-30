# PDB source-use and data-governance approval policy

- Status: Proposed; approval pending
- Applies to: SQP-001 PDB acquisition, retained source objects, derived releases, and publication
- Contract: `pdb-source-use-approval.v1.schema.json`
- Pending record: `pdb-source-use-approval.template.yaml`
- Production authority: false

## Fail-closed boundary

The pending record is the repository truth until Legal, Data Governance, and Biological Safety independently approve one immutable subject. Pending status authorizes no PDB acquisition, dataset publication, Wave 2S implementation, connected source mutation, or production use. Local code, a reachable public endpoint, technical feasibility, or a founder statement cannot substitute for approval.

An approved record must bind:

- the protected source revision and canonical decision receipt;
- the exact source terms URI and terms digest reviewed by Legal;
- the immutable acquired snapshot manifest digest and frozen SQP-001 cutoff;
- permitted purposes, restricted-data classes, retention, export, and release authority;
- the biological-safety screening and escalation policy digest; and
- one signed receipt from each required independent role.

The source connector must verify status and subject binding before acquisition. Curation and publication must carry the approved policy reference through every raw, normalized, split, feature, model, and evidence subject. Missing, malformed, stale, mismatched, or revoked approval fails closed. A derived artifact cannot broaden allowed purpose or export rights.

## Handling and lineage

Original retrieved bytes are immutable artifacts with provider identifier, release metadata, retrieval time, integrity digest, media type, and policy reference. Parsing preserves source fidelity; normalization creates a new lineage-linked artifact and receipt. Quarantined, malformed, ambiguous, or policy-denied records never enter the eligible release.

Retention or export applies to source and every derivative. Release tooling verifies policy closure and refuses subjects with missing lineage, incompatible classification, or a revoked approval. Revocation blocks new acquisition and publication, preserves evidence, quarantines affected candidates, and triggers an impact inventory; it does not silently delete or rewrite immutable history.

## Approval ceremony

The accountable owners review the same immutable revision and canonical contract instance through the protected approval path. Their signed receipts are combined into one approval receipt digest. Only then may a reviewer change `status` to `approved` and add the fields required by the schema. Repository merge proves source state only; connected acquisition and publication need separate signed qualification evidence.
