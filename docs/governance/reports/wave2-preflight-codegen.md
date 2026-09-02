# CODEX Batch Report: preflight-codegen

## Summary

- Replaced the handwritten regex/dataclass renderer with deterministic Buf/protoc plugin orchestration.
- Locked Buf 1.71.0, protoc 36.0, protoc-gen-go 1.36.12, protobuf-codegen/protoc-gen-rs 3.7.2, and protoc-gen-es 2.11.0.
- Added a manifest-aware package/language matrix: current common, artifact, audit, and job v1 packages generate Go, Python, Rust, and TypeScript; the future inference v1 packages are declared Go/Python-only without creating inference sources.
- Preserved all existing schema field numbers and scalar/wire types; corrected only invalid Go package output paths.
- Replaced Wave 1 generated bindings with real plugin output and generator-owned BUILD targets, hashes, toolchain metadata, binary descriptors, and a deterministic wire fixture.
- Added descriptor compatibility and exact binary round-trip coverage across Python, Go, Rust, and compiled TypeScript.

## Changed files

- Generation authority: `buf.gen.yaml`, `tools/codegen/generate_protocols.py`, `tools/codegen/verify_generated_drift.py`, `tools/codegen/toolchain.lock.json`.
- Dependency authorities: `go.mod`, `go.sum`, `Cargo.toml`, `Cargo.lock`, `package.json`, `pnpm-lock.yaml`, `pyproject.toml`, `uv.lock`, `MODULE.bazel`.
- Contracts: existing Wave 1 `.proto` files under `protocols/proto/**` received corrected `go_package` authorities only.
- Generated outputs: real Go, Python, Rust, and TypeScript bindings plus generator-owned BUILD/readme/index/manifest outputs under `protocols/generated/**`.
- Compatibility: `protocols/compatibility/baselines/protobuf.lock.json` and the schema, OpenAPI, and Protobuf compatibility tests.

## Tests/results

- PASS: `python3.12 tools/codegen/verify_generated_drift.py --root .`.
- PASS: `buf lint`.
- PASS: binary-descriptor `buf breaking` through `test_protobuf_compatibility`.
- PASS: Protobuf guard across 22 schemas.
- PASS: Ruff check/format and Pyright for codegen and compatibility sources.
- PASS: five schema/OpenAPI/Protobuf compatibility tests; the Protobuf suite performed exact Python, Go, Rust, and TypeScript binary round trips.
- PASS: `go test ./protocols/generated/go/...`.
- PASS: `cargo test --locked -p mindclade-protocols`.
- PASS: `pnpm --dir protocols/generated/typescript run typecheck`.
- PASS: uv, Go, Cargo, and pnpm frozen/read-only lock integrity checks.
- BLOCKED: Bazel module lock refresh and Bazel targets require the integration branch's coordinator-owned `pnpm-workspace.yaml` change containing explicit `allowBuilds: {}`.
- BLOCKED: license inventory stops on missing policy metadata for `protobuf@7.36.0`; the policy path is outside this shard.
- NOT RUN: full repository governance/affected gates. The coordinator reports the baseline already fails on 52 unknown `kernels/native` paths and one malformed YAML key owned by the separate kernel workstream.
- No connected-system qualification was attempted.

## Risks/follow-ups

- After integration of `allowBuilds: {}`, run `bazel mod deps --lockfile_mode=update`, commit the resulting `MODULE.bazel.lock`, and run the protocol/codegen Bazel targets.
- Add license-policy records `python/protobuf/7.36.0 = BSD-3-Clause` and `python/pyyaml/6.0.3 = MIT`, then regenerate the inventory and `third_party/notices/NOTICE.generated.txt`.
- Expand `tools/licenses/scan_licenses.py` to resolve actual Cargo, Go, and pnpm closures. Its current static coverage claims still say those authorities contain no third-party dependencies.
- Update `tests/conformance/test_generated_clients.py` to assert the real protoc-gen-es symbols (`export type Identifiers` and `IdentifiersSchema`) instead of the removed fake `export interface` renderer output.
- Reconcile the Nix development shell's uv 0.11.28 with the repository-required uv 0.12.5; validation used pinned `uvx --from uv==0.12.5`.
- No Wave 2 inference source files were created.

## Requested shared changes

1. Coordinator-owned `pnpm-workspace.yaml`: retain explicit `allowBuilds: {}`.
2. Coordinator-owned license allowlist/scanner and generated NOTICE: apply the changes above.
3. Coordinator-owned shared conformance test: replace the fake TypeScript expectation with the stable protoc-gen-es schema/type assertions above.
4. Integration owner: refresh `MODULE.bazel.lock` and run Bazel only after items 1-3 are present.
