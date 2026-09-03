# Contributing

This is a private repository. Contributions require an authorized Mindclade
identity and must use a protected pull request.

## Before changing code

1. Identify the semantic owner and affected component.
2. Read `AGENTS.md`, `ARCHITECTURE.md`, the relevant ADRs, and component docs.
3. Classify the change: governance, contract, domain, generated, dependency,
   security, scientific correctness, or release.
4. Update the repository-path manifest first for any governed path change.

## Formatting and static analysis

Use the root commands rather than ambient editor or language defaults:

```text
just format
just format-check
just lint
```

Formatting fixes apply only to editable source. Do not directly format generated
protocol bindings, generated Starlark, architecture renders, or provenance;
change their source or generator and regenerate the complete output family.
Lint suppressions must name the exact rule and explain why the exception is
safe.

## Working copy and branches

Set the clone up once as `AGENTS.md` describes: install the declared hooks,
disable `rerere`, and run Git from inside the pinned Nix shell. Include the
regenerated drift baseline in any commit that changes tracked content.

Before creating a handoff or hand-off-style branch, check that its work is not
already contained in `main`:

```text
git rev-list --left-right --count origin/main...<branch>
```

A branch reporting `0` on the right carries nothing and should be deleted rather
than kept, rebased, or re-reviewed. Several branches in this estate were fully
contained and still attracted repeated attention. Check the same before opening
a worktree, and remove the worktree when its branch is retired.

Local build state grows quickly and is regenerable: `target/` from Cargo, the
Bazel output roots, and the Nix store. When the disk fills, remove `target/`
first, then reclaim the store with `nix store gc`. The store reclamation is
large but not free — the next `nix develop` re-downloads the pinned toolchain.

## Pull-request evidence

Describe affected components, compatibility, risk, data classification,
migration and rollback, tests executed, and any deferred follow-up. Generated
changes include their source edit and drift proof. Security, authorization,
signing, protected-data, biological-safety, and destructive migration changes
require independent specialist review; self-approval is prohibited.

Use `just bootstrap` in a supported Nix shell or devcontainer, then run the
narrowest checks. Before requesting review, run:

```text
just check
just test-affected
```

Connected qualification is never inferred from local tests. Do not deploy,
publish, provision, or promote as part of an ordinary source change.
