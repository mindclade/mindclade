## Appendix A26 — Security, supply chain, and biological governance

### A26.1 Data classifications

At minimum:

- public;
- internal;
- confidential;
- restricted biological;
- regulated human-derived;
- secrets/credentials.

Each component declares the classifications it handles. Policy controls execution environment, storage, egress, logging, retention, and operator access.

### A26.2 Repository controls

- protected `main`;
- required reviews and CODEOWNERS;
- signed release tags or equivalent protected release identity;
- secret scanning;
- dependency and license review;
- static analysis;
- restricted workflow permissions;
- pinned third-party CI actions/plugins;
- isolated untrusted CI;
- no long-lived cloud credentials;
- reproducible clean-checkout releases.

### A26.3 Artifact controls

- content digests;
- encryption in transit and at rest;
- least-privilege access;
- immutable publication;
- SBOMs for software artifacts;
- provenance and build attestations;
- signatures for release artifacts;
- admission verification before deployment;
- retention and legal-hold support where required;
- audit receipts for access and promotion.

### A26.4 Biological safeguards

- source terms and license metadata are mandatory;
- restricted sequences and safety corpora are never committed to Git;
- high-risk datasets use isolated projects/buckets and explicit egress policy;
- model release manifests include safety evaluation evidence;
- generated biological payloads follow the same classification controls as source data;
- human-derived data requires separate review, minimization, and retention policy;
- production logs and traces contain references, not payloads.

### A26.5 Security architecture principles

Security is enforced through identity, policy, isolation, immutable evidence, and safe defaults across every domain. Core principles are:

```text
verify explicitly
least privilege and least data
separate control, data, and execution trust
immutable and attributable artifacts
fail closed on authorization/integrity uncertainty
assume retries, compromise, and partial failure
make biological risk a first-class policy dimension
```

Security controls must not rely on repository secrecy, network location alone, mutable tags, or operator convention.

### A26.6 Threat model

The maintained threat model covers:

- compromised user, service, worker, CI runner, dependency, or administrator;
- cross-tenant access and confused deputy;
- stolen credentials or signed transfer URLs;
- malicious or malformed biological/file inputs;
- artifact/model/checkpoint tampering;
- poisoned data, dependency, kernel, compiler, or cache;
- privilege escalation in Kubernetes/cloud;
- data exfiltration through logs, telemetry, outputs, egress, or side channels;
- denial of service and cost exhaustion;
- unsafe biological design/generation or misuse;
- insider error/abuse;
- backup, recovery, and break-glass compromise.

Threat models are updated when trust boundaries, public capabilities, data classes, deployment modes, or major providers change.

### A26.7 Identity classes

Distinct identities exist for:

```text
human user
service principal/application
CI builder/release signer
control-plane service
worker attempt/workload
Kubernetes/controller
external integration/source connector
break-glass administrator
```

Identities are non-shared, attributable, revocable, and scoped to audience/environment. Production automation uses workload identity and short-lived credentials. Google Identity Platform owns initial application-user authentication and centrally managed lifecycle for development, staging, and production; Mindclade's control plane remains authoritative for tenant membership and authorization.

### A26.8 Authentication

Authentication requirements include:

- phishing-resistant MFA for privileged human access where supported;
- Google Identity Platform OIDC issuer/audience binding for initial application-user authentication;
- centralized user lifecycle and rapid revocation;
- workload identity federation rather than long-lived keys;
- audience/issuer/expiry/signature validation;
- service-to-service authenticated transport;
- token binding/context where appropriate;
- separate development/staging/production trust;
- a fake issuer only in local/hermetic tests, with no path to connected environments;
- no secrets in source, images, build logs, or persistent pod specs.

Authentication failure never degrades to anonymous internal access.

### A26.9 Authorization model

Authorization is deny-by-default and action/resource based. A decision includes:

```text
principal and authentication strength
action
resource and tenant/project ownership
resource state and revision
data/biological classification
purpose/entitlement
execution environment and region
policy version and contextual constraints
```

