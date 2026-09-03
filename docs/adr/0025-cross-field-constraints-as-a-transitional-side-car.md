# ADR-0025: Cross-field constraints as a transitional side-car

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-03
- Effective date: Pending connected ratification; source-only implementation authorized 2026-09-03
- Compatibility window: Until the next descriptor regeneration in the pinned toolchain
- Supersedes: None
- Superseded by: None
- Owners: Contract Governance, Developer Platform
- Reviewers: Architecture, Security

## Decision record metadata

- Affected invariants: exactly one place defines a cross-field constraint; the generator is the only writer of the five projections; the table resolves against the descriptor digest it names, and fails generation loudly when it does not
- Affected paths: `protocols/constraints/cross-field.yaml`; `tools/codegen/generate_cross_field_constraints.py`; `services/control_plane/internal/platform/validation/`; `services/control_plane/cmd/control-plane/wire.go`; the four SDK facades under `internal/sdk/`
- Affected contracts: none; the side-car carries no wire surface and adds no field, message, or RPC to the descriptor set
- Security and safety impact: constraints are enforced in the gRPC unary interceptor after authorization, never before it; identifiers, message names, and dot paths are pinned to a pattern admitting no quote, backslash, or newline, and that property is load-bearing for the five generated languages
- Migration: retire the side-car at the migration trigger in favour of `field_behavior = OUTPUT_ONLY` and a Mindclade `MessageOptions` extension, superseding this record rather than extending it
- Rollback: delete the table and the generated projections; the hand-written validators the extraction replaced are recoverable from this change's parent revision
- Required evidence: `just check-cross-field-drift`; the conformance suite proving the five projections agree; negative fixtures for `conflicts-with`, `xor-with`, and `required-with`

## Context

An invariant that relates two or more sibling fields of a request has no single
field to live on. It gets written into whichever validator noticed it first, and
then copied. The estate had three copies of one such rule when this was written:
`validateDefinition`, `validateWorkflowDefinition` and `validateApproval` each
enumerated the fields a caller may not set on a create. The third list differed
from the other two — correctly, since an approval request carries `requested_at`
rather than the create/update/delete triple — but nothing could establish that,
because nothing compared them. Two further create requests embedding a resource
had no such check at all.

The natural home for these rules is the contract. This repository already
extends `google.protobuf.MessageOptions` with `public_message`, and ADR-0024
vendored `google/api/annotations.proto`, so descriptor-borne contract metadata is
established house style. `google.api.field_behavior = OUTPUT_ONLY` (AIP-203) is
the standard spelling for the class of rule that has instances today.

That path is closed at the time of writing, and not by preference.
`ensure_toolchain` in `tools/codegen/generate_protocols.py` compares seven tool
versions by exact string, including `rustfmt 1.9.0`. That string is produced only
by the Nix build; a rustup build prints `rustfmt 1.9.0-stable (<hash> <date>)`,
and no rustup build can ever produce the pinned form. Where the Nix toolchain is
absent, the descriptor cannot be regenerated at all, so a rule cannot be added to
it.

## Decision

Carry cross-field constraints in a governed side-car,
`protocols/constraints/cross-field.yaml`, generated into the server and all four
SDK facades — **as a transitional carrier, adopted for the toolchain reason
above and for no other.**

- The table names the descriptor digest it was written against, and every
  message and every dot path is resolved against that descriptor before a line
  is emitted. A renamed or removed field fails generation loudly.
- The generator pins no toolchain and shells out to no formatter, so
  `just check-cross-field-drift` is reachable wherever `just generate-contracts`
  is not. That reachability is the entire point of the shape.
- The constraints are applied in one place — the gRPC unary interceptor in
  `services/control_plane/cmd/control-plane/wire.go`, after authorization. Not
  per handler: a rule declared for a message whose handler lacked the call would
  be generated into four facades and enforced by the server nowhere.
- Exactly one place may define a constraint, and the generator is the only
  writer of the five projections. A rule extracted from a hand-written validator
  removes that validator's copy in the same change.

Target state, for when the toolchain is available: `field_behavior =
OUTPUT_ONLY` for the output-only class, and a Mindclade `MessageOptions`
extension following `public_message` for genuine multi-field rules. One governed
input, no digest join, no side-car.

**Migration trigger**, named so that "transitional" does not quietly become
permanent: the next descriptor regeneration performed in the pinned toolchain, or
the point at which that toolchain is available in CI — whichever comes first. At
that point this ADR is superseded and the side-car is retired, not extended.

## Consequences

The estate gains one definition for a class of rule that previously had three
copies and two absences, projected into five languages with a gate that proves
the projections agree and that the table resolves against the committed
contract.

The cost accepted is a second place a contract fact can live, for a bounded
period. That is the failure this table exists to prevent, one level up, which is
why the migration trigger is written into the decision rather than left to
memory.

A secondary cost, and the reason for `--update-digest`: the table pins the whole
descriptor set, so *any* proto change anywhere flips the digest and fails
`check-cross-field-drift` until the pin is refreshed — even when no constrained
message was touched. The pin is kept because it records which contract the table
was reviewed against, which the per-path resolution does not; the friction is
removed by making the refresh one command rather than a hand-edit.

Costs accepted:

- Constraint identifiers, message names and field paths are interpolated into
  five generated languages. The schema pins each to a pattern admitting no
  quote, backslash or newline, so this is not an injection surface — but that
  property is load-bearing and must survive any schema relaxation.
- Only `output-only` has instances today. `conflicts-with`, `xor-with` and
  `required-with` are implemented and exercised only by negative fixtures. A
  vocabulary with no instances is a maintenance liability if it stays empty; it
  is kept because the whole point of the table is to have somewhere for the next
  such rule to go.

## Alternatives considered

**Put the rules in the descriptor now.** Rejected as physically blocked, not as
wrong — it is the target state above.

**Relax the toolchain pin to unblock the descriptor.** Rejected. ADR-0024 names
this as the tempting wrong turn and the reasoning is unchanged: the exact-string
comparison is what makes the pipeline hermetic.

**Enforce per handler rather than in the interceptor.** Rejected. It makes the
table's reach opt-in, and nothing detects a handler that forgets the call. This
was the initial implementation and the review that caught it is why the decision
is recorded here.

**Drop the descriptor digest from the table.** Rejected. Per-path resolution
already catches renamed and removed fields, so the digest adds no detection — but
it records which contract a human reviewed the table against, which nothing else
does. `--update-digest` removes the friction without losing the record.
