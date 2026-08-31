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
