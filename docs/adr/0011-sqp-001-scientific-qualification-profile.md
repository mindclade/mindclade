# ADR-0011: SQP-001 Scientific Qualification Profile

- Status: Proposed
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: Proposed 2026-08-30; not accepted
- Effective date: Pending connected ratification and required owner approvals
- Compatibility window: A ratified frozen field changes only through SQP-002 or a versioned successor
- Supersedes: None
- Superseded by: None
- Owners: Scientific Leadership, Data Governance, ML Systems
- Reviewers: Computational Biology, Biological Safety, Finance and Operations, Architecture

## Decision record metadata

- Affected invariants: legally usable immutable source snapshot, deterministic biological selection and leakage control, exact 24,000-example release, bounded model/training profile, reproducible checkpoint recovery, and no silent qualification simplification.
- Affected paths: Wave 2S biological parsing, data acquisition/normalization/curation/splits, features/transforms, CladeFold-Q0, reference runtime, training, evaluation, inference, and qualification evidence.
- Affected contracts: source and sample identity, dataset release, FeaturePlan, TransformGraph, model bundle, training recipe, checkpoint, evaluation report, inference result, and hardware/software envelope.
- Security and safety impact: acquisition and publication fail closed without approved source-use terms; protected or disallowed records are excluded or quarantined; GPU use fails closed without an approved cost and software envelope.
- Migration: a change to any frozen field creates SQP-002 or a new profile version with explicit comparability, lineage, migration, and release-selection evidence.
- Rollback: retain immutable raw data and evidence, revoke the candidate dataset/model/checkpoint, restore the last qualified local alias, and never rewrite a published subject.
- Required evidence: independent scientific, data-rights, ML-systems, PDB source-use, biological-safety, and H100 envelope approvals plus deterministic release, overfit, recovery, parity, safe-load, lineage, and artifact-integrity results.

## Context

The first scientific slice needs one workload precise enough to prevent implementers from substituting an arbitrary small dataset, model, objective, or hardware claim. The workload must remain locally testable while preserving source rights, biological lineage, deterministic splits, and a bounded accelerator budget.

This record is a proposal. It does not approve PDB use, dataset acquisition or publication, H100 allocation, cost, a driver/software stack, Wave 2S activation, or production authority.

## Decision

The proposed first scientific qualification profile is exactly:

| Dimension | Frozen value |
|---|---|
| Source cutoff | PDB entries released on or before `2025-12-31T23:59:59Z`; the acquired source snapshot is additionally pinned by manifest digest |
| Biological scope | one protein polypeptide chain; 20 canonical amino acids; length 64–512 residues; experimental resolution at most 3.5 Å; at least 90% complete backbone atoms; exclude nucleic acids, covalently bound non-polymer components, and ambiguous polymer identity |
| Identity and leakage | stable sample identity from normalized chain content/provenance; pinned clustering implementation; no cluster crosses splits at greater than 30% sequence identity |
| Release size | exactly 20,000 training, 2,000 validation, and 2,000 test examples, selected deterministically by cluster then stable sample hash; insufficient eligible examples fails rather than relaxing filters |
| Features | sequence tokens, residue mask/index, relative positional pair features, atom/backbone masks; coordinates/frames are supervised targets only; no MSA, template, ligand, or external embedding dependency |
| Model trunk | `CladeFold-Q0`; at most 75 million trainable parameters; `c_s=256`, `c_z=128`, four Pairformer blocks, eight attention heads; sequence/pair embeddings only |
| Supervised head | four invariant rigid-frame update blocks producing per-residue backbone frame and N/CA/C/O coordinates; masked FAPE plus backbone-coordinate and 64-bin distogram losses |
| Diffusion head | four coordinate-denoiser blocks conditioned on trunk outputs; centered backbone coordinates; cosine noise schedule; velocity prediction; 20 deterministic DDIM sampling steps for qualification |
| Objective weights | supervised FAPE `1.0`, masked backbone coordinate loss `1.0`, distogram cross-entropy `0.3`, diffusion velocity loss `1.0`; normalization is by valid residues/atoms rather than batch count |
| Optimization | AdamW (`beta1=0.9`, `beta2=0.95`, `eps=1e-8`, weight decay `0.1`); peak learning rate `3e-4`; 500-update linear warmup then cosine decay to `3e-5`; global batch 64 chains through accumulation; gradient norm clip `1.0`; qualification seed `20260829`; 10,000-update bounded training run |
| Execution | native PyTorch and PyTorch reference operations only; FP32 reference and BF16 qualified path; AdamW; no compile, provider, TileLang, custom CUDA, or distributed framework dependency |
| Hardware | CPU contract/unit tests; one NVIDIA H100 80 GB functional qualification; maximum eight H100 80 GB GPUs in one node for any pre-Wave-5 run; no multi-node or Kubernetes dependency |
| Required gates | overfit-128, deterministic input receipts, forward/backward/update health, committed checkpoint crash/resume, same-seed evaluation/inference parity, lineage closure, safe model load, artifact integrity |
| Overfit criterion | at least 90% reduction in normalized total training loss from the median of the first ten updates within 2,000 optimizer updates on the fixed 128-example subset |
| Resume criterion | identical logical state/input frontier after restore; FP32 next-update values within `rtol=1e-5, atol=1e-6`; BF16 loss and parameter deltas within `rtol=5e-3, atol=5e-4` under the same hardware/software envelope |
| Product status | internal qualification model only; it makes no frontier-quality, therapeutic, or experimental-validity claim |

