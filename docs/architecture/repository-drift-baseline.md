# Repository drift baseline

This Wave 0 source baseline is generated from repository facts and awaits independent architecture
approval. It does not claim live GitHub, cloud, Kubernetes, or production qualification. Legacy and
operational repositories are inputs for comparison only and are not migration sources.

## Canonical repository

- Anchor commit: `292b71f47b1b29cc9ba7cf760a9bd07cd5e0ffa7`
- Observation scope: `working-tree`
- Base commit: `851ff28f2d1117d50b1474267a1f1d7c7d401bc6`
- Observed immutable commit: `not commit-bound`
- Working tree state: `dirty`
- Populated path-set SHA-256: `3101720b40a682c23e168de753e920122b8809c167868bad0fef61624d0c1022`
- Content snapshot SHA-256: `18be1854e525599b68a77e543b39083b874379c1e510f033b1dcce39938f68ad`
- Evidence outputs excluded from content snapshot: `build/evidence/repository_drift.v1.json`, `docs/architecture/repository-drift-baseline.md`
- Canonical target paths: 2626
- Populated paths: 729
- Unknown paths: 0
- Premature target paths: 0
- Missing active paths: 0
- Failed or incomplete operational source checks: 7
- Operational sources without a check: 0
- Operational metadata failures: 0
- Default-branch observations incomplete: 5
- Branch-protection observations incomplete: 5
- Appendix A3 inventory failures: 5
- Readiness: `INCONCLUSIVE`

The repository Markdown evidence is a worktree-scoped observation and is excluded from its own
content digest. Once committed, CI regenerates the JSON report from that clean commit using commit
scope.

## Reference-only sources

- Required operational sources not observed: none

| Source | Immutable revision | Canonical remote | Working tree and evidence scope |
|---|---|---|---|
| `bootstrap` | `9a221078120026167624d5d38b5fcd3f7c93560a` | `https://github.com/mindclade/bootstrap.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |
| `github-config` | `0ebe461d003e37321c545e6b56c8f1d7016825ed` | `https://github.com/mindclade/github-config.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |
| `gitops` | `7a7ad44c0b0bffc5983ce1040ac7b6bf865efdd1` | `https://github.com/mindclade/gitops.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |
| `infrastructure-live` | `b9de2e33d5d441893b9777bbfa48d6129c339963` | `https://github.com/mindclade/infrastructure-live.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |
| `organization-workflows` | `e195b71d3657aca32cb325990e5e4ef8789b7eee` | `https://github.com/mindclade/.github.git` | excluded; immutable object inspected; selection=declared; checkout HEAD=`excluded`; checks retain their listed scopes |

## Operational estate contract

Component metadata is read from each immutable source revision. The default-branch and protection
columns require signed connected observations; a local checkout or desired-state ruleset is never
promoted into live enforcement evidence. Inventory compares immutable Git trees with the exact
Appendix A3 repository trees.

| Source | Owner | Class | Trust / recovery | Default | Protection | A3 tree |
|---|---|---|---|---|---|---|
| `bootstrap` | `security` | `infrastructure-source` | `ring-0` / `isolated-ring-0` | `INCONCLUSIVE` | `INCONCLUSIVE` | `FAIL` (97 target / 98 observed) |
| `github-config` | `developer-platform` | `governance-source` | `privileged-governance` / `tier-0` | `INCONCLUSIVE` | `INCONCLUSIVE` | `FAIL` (110 target / 111 observed) |
| `gitops` | `platform-operations` | `deployment-source` | `deployment-control` / `isolated-git` | `INCONCLUSIVE` | `INCONCLUSIVE` | `FAIL` (127 target / 128 observed) |
| `infrastructure-live` | `platform-operations` | `infrastructure-source` | `privileged` / `tier-0` | `INCONCLUSIVE` | `INCONCLUSIVE` | `FAIL` (311 target / 312 observed) |
| `organization-workflows` | `developer-platform` | `governance-source` | `trusted` / `tier-1` | `INCONCLUSIVE` | `INCONCLUSIVE` | `FAIL` (57 target / 58 observed) |

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