Critical actions—policy changes, public model/data release, artifact quarantine override, destructive deletion, support access, break-glass—require stronger controls such as reason, step-up, dual approval, time bounds, and audit.

### A26.10 Tenant isolation

Isolation is layered:

- tenant/project identifiers in every resource and query;
- server-side authorization on every operation;
- scoped worker identities and artifact permissions;
- database ownership/row isolation controls where appropriate;
- cache keys and browser/session clearing;
- network and namespace/node-pool segmentation by risk;
- separate encryption keys or projects for stronger classifications;
- no cross-tenant batching or shared buffers without explicit qualification;
- audit and tests for enumeration/count/timing leakage.

Namespace separation alone is not treated as a complete tenant boundary.

### A26.11 Data-classification enforcement

Classification travels with artifacts, resources, jobs, logs, and generated outputs. Policy controls:

```text
allowed storage and region
encryption key class
who/what may access
approved compute/worker pools
egress and external tools
logging/diagnostics
sharing/publication
retention/deletion/legal hold
model training and generation eligibility
```

Classification cannot be silently downgraded. Derived data and generated artifacts inherit the highest relevant class unless a reviewed transformation proves declassification.

### A26.12 Secrets management

Secrets are stored in approved secret systems and referenced by logical name/policy. Requirements:

- short-lived dynamic credentials where possible;
- per-workload/service scope;
- automatic rotation;
- access audit;
- envelope encryption and key separation;
- no secrets in environment variables when safer projected/file or brokered mechanisms exist;
- no secrets in command lines, telemetry, crash dumps, checkpoints, notebooks, or support bundles;
- revocation and compromise runbooks.

Local development uses dedicated non-production credentials and documented secure storage.

### A26.13 Key management and encryption

Encrypt data in transit and at rest with managed, policy-approved cryptography. Key hierarchy separates environments, tenants/data classes where required, signing, artifact encryption, database, backups, and secrets.

Key operations are logged and access-controlled. Rotation and re-encryption plans preserve artifact identity/lineage. Cryptographic algorithm and key-version metadata are recorded without exposing key material.

### A26.14 Network and egress security

Network policy is allowlist-oriented by workload class. Controls include:

- private service endpoints where appropriate;
- ingress through authenticated gateways;
- service-to-service identity and encryption;
- restricted DNS and external egress for data/worker pools;
- source connector egress through controlled destinations/proxies;
- separate policies for RDMA/internal collectives;
- no public exposure of worker/rendezvous/debug ports;
- flow logs/alerts with privacy-aware retention;
- tested deny behavior.

High-risk biological workloads may use isolated projects/networks with no general internet egress.

### A26.15 Compute isolation

Execution controls include:

```text
immutable signed images
non-root/minimal privileges
pod/container sandboxing where compatible
restricted host mounts/devices
separate node pools/projects for sensitive workloads
attempt-scoped local storage and cleanup
no arbitrary user images/code in production worker pools without sandbox policy
GPU memory/buffer isolation and lifecycle controls
node image/driver/firmware qualification
```

Research or customer-supplied code runs only in a deliberately designed sandbox tier, not inside trusted training/inference workers.

### A26.16 Secure software development lifecycle

The SDLC requires:

- threat modeling for significant changes;
- CODEOWNERS and review separation for sensitive paths;
- static analysis, dependency/license review, secret scanning, and fuzzing where relevant;
- security tests mapped to abuse cases;
- pinned CI actions/plugins/toolchains;
- isolated untrusted builds;
- signed provenance and SBOMs;
- vulnerability triage and remediation SLAs;
- secure defaults and documented exceptions;
- release/admission verification.

Security review depth follows risk, not line count.

### A26.17 Supply-chain security

The trusted path is:

```text
protected source
→ pinned dependencies/toolchains
→ isolated reproducible build
→ qualification
→ SBOM/provenance
→ signature/attestation
→ registry policy
→ deployment/load admission verification
```

Controls address dependency confusion, compromised registries, malicious code generation, cache poisoning, compiler/kernel binaries, base images, third-party source mirrors, and signing identity compromise. Runtime installation from public package indexes is prohibited in production.

