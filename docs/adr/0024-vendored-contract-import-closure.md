# ADR-0024: Vendored contract import closure

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-02
- Effective date: Pending connected ratification; source-only implementation authorized 2026-09-02
- Compatibility window: None required; no contract surface changes
- Supersedes: None
- Superseded by: None
- Owners: Contract Governance, Developer Platform
- Reviewers: Architecture, Security

## Decision record metadata

- Affected invariants: the contract build resolves every import from repository content; `buf.lock` declares zero registry dependencies; the descriptor digest is unchanged by the vendoring
- Affected paths: `protocols/google/api/annotations.proto`; `protocols/google/api/http.proto`; `buf.yaml`; `buf.lock`; `tools/codegen/generate_protocols.py`; `protocols/generated/generated-files.manifest.json`
- Affected contracts: none; the descriptor set is byte-identical at `sha256:46514bdee27df6f41f03b63f050b2cfcb95867fc8f291fe943eaf2019693c0ed`
- Security and safety impact: removes a live third-party network service from the build path and pins the third-party closure by content digest rather than by registry pointer; both vendored files are Apache-2.0 with headers intact
- Migration: none; the import statement `google/api/annotations.proto` resolves unchanged, so no consumer, binding, or generated output moves
- Rollback: restore the `deps` entry in `buf.yaml` and the previous `buf.lock`, and delete the two vendored files; the descriptor digest is unchanged either way
- Required evidence: descriptor digest equality before and after; `just generate-contracts` completing with no network access; the generated-files manifest recording both vendored proto digests

## Context

The contract build was described as hermetic, and in every respect but one it
was: pinned Nix toolchain, exact-version checks on every generator plugin, a
staged atomic transaction, and a descriptor digest that joins the whole
governance chain. The exception was `buf build`, which resolved
`buf.build/googleapis/googleapis` from the Buf Schema Registry on every run.

That dependency existed for a single import. Of the 131 `google/*` imports
across `protocols/`, 130 are `google/protobuf/*` well-known types that buf
bundles locally. Exactly one — `google/api/annotations.proto`, imported by
`protocols/proto/mindclade/api/v1/mindclade_service.proto` — came from the
registry, and it is there to support seven `google.api.http` annotations that
define the public HTTP transcoding contract. Those annotations are load-bearing;
removing them would remove the public REST projection.

So a pipeline whose entire value proposition is reproducibility could not run
without a live third-party network service. On a runner without registry access
the build fails outright, which is not a theoretical concern: it is how this
change came to be specified.

A second, quieter problem: `buf.lock` pinned the dependency by commit and
digest, but the pin was a *pointer*. Reproducing the build required trusting
that the registry would continue to serve identical bytes for that commit.

## Decision

Vendor the contract build's entire third-party import closure into the
repository, and remove the registry dependency.

- `protocols/google/api/annotations.proto` and `protocols/google/api/http.proto`
  are committed verbatim from upstream googleapis (Apache-2.0, headers intact).
  They sit under the `protocols` module root, so the import statement
  `google/api/annotations.proto` resolves unchanged.
- `buf.yaml` declares no `deps`.
- `buf.lock` is retained and emptied rather than deleted. An explicit lock
  stating zero registry dependencies is a stronger claim than an absent file,
  and it keeps `buf.lock` available as a governed input digest to the
  compatibility suites, the dependency review workflow, and the Bazel graph.
- `tools/codegen/generate_protocols.py` no longer runs `buf export` against the
  registry on the Python gRPC path. `-Iprotocols` already resolves the vendored
  files, so the export was redundant once they were present.
- The generated-files manifest records the digests of both vendored protos as
  build inputs, alongside `buf.lock` rather than in place of it. The pin is now
  over content this repository holds, not over a pointer to content a third
  party holds.

Upstream currency is a deliberate, reviewed act. These files do not track
upstream automatically; changing them is a contract change and shows up as one.

## Consequences

The contract descriptor is **byte-identical** before and after:
`sha256:46514bdee27df6f41f03b63f050b2cfcb95867fc8f291fe943eaf2019693c0ed`. The
vendored files reproduce the registry module exactly for the two files the build
consumes, so no contract, no generated binding, and no governance join key
changes. This is the evidence that the vendoring is faithful; had the digest
moved, the change would have been a contract change requiring ratification.

`just generate-contracts` now completes with no network access. That closes two
gates that had been red — `test_generated_bindings_are_current_and_compilable`
and `test_internal_sdk_rpc_coverage_is_descriptor_bound_and_explicit` — which
were failing only because their per-file digests could not be refreshed on a
runner that could not reach the registry.

The reproducibility claim in `ARCHITECTURE.md` is now demonstrable rather than
asserted. Any runner with the pinned Nix toolchain can regenerate the estate.

Costs accepted:

- Two upstream files are now this repository's responsibility to review and, if
  ever necessary, refresh. Both are small, stable, and Apache-2.0.
- A future proto that imports something else from googleapis must vendor that
  file too, rather than picking it up implicitly from the registry. This is the
  intended friction: an addition to the contract's third-party closure should be
  a visible, reviewed change.

## Alternatives considered

**Keep the registry dependency and regenerate only in CI.** Rejected. It leaves
the estate unbuildable wherever the registry is unreachable, and it makes the
hermeticity claim conditional on a service outside our control.

**Relax the toolchain pin to get past the failure.** Rejected, and worth naming
because it is the tempting wrong turn. The observed error on a blocked runner is
a `rustfmt version mismatch`, which looks like the blocker but is not: the lock
names `flake.lock:nixpkgs` as rustfmt's authority, and the Nix binary prints
exactly the pinned `rustfmt 1.9.0` while a rustup rustfmt prints
`1.9.0-stable (<hash> <date>)`. The exact-string comparison is what makes the
toolchain hermetic; the fix is to put the Nix toolchain first on `PATH`.

**Delete `buf.lock`.** Rejected. It is referenced by `BUILD.bazel`, the
dependency-review workflow, `protocols/openapi/compatibility-policy.yaml`, both
compatibility test suites, and the manifest verifier. Emptying it achieves the
same result with none of that churn.
