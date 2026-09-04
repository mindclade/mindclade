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
- Blueprint waves remain the default implementation sequence. ADR-0015 makes
  their timing guidance for the complete contract program: a contract path may
  be populated only when its manifest status is `active` or `generated` and it
  has a real implementation, owner, build/test labels, consumer, and evidence.
  Target and deferred non-contract product paths remain prohibited.

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

## Local gates and clone state

Some controls live in the clone rather than in the repository, so the repository
cannot enforce them. Each is a per-clone action a contributor must take once.

- Install the declared hooks with `pre-commit install`. The four `pre-push`
  hooks are the only enforcement that does not depend on GitHub or Buildkite,
  and they are the layer that catches an enforcement-closure change before it
  leaves the machine. `git push --no-verify` bypasses them; treat them as
  self-discipline, not as a gate.
- Run `git commit` and `git push` from inside the pinned Nix shell once the
  hooks are installed. They invoke `just format-check`, `just lint`, and
  `just governance`, which require pinned tools such as `nixfmt` and `zizmor`
  that a host toolchain generally lacks. Outside the shell a commit fails on a
  missing binary rather than on the rule it was meant to check.
- Disable `rerere` for this clone (`git config --local rerere.enabled false`)
  and remove any existing `.git/rr-cache`. A recorded resolution can silently
  reinstate a stale generated artifact on a later merge, which is exactly the
  outcome regenerate-on-conflict exists to prevent.
- `git` is not in the pinned tool contract, so merge and rebase semantics depend
  on whichever `git` a contributor runs. Do not rely on version-specific
  attribute behaviour.

## The reviewed drift baseline

`docs/architecture/repository-drift-baseline.md` records a content snapshot over
every populated path. Any change to tracked content therefore makes
`just governance` report stale outputs until the baseline is regenerated.

Run `just governance-refresh` and include the regenerated baseline in the same
commit as the change that invalidated it. The baseline sits under a protected
path, so it is part of that change rather than a follow-up.

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
