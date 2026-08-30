# Repository Instructions

These instructions apply to the entire `mindclade` repository. A more specific
`AGENTS.md` may narrow them after its component is activated, but it cannot
weaken the architecture, security, safety, or evidence rules here.

## Authority and scope

- The canonical repository and Go module identity is lowercase
  `github.com/mindclade/mindclade`.
- The generated architecture blueprint and its ordered editable sources define
  the approved design. The repository-path manifest defines approved paths and
  activation status. Sections 1–18 and accepted ADRs take precedence over
  appendices and examples.
- This repository owns product source, contracts, build definitions, and
  immutable release inputs. It does not own GitHub organization settings,
  bootstrap trust, cloud infrastructure, live Kubernetes desired state, or
  environment secrets.
- Wave 0 contains governance and tooling only. Do not create a target or
  deferred product path until its activation wave has a real implementation,
  owner, tests, build target, and evidence.

## Required workflow

1. Read `ARCHITECTURE.md`, the owning component metadata, and relevant ADRs.
2. Update the repository-path manifest before adding, moving, activating,
   retiring, or changing ownership of a governed file.
3. Preserve unrelated work. Do not run destructive Git commands or bulk-stage
   a dirty worktree.
4. Keep native dependency authorities and Bazel targets in agreement. Update
   their locks in the same change.
5. Run the narrowest affected tests, then `just check` and
   `just test-affected` when their prerequisites are available.
6. Report source checks separately from connected GitHub, cloud, cluster, and
   signing qualification.

## Non-negotiable boundaries

- Never commit credentials, tokens, private keys, kubeconfigs, provider state,
  protected biological data, customer tensors, model weights, checkpoints, or
  generated datasets.
- Do not hand-edit generated blueprint or protocol outputs. Change their
  declared sources and run the owning generator.
- Do not use mutable production image tags, filesystem paths as durable
  identity, or a downstream operational repository as a build authority.
- Do not deploy, provision, publish, promote, archive, or mutate a connected
  system without explicit authorization and the protected approval path.
- Fail closed when identity, immutable revision, ownership, independent review,
  signature, or recovery evidence is missing.
- Keep `libs/python` torch-free when that path activates. Product code must
  never import `research/`, and workers must not mutate the control-plane
  database.

## Style and generated changes

- Prefer domain names over generic `utils`, `manager`, `service`, or `api`
  modules outside approved public API boundaries.
- Use UTC, canonical JSON where evidence is hashed, and
  `sha256:<64 lowercase hex>` for digest strings.
- Isolate mechanical/generated diffs and review them through source changes,
  generator versions, compatibility reports, and drift checks.
- Documentation claims capabilities only when repository and qualification
  evidence supports `IMPLEMENTED`; otherwise use the approved readiness label.
