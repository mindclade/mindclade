# Buildkite Pipeline

Buildkite is the authoritative heavy CI graph. GitHub workflows only classify
events, dispatch an exact revision, verify returned evidence, and publish the
stable required conclusion.

`pipeline.yml` is intended to load `pipeline.py` from the protected definition
revision. The model validates trusted-context values issued by the pinned
organization workflow and emits canonical pipeline JSON. Presubmit is assigned
to the isolated untrusted tier; protected, nightly, security, GPU, and release
classes require a revision-identical protected definition. The source hooks
recheck the checkout and refuse an ambiguous binding, but the connected loader
must establish their own protected provenance before they can be trusted.

The static loader and every generated step bind to one explicit queue:
`mindclade-untrusted-cpu`, `mindclade-trusted-cpu`, `mindclade-gpu`, or
`mindclade-release`. The connected Buildkite control plane must prove those
queues are separate ephemeral pools with the declared identity and secret
boundary. Missing pools leave a build unscheduled rather than falling back to a
default agent.

GPU and release paths are activation-gated and fail while Wave 0 has no real
target. Successful local commands create unsigned evidence inputs only. The
qualified trusted CI signer, not this source tree, produces a signature.

The gated GPU graph separates the DeepEP intra-node SM90 probe from the
multi-node RDMA/IBGDA probe. The latter uses two protected parallel agents and
requires the protected agent pool to provide one shared
`MINDCLADE_DEEPEP_RDZV_ENDPOINT`; it never falls back to a local or untrusted
runner. The Buildkite build ID isolates the rendezvous from concurrent runs.
Both steps remain unreachable while the `gpu` activation gate is closed.

Validate the source model without a Buildkite credential:

```text
python3.12 .buildkite/pipeline.py --check
```

## Protected-definition roll-forward

Presubmit is designed to execute a pipeline definition pinned to the protected
base revision. Once a connected immutable launcher establishes that binding,
the pre-command hook rejects any head revision that changes the Wave 0
enforcement closure, including Buildkite/GitHub definitions, repository and
blueprint validators, Bazel test declarations, schemas, locks, and their root
configuration. There is no source-controlled bypass.

A legitimate enforcement change requires a two-stage protected operation:
security and developer-platform reviewers first qualify and land a
definition-only revision through an independently approved baseline-update
path; only a later build may use that revision as its protected pipeline
definition. Dependent source changes are rebased and rerun after the
roll-forward.

That connected handoff does not exist in the current estate: the active
application-source ruleset has no bypass actors and organization policy rejects
ruleset bypasses. It also names `pull-request.yml` while this repository's
canonical required workflow is `required-check.yml`. GitHub governance must be
reconciled through its separately protected repository before this source path
can qualify an enforcement change. Until then, such a change is intentionally
blocked rather than self-qualifying from pull-request code.

Likewise, repository source cannot prove that Buildkite's initial loader and
hooks came from the protected definition revision: the dispatcher checks out
the source revision and passes the definition revision only as environment
metadata. The connected Buildkite control plane must supply an immutable
launcher outside the pull-request checkout. Without that independently
verified launcher, protected-base execution remains blocked even though the
source hook validates the intended closure.
