## Appendix A8 — Standard package shape

Every maintained package should provide the same minimum evidence.

```text
package/
├── README.md
├── BUILD.bazel
├── component.yaml          # for releasable/deployable/operational components
├── src/ or language-native source layout
├── tests/
└── fixtures/               # only when owned by the package
```

### README requirements

A package README states:

- purpose and non-goals;
- owner;
- public entrypoints;
- dependency restrictions;
- data classifications handled;
- build and test commands;
- compatibility contract;
- failure modes;
- operational considerations if deployable;
- graduation or deprecation status.

### `component.yaml`

Each deployable or independently releasable component has machine-readable metadata.

```yaml
apiVersion: mindclade.dev/v1
kind: Service
metadata:
  name: control-plane
  owner: platform-control-plane
spec:
  maturity: production
  tier: 1
  languages: [go]
  buildTargets:
    - //services/control_plane/cmd/control-plane
  testTargets:
    - //services/control_plane/...
  artifacts:
    - type: oci
      name: control-plane
  protocols:
    - mindclade.training.v1
    - mindclade.artifact.v1
  dataClassifications:
    - internal
    - confidential-metadata
  runtime:
    kubernetes: true
    gpu: false
```

Use this catalog to drive CI selection, ownership validation, deployment documentation, developer portal metadata, release manifests, and security review.

### A8.1 Package classes

Packages are classified because their required evidence differs.

| Class | Examples | Additional requirements |
|---|---|---|
| foundation library | identifiers, retry, serialization | very small dependency budget, broad compatibility |
| domain library | parser, feature logic, model component | semantic fixtures and domain invariants |
| releasable library | public SDK, Python wheel | versioning, public API checks, install tests |
| executable | CLI, conversion tool | entrypoint, exit codes, resource limits |
| service | control plane, gateway | SLO, migrations, authz, runbook, deployment |
| worker | training/evaluation/ingestion | lease, cancellation, idempotency, artifact cleanup |
| model family | CladeFold | state schema, bundle, conversion, model card |
| kernel package | triangle attention | reference, dispatch, qualification, benchmark |
| schema package | Protobuf/JSON Schema | compatibility baseline, code generation |
| deployment package | chart/Kustomize base/CRD | validation, rollout/rollback, policy tests |
| research package | prototype/study | isolation, reproducibility record, no production consumers |

The package class is declared in metadata and drives validation.

### A8.2 Required package metadata

All maintained packages expose machine-readable metadata, directly or inherited from a containing component:

```text
identity and display name
package class
owner and escalation contact
maturity
public entrypoints
source and build targets
test and qualification targets
allowed consumers and dependencies
artifact outputs
protocol/schema dependencies
data classifications
runtime/hardware requirements
compatibility policy
deprecation status
```

Metadata is validated against actual Bazel targets and repository paths.

### A8.3 Public API declaration

A package must distinguish:

- public supported API;
- domain-internal API;
- package-private implementation;
- experimental API;
- generated API;
- test-only API.

Public symbols are listed or mechanically extracted. Compatibility checks compare them with the protected baseline for releasable packages. Deep imports and re-export chains that obscure ownership are rejected.

### A8.4 README as an operator/developer contract

In addition to the existing requirements, a package README answers:

```text
What problem does this package solve?
What problem does it explicitly not solve?
What are the stable concepts and entrypoints?
What inputs, outputs, artifacts, and side effects exist?
What invariants must callers preserve?
What errors are retryable or terminal?
How is cancellation and cleanup handled?
How is compatibility maintained?
How is the package qualified and released?
Who responds when production behavior fails?
```

Generated API reference may supplement but cannot replace the conceptual README.

### A8.5 Expanded `component.yaml` contract

For operational components, extend metadata with:

```yaml
spec:
  lifecycle:
    maturity: production
    deprecationDate: null
  ownership:
    team: platform-control-plane
    oncall: platform-primary
    escalation: security-platform
  interfaces:
    inbound:
      - protocol: mindclade.job.v1
    outbound:
      - protocol: mindclade.artifact.v1
  artifacts:
    - type: oci
      buildTarget: //services/control_plane:image
  data:
    classifications: [internal, confidential-metadata]
    persistence: relational
  runtime:
    cpu: true
    gpu: false
    networkEgress: restricted
    kubernetesServiceAccount: control-plane
  reliability:
    tier: 1
    sloRef: docs/operations/slo/control-plane.md
    runbookRef: docs/runbooks/control-plane.md
  security:
    threatModelRef: docs/security/threat-models/control-plane.md
  qualification:
    requiredSuites:
      - //services/control_plane/tests:release
```

Schema evolution is versioned. Unknown fields fail in repository validation unless explicitly permitted for forward-compatible readers.

### A8.6 Test layout and evidence

Package-local tests cover implementation and contract behavior. Cross-package tests validate conformance and composition. Required categories are selected by package class:

- unit and error-path;
- property/fuzz;
- API/ABI compatibility;
- deterministic/golden;
- integration;
- numerical/gradient;
- security/authorization;
- migration;
- performance/resource bounds;
- failure injection and recovery;
- install/package smoke.

Fixtures are immutable, licensed, minimal, classified, and owned. Generated fixtures include their generator and seed.

### A8.7 Configuration and side-effect policy

A library package may not silently read ambient environment variables, user home files, cloud metadata, or network state. Configuration is passed through typed constructors or context objects.

Import or package initialization must not:

- open network connections;
- initialize CUDA/distributed runtimes;
- start background threads;
- mutate global logging;
- resolve credentials;
- write files;
- perform migrations.

Executables and composition roots own side effects and lifecycle.

### A8.8 Resource ownership and cleanup

Packages that own files, sockets, threads, processes, device memory, leases, or temporary artifacts document:

```text
acquisition
maximum bounds
cancellation
normal close
failure cleanup
crash recovery
ownership transfer
observability
```

Cleanup must be idempotent. Finalizers/destructors are not the sole correctness mechanism for durable resources.

### A8.9 Deprecation and retirement

A supported package deprecation includes:

- replacement and rationale;
- compatibility window;
- automated migration where practical;
- warning strategy without high-cardinality noise;
- last supported release/date;
- owner for consumer migration;
- artifact and documentation retention.

Retirement checks prove no production source, build, protocol, deployment, or artifact consumer remains.

### A8.10 Package generators

Repository generators may create the minimum compliant package shape for each class. They must not create empty implementation forests. Generated scaffolds include working build/test targets, metadata, README prompts, and policy checks, and are removed if the initiating capability is abandoned.

### A8.11 Definition of done

1. Every maintained package has a declared class and owner.
2. Required metadata matches real targets and interfaces.
3. Public APIs are explicit and compatibility-tested.
4. Side effects occur only at composition roots.
5. Tests and fixtures meet package-class requirements.
6. Operational components have SLO, runbook, threat model, and release qualification references.
7. Deprecation and retirement are machine-visible and enforceable.