### A26.18 Artifact integrity and authorization

Artifact access checks exact generation, action, principal/workload, classification, tenant/project, and purpose. Upload commit verifies digest, size, schema, provenance expectations, and attempt fence. Download uses scoped authorization and integrity verification.

Mutable aliases cannot bypass revoked/quarantined versions. Artifact revocation propagates to deployment/job admission and impact analysis.

### A26.19 Biological input security

Parsers and pipelines assume external biological files are untrusted. Controls include:

- bounded streaming and decompression limits;
- size/count/depth limits;
- fuzzing and malformed-input fixtures;
- path/archive traversal prevention;
- no executable content handling;
- strict diagnostics without payload leakage;
- quarantine and operator-safe inspection;
- source terms and integrity validation;
- isolation of native parsers/extensions.

Scientific validity checks complement, but do not replace, memory and resource safety.

Agent-visible source documents, retrieved records, model outputs, and tool results are also untrusted content. They cannot modify system policy, expand tool scope, supply credentials, approve their own action, or override data classification. Retrieval and tool adapters preserve provenance and clearly separate instructions supplied by trusted operators from content supplied by external sources.

### A26.20 Biological governance and responsible-use policy

Policy classifies model/dataset/use cases by capability and risk. It may govern:

```text
which datasets/models a principal may access
which biological modalities or design tasks are permitted
maximum generation/sampling scope
restricted target or sequence screening
allowed external tools/databases
generated-output classification and review
public/export eligibility
human oversight or dual control
logging, retention, and incident escalation
```

Controls are versioned and auditable. Safety policy belongs in stable service/evaluation/inference contracts, not ad hoc UI checks or hidden worker scripts.

For agents, policy evaluation occurs at run admission and again at each consequential action because available evidence, target resources, costs, and risk may change. Approval receipts bind exact action intent, parameters or digests, policy version, approver identity, scope, and expiry; broad conversational approval is not transferable authority.

### A26.21 Human-derived and regulated data

Human-derived data requires dedicated review covering legal basis/consent, minimization, de-identification limits, re-identification risk, allowed purposes, data residency, access, encryption, retention/deletion, auditing, model memorization risk, and release restrictions.

Identifiers and raw data are separated where possible. Derived features and model artifacts are assessed for continued sensitivity. Public release is prohibited absent explicit approval and evidence.

### A26.22 Model and output security

Model bundles and generated outputs can be sensitive assets. Controls include:

- model access entitlements and watermark/usage evidence where appropriate;
- download versus hosted-use distinctions;
- rate/quota and abuse detection;
- prompt/input/output classification;
- restricted design output containment;
- model extraction and exfiltration considerations;
- safety evaluation before deployment/promotion;
- incident/revocation mechanisms;
- no raw model weights in logs, crash dumps, or unapproved local caches.

### A26.23 API and abuse protection

Public edges enforce authentication, authorization, request/body limits, schema validation, rate/concurrency quotas, idempotency, timeouts, safe error mapping, anomaly detection, and protection against enumeration/resource exhaustion.

Expensive scientific operations require durable admission and cost controls. The platform rejects requests whose declared resource or safety envelope is unsupported rather than beginning uncontrolled work.

Agent and tool edges additionally defend against prompt injection, confused-deputy behavior, schema smuggling, cross-run memory contamination, recursive fan-out, approval spoofing, indirect data exfiltration, and tool-result forgery. Tool selection is allowlisted by exact capability and version; network and filesystem access is never inferred from model intent.

### A26.24 Logging, telemetry, and diagnostics security

Signals are classified and minimized. Default prohibitions include raw sequences/structures, credentials, signed URLs, model weights, restricted sample identities, and unrestricted user inputs. Diagnostic capture requires authorization, reason, scope, retention, and access audit.

Security events route to controlled monitoring. Audit integrity and access are stronger than ordinary operational logs.

### A26.25 Backup, recovery, and break-glass

Backups are encrypted, access-controlled, immutable where appropriate, tested, and covered by key/credential recovery. Restore procedures verify authorization, integrity, and environment isolation.

