# ADR-0008: Founder bootstrap and public-estate transition

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification; source-only exception authorized 2026-08-30
- Compatibility window: Founder bootstrap authorization expires 2026-09-30
- Exception expiry: 2026-09-30
- Supersedes: None
- Superseded by: None
- Owners: Architecture, Security
- Reviewers: Founder for source authorization; independent Security and Developer Platform review required for connected ratification

## Decision record metadata

- Affected invariants: Repository governance remains fail-closed; connected and production qualification require independent evidence; an exception cannot expand or renew itself
- Affected paths: `component.yaml`, `docs/adr/`, `docs/governance/`, `github-config/.github/workflows/protected-apply.yml`, and the public GitHub repository profile
- Affected contracts: `FounderBootstrapException/v1`, repository readiness lifecycle, repository-path manifest, and architecture blueprint manifest
- Security and safety impact: Temporarily permits one tightly bounded privileged bootstrap execution while preserving no-bypass, two-approval, secret, production, and destructive-operation prohibitions
- Migration: Use the exception once to establish or adopt the public GitHub Free repository-level foundation, then replace source authorization with independently verified connected qualification
- Rollback: Revoke or let the exception expire, keep production authority false, and return readiness to `BLOCKED` if any scope, identity, revision, receipt, or guard cannot be proved
- Required evidence: Source validation, exact protected revision, protected workflow identity, single-use receipt, repository protection observation, independent review, trusted CI, signing, and recovery evidence

## Context

The initial public estate must be bootstrapped before organization-level or enterprise-only controls are available. The canonical repository is therefore a public GitHub Free repository governed at repository level. Normal policy requires privileged mutations to flow through independently reviewed connected governance, but that path cannot establish its own first protected identity and controls without a bounded bootstrap authority.

Founder stewardship supplies continuity and explicit source authorization. It is not independent review, connected-control evidence, or production authority. Treating it as any of those would create a self-ratifying trust loop.

## Decision

Adopt the readiness lifecycle:

```text
BLOCKED -> FOUNDER_BOOTSTRAPPED -> CONNECTED_QUALIFIED
```

`BLOCKED` permits governance discovery only. `FOUNDER_BOOTSTRAPPED` permits Wave 1 source implementation and one execution of the existing `github-config/.github/workflows/protected-apply.yml` repository-local privileged workflow under `FBE-0001` and Appendix A3.10; `production_authority` remains `false`. Before that workflow can exist on its own default branch, FBE-0001 also permits one separate initial-publication step: `mindclade-founder` may merge a pull request that publishes only `.github/workflows/protected-apply.yml` with the pinned `sha256:d9109bd4227557cb98a032cfaaa4748744ec8c280733f4f13400da340f1c8de9` content digest to `mindclade/github-config:main`. That step is not protected apply, does not use a direct `main` push or a branch-protection waiver, and cannot be called independent review. Its post-merge receipt records the canonical PR URL and number, observed `main` commit SHA, merge actor, UTC time, and receipt digest before changing the single-use state. No privileged founder workflow exists in `mindclade/.github/workflows/`. `CONNECTED_QUALIFIED` requires the ordinary independently reviewed, subject- and revision-bound connected evidence. The founder exception cannot produce that terminal state by itself.

The canonical profile is `mindclade/mindclade`, visibility `public`, GitHub plan `free`, default branch `main`, and repository-level protection. Public visibility does not change the proprietary license, authorize secrets in source, or create a public API compatibility promise.

The only permitted bootstrap operations are:

- `create`;
- `adopt`;
- `protect`;
- `set-non-secret-variable`;
- `activate-foundation-identity`.

Deletes, replacement, bypass, production promotion, secret export, force push, and self-extension are prohibited. The exception is fail-closed, single-use, bound to `mindclade/mindclade`, `main`, `github-config/.github/workflows/protected-apply.yml`, the protected revision, and the foundation identity, and expires after 2026-09-30. The pre-publication step is separately single-use and bound to `mindclade/github-config`, `main`, the exact workflow content digest, `mindclade-founder`, and an immutable GitHub pull-request receipt; it has no authority to mutate governance settings, establish protection, set variables, or invoke protected apply. Missing or ambiguous state is denial. A connected receipt is the consumption authority; this repository does not fabricate or duplicate that evidence.

Normal independent review remains mandatory for protected changes after protection is established and for every transition to `CONNECTED_QUALIFIED`. The protected repository profile retains no bypass and requires two approvals; the founder exception cannot waive either rule.

## Consequences

Wave 1 source work may proceed without falsely claiming that connected Wave 0 qualification has completed. The public repository can establish its minimum foundation without depending on unavailable enterprise controls. The temporary privileged surface is an explicit, machine-checkable mode of the existing `github-config` protected-apply entry point, not a second workflow or authority in the monorepo.

The source state remains non-production and carries a hard expiry. Initial publication removes only the workflow-publication circularity; the published workflow must still satisfy its own configured executor, review, and evidence gates before it can perform an FBE-0001 foundation execution. If either one-time step cannot complete within scope, a new independently reviewed decision is required; the record cannot be edited to extend itself or broaden permissions.

## Rejected alternatives

- Claim connected qualification from founder approval alone. This is self-ratification and supplies no independent observation.
- Keep the repository private until enterprise controls exist. This conflicts with the authorized public-estate profile and delays the first protected source foundation.
- Grant a general administrative or break-glass token. This is broader than the five required operations and cannot prove single-use or revision binding.
- Allow the workflow to delete, replace, bypass, promote, export secrets, force-push, or renew its authority. Each action can irreversibly expand or conceal compromise.
- Treat GitHub organization settings or CI evidence as source-owned. Those remain separate connected authorities and receipts.

## Qualification and rollback

Source qualification validates ADR-0008, the closed `FounderBootstrapException/v1` schema, `FBE-0001`, its exact initial-publication branch/SHA/actor/receipt contract, component classification, path-manifest membership, and generated blueprint drift. Connected qualification separately verifies the live repository, branch protection, required checks, the exact `github-config/.github/workflows/protected-apply.yml` source and pipeline definition, signer identity, single-use receipt, recovery path, and independent approval at the exact revision.

Any expiry, reuse, unexpected operation, subject mismatch, missing immutable receipt, missing independent review, or attempt to set production authority returns a non-successful result and leaves the lifecycle `BLOCKED` or `FOUNDER_BOOTSTRAPPED`. Rollback disables the founder authorization and bootstrap identity, preserves `github-config/.github/workflows/protected-apply.yml` for its normal independently reviewed governance role, retains audit evidence, and reconciles through that protected path; it never deletes or replaces established resources under this exception.
