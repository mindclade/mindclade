# ADR-0001: Repository Identity and Ownership

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification
- Compatibility window: Greenfield only; immutable identity begins with Wave 1 activation
- Supersedes: None
- Superseded by: None
- Owners: Architecture, Developer Platform
- Reviewers: Security, Product Engineering, Platform Operations

## Decision record metadata

- Affected invariants: canonical lowercase repository identity, atomic product source, and
  separation of product, infrastructure, GitOps, bootstrap, and organization authorities.
- Affected paths: root identity files, `component.yaml`, `.github/`, `docs/architecture/`, and all
  future module/package namespaces.
- Affected contracts: component metadata, Git/OIDC repository claims, provenance subjects, and
  repository-numeric-identity verification.
- Security and safety impact: prevents a product repository from granting itself operational or
  production authority and prevents case-confused identity claims.
- Migration: this is a greenfield boundary; legacy history and sibling operational sources remain
  reference-only and are not imported.
- Rollback: before Wave 1, replace this ADR and every identity surface atomically; after activation,
  a new ADR and compatibility migration are required.
- Required evidence: exact path manifest, component/schema validation, lowercase-reference scan,
  CODEOWNERS coverage, and protected external repository-identity verification.

## Context

Mindclade needs one atomic source boundary for product semantics, contracts,
build definitions, qualification, and immutable release inputs without making
that repository an authority for privileged trust or live state. Ambiguous
repository names and mixed-case module identities would leak into import paths,
OIDC claims, provenance, generated contracts, and persisted evidence.

The repository estate also needs non-overlapping authorities. A monorepo that
owns cloud resources or live deployment selection could approve, build, and
deploy its own change, defeating separation of duties and recovery isolation.

## Decision

The canonical product repository is the private repository
`github.com/mindclade/mindclade`. The canonical Go module, source provenance,
OIDC repository claim, documentation, and generated-language namespace use that
exact lowercase identity. Repository numeric identity is validated by the
external governance and bootstrap authorities; a name alone is insufficient
for connected trust.

Mindclade adopts a domain-first polyglot monorepo. A domain is the semantic
owner even when its implementation crosses languages. Language roots exist
inside domain or foundation boundaries and do not become competing semantic
authorities.

The estate authorities are disjoint:

| Authority | Source owner |
|---|---|
| Product code, contracts, build, release inputs | `mindclade` |
| Shared GitHub workflow implementations | organization `.github` repository |
| GitHub organization and repository desired state | `github-config` |
| Root trust, federation, signing, audit, break-glass | `bootstrap` |
| Cloud foundations and typed infrastructure exports | `infrastructure-live` |
| Runtime desired state and digest promotion | `gitops` |

Durable application state belongs to the transactional control-plane database.
Immutable scientific and execution evidence belongs to content-addressed
storage plus catalog metadata. Live environment desired state belongs to the
operational repositories. None is a substitute for another.

Every populated component has one semantic owner, one component identity, and
machine-readable dependencies. CODEOWNERS supplies required reviewers but does
not itself define semantic ownership. Temporary stewardship has an explicit
expiry and does not count as independent approval.

## Consequences

- Product changes can be atomic across supported domains and languages.
- Operational repositories consume signed, immutable handoffs and never rebuild
  or write product source.
- Repo-local `.github/` remains a thin event and required-check bridge; it
  cannot own organization policy or the heavy CI graph.
- A repository rename or ownership transfer requires a migration ADR, exact-ID
  trust updates, compatibility handling, recovery proof, and rollback.
- The legacy repository may be referenced only as provenance or through a
  bounded historical evidence reader. It is not an implementation authority.

## Rejected alternatives

- Service-per-repository decomposition was rejected because it fragments
  scientific and contract changes and multiplies release authorities.
- Language-first ownership was rejected because biological, data, training,
  and model semantics would acquire multiple owners.
- One universal system of record was rejected because intended source, durable
  workflow state, immutable evidence, and live desired state have incompatible
  transaction and trust requirements.
- Mixed-case or redirect-dependent module identities were rejected because
  claims and import paths must compare byte-for-byte.

## Qualification and rollback

Wave 0 proves the exact remote/module identity, ownership graph, repository
estate inventory, and protected review path. If enforcement must be rolled back,
the policy change may be reverted independently while retaining the signed
baseline and repository history. Authority is never transferred implicitly by
disabling a check.
