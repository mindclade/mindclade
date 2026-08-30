# Repository drift baseline

This Wave 0 source baseline is generated from repository facts and awaits independent architecture
approval. It does not claim live GitHub, cloud, Kubernetes, or production qualification. Legacy and
operational repositories are inputs for comparison only and are not migration sources.

## Canonical repository

- Anchor commit: `292b71f47b1b29cc9ba7cf760a9bd07cd5e0ffa7`
- Observation scope: `working-tree`
- Base commit: `292b71f47b1b29cc9ba7cf760a9bd07cd5e0ffa7`
- Observed immutable commit: `not commit-bound`
- Working tree state: `dirty`
- Populated path-set SHA-256: `0da98826596f466b22a5236d5f54626d03306b5c8e0bf701372d7b04d3ac9067`
- Content snapshot SHA-256: `4e2c81b39c5b81b913410b2fa4fa1ab390c3790713e1cea7a998a3916d292456`
- Evidence outputs excluded from content snapshot: `build/evidence/repository_drift.v1.json`, `docs/architecture/repository-drift-baseline.md`
- Canonical target paths: 2484
- Populated paths: 200
- Unknown paths: 0
- Premature target paths: 0
- Missing active paths: 0
- Failed or incomplete operational source checks: 7
- Operational sources without a check: 0
- Operational metadata failures: 0
- Default-branch observations incomplete: 5
- Branch-protection observations incomplete: 5
- Appendix A3 inventory failures: 0
- Readiness: `INCONCLUSIVE`

The repository Markdown evidence is a worktree-scoped observation and is excluded from its own
content digest. Once committed, CI regenerates the JSON report from that clean commit using commit
scope.

## Reference-only sources

- Required operational sources not observed: none

| Source | Immutable revision | Canonical remote | Working tree and evidence scope |
|---|---|---|---|
| `bootstrap` | `620d17fcd589cdeb8cef7c292f47e2b7be3b4987` | `https://github.com/mindclade/bootstrap.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |
| `github-config` | `8cdf1f256c0d9310c825fd05ab068295488070a6` | `https://github.com/mindclade/github-config.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |
| `gitops` | `a74d7447b05fca142d54a09504f4d0a9050b9e73` | `https://github.com/mindclade/gitops.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |
| `infrastructure-live` | `c6eded5a2dafd47d62eb587f76d21bb17a9343f0` | `https://github.com/mindclade/infrastructure-live.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |
| `organization-workflows` | `6399abc50c4678d0dff7f33bbd7f6868043ef736` | `https://github.com/mindclade/.github.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |

## Operational estate contract

Component metadata is read from each immutable source revision. The default-branch and protection
columns require signed connected observations; a local checkout or desired-state ruleset is never
promoted into live enforcement evidence. Inventory compares immutable Git trees with the exact
Appendix A3 repository trees.

| Source | Owner | Class | Trust / recovery | Default | Protection | A3 tree |
|---|---|---|---|---|---|---|
| `bootstrap` | `security` | `infrastructure-source` | `ring-0` / `isolated-ring-0` | `INCONCLUSIVE` | `INCONCLUSIVE` | `PASS` (96 target / 96 observed) |
| `github-config` | `developer-platform` | `governance-source` | `privileged-governance` / `tier-0` | `INCONCLUSIVE` | `INCONCLUSIVE` | `PASS` (109 target / 109 observed) |
| `gitops` | `platform-operations` | `deployment-source` | `deployment-control` / `isolated-git` | `INCONCLUSIVE` | `INCONCLUSIVE` | `PASS` (126 target / 126 observed) |
| `infrastructure-live` | `platform-operations` | `infrastructure-source` | `privileged` / `tier-0` | `INCONCLUSIVE` | `INCONCLUSIVE` | `PASS` (310 target / 310 observed) |
| `organization-workflows` | `developer-platform` | `governance-source` | `trusted` / `tier-1` | `INCONCLUSIVE` | `INCONCLUSIVE` | `PASS` (56 target / 56 observed) |

## Source validation observations

These observations retain their actual execution scope. A check on a dirty working tree is not
evidence that the immutable HEAD passed.

| Source | Qualification | Status | Scope | Command | Finding |
|---|---|---|---|---|---|
| `bootstrap` | `ASSERTED` | `BLOCKED` | `immutable-head` | `just ci` | Manifest and formatting checks pass and isolated root-plan metadata validation passes; the aggregate test remains blocked by intermittent provider initialization. |
| `github-config` | `ASSERTED` | `PASS` | `immutable-head` | `application-source ruleset contract review` | The application-source ruleset names required-check.yml, preserves an empty bypass set, and requires two approvals. |
| `github-config` | `ASSERTED` | `PASS` | `immutable-head` | `just ci` | Go, Python, Bazel presubmit, policy, OpenTofu, workflow, buildifier, and whitespace checks passed. |
| `gitops` | `ASSERTED` | `PASS` | `immutable-head` | `just validate && just bazel-test` | Clean HEAD validation, 20 policy tests, 355 manifests, and Bazel 9/9 passed before later working-tree edits were observed. |
| `infrastructure-live` | `ASSERTED` | `PASS` | `immutable-head` | `just ci` | Scoped default-deny policy, 23 security tests, formatting, and four backend-disabled CI-execution validations passed. |
| `organization-workflows` | `ASSERTED` | `BLOCKED` | `immutable-head` | `Buildkite protected-definition launcher qualification` | The dispatcher supplies the definition revision as metadata but no connected immutable launcher proves that the initial loader and hooks came from that revision. |
| `organization-workflows` | `ASSERTED` | `PASS` | `immutable-head` | `just ci` | Bazel workflow governance tests passed (3/3). |

## Greenfield disposition

- Product dependency graph: empty until a later wave activates real product targets.
- Legacy code and history imported: no.
- Migration dispositions: none.
- Existing drift may be refreshed only through architecture review; presubmit rejects new or
  worsened drift.
