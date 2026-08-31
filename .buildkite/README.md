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

GPU and release paths are activation-gated and fail while their governed
targets remain inactive. Successful local commands create unsigned evidence inputs only. The
qualified trusted CI signer, not this source tree, produces a signature.

The gated GPU graph separates the DeepEP intra-node SM90 probe from the
multi-node RDMA/IBGDA probe. The latter uses two protected parallel agents and
requires the protected agent pool to provide one shared
`MINDCLADE_DEEPEP_RDZV_ENDPOINT`; it never falls back to a local or untrusted
runner. Both probes require the agent authority to inject the exact source
revision, physical host identity, qualified topology digest, and H100/H200 SKU;
the multi-node probe additionally requires canonical RDMA device identities and
the qualified IBGDA mode. The Buildkite build ID isolates the rendezvous from
concurrent runs. Both steps remain unreachable while the `gpu` activation gate
is closed.

Every dynamic pipeline requires the connected launcher to inject a canonical
`buildkite://` identity, an immutable launcher revision, and a `sha256:`
launcher digest into both the protected environment and trusted context.
`ci-plan` hashes the exact protected definition closure from Git and emits
`immutable-launcher.v1.json` with
`qualification: UNSIGNED_OBSERVATION_INPUT`. Final CI evidence binds that input
by digest; only the independently qualified detached signer can produce the
required-check signature.

Remote Bazel cache use is not source-activated. The only accepted mode is
explicit `disabled`, the public-cache target allowlist is empty, and the cache
namespace still binds schema, private/public classification, namespace epoch,
trust class, platform, architecture, toolchain, and build mode. Cache metadata is provenance only and never qualification
evidence. Protected builds run a clean output-root Wave 1 canary. The recorded
poison-recovery sequence requires namespace revocation, a cacheless rebuild,
output-digest comparison, and reviewed reactivation. All qualification Bazel
tests use one source-controlled cache-disabled wrapper, and the periodic canary
compares one declared binary from two independent output roots. IAM, bucket, and cache
write state remain connected GCP authority outside this repository.

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

The source-side handoff is fail closed until the connected Buildkite control
plane and pinned organization reusable workflows provide the exact launcher
bindings. GitHub governance and signer trust remain separately protected
authorities; this repository cannot provision or self-approve them.

Repository source still cannot prove the origin of Buildkite's initial loader.
The connected control plane must execute an immutable launcher outside the
pull-request checkout, pin it to the reviewed definition revision, and
authorize the qualified signer only after it verifies the observation input.
Missing or mismatched launcher identity, revision, digest, definition tree,
source commit, plan, build ID, or signature remains non-successful.
