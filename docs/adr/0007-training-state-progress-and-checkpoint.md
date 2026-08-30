# ADR-0007: Training State, Progress, and Checkpoint Recovery

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification and ML-systems qualification
- Compatibility window: Logical checkpoint envelope versioned and readable across supported trainers
- Supersedes: None
- Superseded by: None
- Owners: Training Systems, Architecture
- Reviewers: ML Systems, Data Platform, Platform Operations

## Decision record metadata

- Affected invariants: Mindclade-owned logical state, committed-update/data progress, monotonic
  snapshot epochs, all-rank verification, and resume without double-counting.
- Affected paths: future training protocols, checkpoint adapters, trainer/runtime packages,
  qualification fixtures, and recovery runbooks.
- Affected contracts: logical training state, UpdateId, data-progress ranges, SnapshotEpoch,
  checkpoint manifests/shards, topology envelopes, and resume receipts.
- Security and safety impact: prevents mixed-epoch or substituted checkpoints, requires integrity
  and policy-bound artifact references, and treats unverified snapshots as unusable.
- Migration: wrap provider-native state in the versioned logical envelope, qualify save/resume at
  commit boundaries, then migrate trainers without rewriting prior checkpoints.
- Rollback: select the last fully verified snapshot and compatible trainer envelope, fence newer
  attempts, and replay only uncommitted work.
- Required evidence: multi-rank fault injection, shard/digest corruption tests, exact progress and
  RNG replay, topology/precision compatibility, provider replacement, and recovery drills.

## Context

Provider-native checkpoint formats capture tensors but do not necessarily
capture Mindclade's logical progress, data position, randomness, phase state,
or commit semantics. Multi-rank best-effort saves can mix epochs and make a
resumed run silently repeat or skip training work.

## Decision

Mindclade owns the logical training state independently of PyTorch, scheduler,
or checkpoint-provider layout. At minimum it identifies model and optimizer
logical state, scheduler/scaler state, training phase, committed update count,
committed data progress, dataset/split and feature/view references, recipe and
executable-plan digests, RNG state by declared domain, topology and precision
envelope, callback state that affects semantics, and parent checkpoint.

Progress is committed at explicit boundaries. `UpdateId` and data-progress
ranges distinguish prepared work from durably committed work. A retry may
recompute an uncommitted range, but it must not count an update twice or advance
past data whose result was not committed. Effective global batch and sample
accounting are part of evidence.

A checkpoint uses monotonically increasing `SnapshotEpoch` and four phases:

1. prepare: fence the run/attempt and freeze one logical-state descriptor;
2. write: ranks write attempt- and epoch-scoped shards and local integrity
   metadata;
3. verify: coordinator proves required shard closure, digests, topology mapping,
   and logical-state completeness; and
4. commit: publish one immutable checkpoint manifest and transactionally record
   its reference and committed progress.

An incomplete epoch is never resumable. Resume begins from a committed manifest,
verifies every subject, reconstructs logical state, restores declared RNG and
data progress, and proves the target topology is supported. Resharding or
topology change is an explicit qualified conversion, not an implicit provider
behavior.

Provider-native checkpoint state is an implementation representation. Native
PyTorch Distributed Checkpoint is the initial active substrate, but Mindclade
contracts, manifests, and recovery tests remain authoritative.

## Consequences

- Training can recover across preemption without ambiguous update or data
  replay.
- Checkpoints have immutable identity, lineage, compatibility, and release
  eligibility independent of storage layout.
- Model release references a verified checkpoint plus evaluation evidence, not
  an arbitrary directory.
- Retention and garbage collection preserve committed manifests, reachable
  shards, parent lineage, holds, and rollback checkpoints.

## Rejected alternatives

- Provider-native state as the sole authority was rejected because provider
  schemas do not own Mindclade lifecycle or data semantics.
- Independent best-effort rank saves were rejected because they can publish a
  mixed or incomplete snapshot.
- Step counters without committed data ranges were rejected because replay and
  skip cannot be distinguished.
- Assuming topology-agnostic resume was rejected because layout, optimizer, and
  collective behavior require explicit qualification.

## Qualification and rollback

Before activation, tests cover single-process exact resume, multi-rank failure
during every checkpoint phase, missing/corrupt shard, duplicate commit,
preemption, committed/uncommitted progress, RNG restoration, supported
resharding, previous-version reader, and release lineage. Rollback selects a
previous committed checkpoint and compatible executable plan; incomplete or
revoked checkpoints remain ineligible.