PDB acquisition and dataset publication remain blocked until a cryptographically verified PDB source-use approval binds the source terms, snapshot manifest, permitted purposes, retention/export controls, safety escalation, independent approvers, protected revision, and receipt digests. Wave 2S implementation and H100 execution remain blocked until a cryptographically verified SQP-001 H100 approval binds the exact driver, CUDA, cuDNN, PyTorch, container/Nix closure, hardware, reservation, expiry, and maximum authorized cost. The current v1 repository schemas accept only pending templates; an approved or revoked state cannot be represented until its protected receipt verifier and verifier-controlled activation schema land together.

Wave 2S implements only internal typed Python/Rust scientific contracts and local immutable evidence required for this proof. Dataset, feature, transform, model, training, checkpoint, evaluation, and scientific inference protocol/schema paths scheduled for Wave 3 remain absent and manifest status `target`. Their design may be reviewed during Wave 2S, but they receive no public compatibility promise and cannot be created or generated before Wave 3 activation.

## Consequences

- Scientific results are comparable because data, model, objective, optimization, randomness, and tolerances are fixed together.
- Insufficient eligible examples or missing approval is a hard failure, not permission to weaken filters or resize the release.
- CPU tests can prove contracts but cannot stand in for the separately approved one-H100 qualification.
- The internal model makes no product-quality, therapeutic, or experimental-validity claim.
- `production_authority` remains `false` after local qualification.

## Rejected alternatives

- An arbitrary small PDB subset was rejected because it permits unreviewed leakage, selection, and scientific changes.
- Alternate Pairformer dimensions, objectives, seeds, or update counts were rejected because they destroy qualification comparability.
- MSA, templates, ligands, external embeddings, compile, custom kernels, distributed frameworks, and multi-node execution were rejected as unnecessary dependencies for the first proof.
- Silent filter relaxation was rejected because it changes biological scope and leakage risk.
- Treating a local CPU or GPU run as source-use/cost approval was rejected because technical execution cannot grant legal or financial authority.

## Qualification and rollback

Ratification requires protected independent approval by Scientific Leadership, Data Governance, and ML Systems plus approved PDB and H100 policy records. The exact release, 10,000-update run, checkpoint recovery, FP32/BF16 tolerances, same-seed parity, lineage, safe load, and artifacts bind immutable digests in qualification receipts. Failure revokes the candidate and retains raw/evidence for diagnosis; it never rewrites the source snapshot or relaxes a frozen value.
