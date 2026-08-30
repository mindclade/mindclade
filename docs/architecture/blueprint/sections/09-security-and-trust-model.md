## 9. Security and trust model

### 9.1 Trust zones

| Zone | Examples | Default posture |
|---|---|---|
| Untrusted ingress | users, source data, uploaded artifacts, prompts, tool output | authenticate, authorize, size/schema/content validate, quarantine |
| Product control | Go APIs, policy, relational state, outbox | private network, least privilege, no raw payload logs |
| Trusted scientific execution | approved data/training/eval/inference workers | immutable images, declared inputs, no arbitrary code, scoped identity |
| Restricted sandbox execution | agent tools, external converters, customer-supplied inputs | isolated nodes/runtime, explicit egress, ephemeral storage, capability tokens |
| Evidence and registry | object storage, catalog, signatures, audit | immutable/versioned, encrypted, integrity verified, retention controlled |
| Build and release | presubmit, trusted builders, signing | PR builds untrusted; release identity isolated and attestable |
| Live environment | foundation/GitOps repositories and reconcilers | separate approvals, no source build, digest-only promotion |

Data crossing inward gains trust only through evidence; the originating identity never confers content trust. Model-generated content is always untrusted. Data crossing outward passes tenant, classification, license, biological-safety, export, and release policy.

### 9.2 Security controls by layer

- **Identity:** Google Identity Platform OIDC for initial human authentication; federated workload/CI identity; short-lived credentials; phishing-resistant MFA for privileged users; automated key rotation; break-glass use is time-bound, dual-approved, and audited.
- **Network:** default deny between namespaces; private service endpoints; egress proxies/allowlists for connectors and tools; no worker receives broad Internet access.
- **Compute:** signed/verified images, non-root containers, read-only root filesystems, dropped capabilities, resource limits, node-pool isolation, GPU device access only for admitted workloads.
- **Data:** classification and tenant labels on every artifact; encryption in transit/at rest; KMS separation by environment/class where required; scoped signed URLs; DLP/malware checks for untrusted uploads.
- **Application:** centralized authentication middleware, domain action authorization, request limits, canonicalization before idempotency hash, safe deserialization, parameterized database access, and CSRF/CORS protections for browser flows.
- **Supply chain:** pinned dependencies and toolchains, dependency review, SBOM, signed provenance, vulnerability/license policy, secret scanning, protected builders, and deploy-time signature verification.
- **Biological governance:** source/use restrictions, sequence/structure screening where policy requires, controlled tool capabilities, approval gates, output handling rules, release review, and revocation propagation.

### 9.3 Threats and mandatory mitigations

| Threat | Mandatory design response |
|---|---|
| cross-tenant object or cache access | tenant-scoped authorization and keys, negative tests, no client-selected storage paths |
| confused deputy in worker/tool | delegated token bound to subject, action, artifacts, deadline, and lease |
| duplicate command/side effect | scoped idempotency, canonical request hash, inbox/outbox, tool side-effect key |
| stale worker commits | monotonically increasing lease epoch and expected-version transition |
| prompt/tool injection | treat outputs as data, capability allowlist, schema validation, policy recheck, sandbox |
| malicious model/checkpoint | safe tensor/manifest formats, digest/signature, no arbitrary deserialization code |
| poisoned source data | quarantined raw zone, parser sandbox/fuzzing, provenance, policy/quality gates |
| compromised CI or dependency | isolated trusted builds, pinned source, provenance, signing separation, revocation |
| sensitive telemetry leak | prohibited-field policy, redaction, sampling review, access/retention controls |
| unsafe biological action | risk classification, tool restriction, human approval, audit, output publication gate |

### 9.4 Privacy, retention, and audit

Purpose and retention class are attached at ingestion/request time and propagate to derived artifacts. Access is logged at the metadata/control layer without logging payload. Data-subject or contract-driven deletion uses lineage analysis, legal-hold check, revocation/tombstone, deletion of eligible replicas, and proof of completion; immutable audit retains only the minimum lawful metadata. Backups inherit classification and deletion/retention controls.

Security evidence includes threat models for every supported deployable and tool class, access reviews, restore/key-rotation drills, dependency/SBOM scans, penetration and tenant-isolation tests, biological-governance cases, and incident exercises. A critical security/safety finding blocks release regardless of performance or schedule.
