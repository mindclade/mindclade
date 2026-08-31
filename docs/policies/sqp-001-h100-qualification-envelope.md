# SQP-001 H100 qualification-envelope approval policy

- Status: Proposed; approval pending
- Applies to: SQP-001 one-H100 functional qualification and any pre-Wave-5 multi-GPU run
- Contract: `sqp-001-h100-approval.v1.schema.json`
- Pending record: `sqp-001-h100-approval.template.yaml`
- Production authority: false

## Fail-closed boundary

The hardware ceiling is fixed by SQP-001, but it is not an allocation or spending approval. Wave 2S implementation, H100 qualification, and any pre-Wave-5 multi-GPU run remain blocked until ML Systems and Finance/Operations approve the exact software and cost envelope at an immutable revision. A local GPU, available quota, cloud credentials, or successful CPU test does not grant authority.

The fixed hardware envelope is one NVIDIA H100 80 GB for functional qualification and at most eight NVIDIA H100 80 GB accelerators in one node for any pre-Wave-5 run. Multi-node execution and a Kubernetes dependency are prohibited. Approval cannot widen this ceiling; a wider or different profile needs a new decision.

An approved record must bind:

- NVIDIA driver, CUDA, cuDNN, and PyTorch versions;
- immutable container image and Nix closure digests;
- the exact reservation/capacity identifier, cost center, currency, maximum authorized cost, and expiry;
- the protected source revision and combined approval receipt; and
- one signed receipt from ML Systems and one from Finance/Operations.

Missing, expired, malformed, mismatched, or revoked approval fails closed before allocation. Runtime qualification verifies observed accelerator model/count, driver/software versions, image/closure digests, node topology, and subject revision against the approved record. A mismatch terminates without claiming evidence from that run.

## Evidence and accounting

Qualification receipts record the approved envelope digest, observed hardware/software, start/end UTC times, immutable model/dataset/recipe/checkpoint subjects, logical update range, cost attribution, result, and artifact/evidence digests. H100 evidence does not imply H200, B200, alternate driver/software, multi-node, Kubernetes, or production qualification.

Finance/Operations can revoke or expire the envelope. Revocation blocks new allocation and stops resumable work at the next safe checkpoint boundary according to policy; evidence and committed checkpoints remain immutable. Cost overrun, topology mismatch, integrity failure, or inability to attribute spend fails the run and triggers the documented escalation path.

## Approval ceremony

Both owners review the same immutable contract instance through the protected approval path. Version 1 intentionally accepts only the pending template and rejects every self-asserted approved or revoked record. Before any state transition is representable, the repository must add a protected cryptographic verifier that resolves each signed receipt, verifies independent role identity against approved trust roots, and binds the receipt to the protected revision and canonical approval-contract digest. That verifier and its verifier-controlled activation schema must land together. Until then, Wave 2S implementation and accelerator allocation remain blocked. Merge of this policy or its pending template is source governance only and grants no accelerator, cloud, deployment, or production authority.