Break-glass access is:

- limited to named emergencies;
- strongly authenticated;
- time-bounded;
- reasoned and approved where feasible;
- fully audited and alerted;
- automatically revoked;
- followed by review and credential/session validation.

Break-glass does not mean bypassing artifact integrity or silently editing audit/run records.

### A26.26 Incident response

Security incidents follow:

```text
detect and classify
→ contain identities, workloads, artifacts, or egress
→ preserve evidence
→ identify lineage/blast radius
→ eradicate and rotate/rebuild
→ recover from verified state
→ notify according to policy
→ post-incident review and control updates
```

Runbooks cover credential compromise, cross-tenant access, malicious dependency/image, data exfiltration, unsafe biological output, artifact tampering, CI/signing compromise, and insider misuse.

### A26.27 Vulnerability management

Dependencies, images, hosts, clusters, services, and native components are continuously inventoried and scanned. Findings are triaged by exploitability, exposure, data class, and compensating controls. Remediation SLAs are policy-defined.

Exceptions include owner, risk, controls, scope, and expiry. A scanner pass is not proof that an artifact is secure; it is one evidence source.

### A26.28 Third-party and vendor risk

Third-party systems are reviewed for:

- security and support posture;
- data access/retention/training terms;
- regional/compliance capability;
- identity and audit integration;
- incident notification;
- availability and exit strategy;
- artifact/software supply chain;
- license and intellectual property;
- biological data/use restrictions.

Only required data is shared. Contracts and technical controls prevent accidental expansion of vendor authority.

### A26.29 Security assurance levels

| Level | Required evidence |
|---|---|
| `security-s0` | threat classification, secure defaults, static/secret/dependency checks |
| `security-s1` | authentication/authorization, encryption, tenant isolation, logging/redaction tests |
| `security-s2` | workload/network/supply-chain controls, fuzz/abuse/failure tests, audit |
| `security-s3` | restricted biological/human-data governance, penetration and recovery exercises |
| `security-s4` | sustained monitoring, incident/break-glass/DR drills, independent review and release assurance |

### A26.30 Capability-local qualification progression

**Milestone 0 — identity and policy foundation:** tenant/project resource model, workload identity, authorization library, classifications, secrets, audit, and threat model.

**Milestone 1 — trusted artifact/workload path:** signed builds, provenance/SBOM, artifact authorization/integrity, restricted CI, Kubernetes/network security, and worker scopes.

**Milestone 2 — biological governance:** dataset/model/use policies, restricted worker pools, safety evaluation/output handling, human-derived data process, and abuse controls.

**Milestone 3 — assurance and response:** vulnerability SLAs, penetration tests, incident/break-glass/backup drills, vendor risk, and independent production review.

### A26.31 Definition of done

Security is production-ready when:

1. every human/service/worker/build identity is attributable, short-lived where possible, and least-privileged;
2. authorization decisions bind action, resource, tenant, classification, context, and policy version and fail closed;
3. data classification propagates through artifacts, jobs, compute, egress, telemetry, outputs, and retention;
4. secrets, keys, and credentials never rely on Git, images, logs, or long-lived static distribution;
5. untrusted inputs/code/builds are isolated from trusted release and execution paths;
6. artifacts and deployments verify digest, provenance, signature, and policy;
7. tenant isolation, abuse controls, parser/input safety, and biological governance have negative/failure evidence;
8. restricted and human-derived data have explicit purpose, access, region, retention, and release controls;
9. incidents, break-glass, backup/restore, revocation, and supply-chain compromise are exercised;
10. all security exceptions are scoped, owned, compensated, visible, and expiring.

### A26.32 Final security invariants

- identity and policy are explicit at every trust crossing;
- authorization never fails open;
- classification cannot be silently downgraded;
- production trust begins at protected source and ends with verified runtime artifacts;
- biological inputs and outputs are security assets, not ordinary application payloads;
- logs and diagnostics minimize rather than replicate sensitive data;
- recovery is from verified state, never from convenience copies.
