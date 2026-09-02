set dotenv-load := false
set export := false
set shell := ["bash", "-euo", "pipefail", "-c"]

uv := env_var_or_default("UV", "uv")
python := env_var_or_default("PYTHON", "python3.12")
bazel_bin := env_var_or_default("BAZEL", "bazel")
bazel := bazel_bin
manifest := "docs/architecture/repository-path-manifest.yaml"
component_schema := "tools/repo/component.schema.json"
evidence_dir := "build/evidence"

# Single cache-disabled Bazel test authority for qualification commands.
[private]
_ci-bazel-test output_root *args:
    BAZEL_OUTPUT_USER_ROOT="{{ output_root }}" {{ bazel_bin }} test --config=ci {{ args }}

default:
    @just --list

# Verify the exact local tools and generated dependency locks.
bootstrap:
    {{ python }} tools/dev/bootstrap.py --root .

# Run non-connected environment diagnostics.
doctor:
    {{ python }} tools/dev/doctor.py --root .

# Apply native formatters to editable source and configuration files.
format:
    ruff format .buildkite tools libs/python tests internal/sdk/python workers/training_worker examples
    find libs/rust -type f -name '*.rs' -print0 | xargs -0 rustfmt --edition 2024
    golangci-lint fmt ./libs/go/... ./services/control_plane/... ./internal/sdk/go/... ./tools/mindcladectl/...
    pnpm run format
    find . -type d \( -name .git -o -name node_modules -o -name build -o -name 'bazel-*' -o -path './third_party/bazel_vendor' \) -prune -o -type f \( -name BUILD -o -name BUILD.bazel -o -name MODULE.bazel -o -name '*.bzl' \) ! -path './protocols/generated/*' ! -path './kernels/native/generated/*' -print0 | xargs -0 buildifier -mode=fix
    nixfmt flake.nix third_party/packages/deep_ep/package.nix
    shfmt -w -i 2 -ci -bn .buildkite/hooks/environment .buildkite/hooks/pre-command
    just --fmt

# Prove that every editable and generated source matches its owning formatter.
format-check:
    ruff format --check .buildkite tools libs/python tests internal/sdk/python workers/training_worker examples
    cargo fmt --all --check
    golangci-lint fmt --diff ./libs/go/... ./services/control_plane/... ./internal/sdk/go/... ./tools/mindcladectl/... ./protocols/generated/go/...
    pnpm run format:check
    find . -type d \( -name .git -o -name node_modules -o -name build -o -name 'bazel-*' -o -path './third_party/bazel_vendor' \) -prune -o -type f \( -name BUILD -o -name BUILD.bazel -o -name MODULE.bazel -o -name '*.bzl' \) -print0 | xargs -0 buildifier -mode=check -lint=warn
    nixfmt --check flake.nix third_party/packages/deep_ep/package.nix
    shfmt -d -i 2 -ci -bn .buildkite/hooks/environment .buildkite/hooks/pre-command
    just --fmt --check

# Run static analysis for every activated language and repository text surface.
lint:
    ruff check .buildkite tools libs/python tests internal/sdk/python workers/training_worker examples
    {{ uv }} run pyright --project pyproject.toml
    {{ uv }} run pyright --project internal/sdk/python/pyproject.toml
    {{ uv }} run pyright --project workers/training_worker/pyrightconfig.json
    cargo clippy --workspace --all-targets --locked --no-deps -- -D warnings
    golangci-lint run ./libs/go/... ./services/control_plane/... ./internal/sdk/go/... ./tools/mindcladectl/... ./protocols/generated/go/...
    pnpm run lint
    shellcheck .buildkite/hooks/environment .buildkite/hooks/pre-command
    actionlint -no-color
    yamllint -c .yamllint.yaml .
    if [[ -d protocols ]] && [[ -n "$(find protocols -type f -name '*.proto' -print -quit)" ]]; then buf lint; fi
    just docs

# Validate path, owner, schema, architecture, ADR, and unit-test governance.
_governance-source:
    #!/usr/bin/env bash
    set -euo pipefail
    for entrypoint in \
      .buildkite/pipeline.py \
      .buildkite/hooks/environment \
      .buildkite/hooks/pre-command \
      tools/ci/affected_targets.py \
      tools/ci/pipeline_plan.py \
      tools/ci/required_check.py \
      tools/ci/evidence_bundle.py \
      tools/dev/bootstrap.py \
      tools/dev/diagnostic_bundle.py \
      tools/dev/doctor.py \
      tools/dev/environment_profile.py \
      tools/docs/render_architecture_blueprint.py \
      tools/docs/validate_blueprint_sources.py \
      tools/licenses/generate_notices.py \
      tools/licenses/scan_licenses.py \
      tools/repo/build_repository_drift_report.py \
      tools/repo/dependency_policy.py \
      tools/repo/owner_policy.py \
      tools/repo/path_policy.py \
      tools/repo/render_repository_tree.py \
      tools/repo/verify_repository_path_manifest.py; do
      test -x "${entrypoint}"
    done
    {{ python }} tools/repo/verify_repository_path_manifest.py \
      --root . \
      --manifest {{ manifest }} \
      --component-schema {{ component_schema }}
    {{ python }} tools/docs/validate_blueprint_sources.py \
      --manifest docs/architecture/blueprint/manifest.yaml
    {{ python }} tools/docs/render_architecture_blueprint.py \
      --manifest docs/architecture/blueprint/manifest.yaml \
      --check
    {{ python }} tools/ci/required_check.py --validate-adrs .
    {{ python }} -m unittest discover -s tools/repo/tests -p 'test_*.py'
    {{ python }} -m unittest discover -s tools/docs/tests -p 'test_*.py'
    wave0_sources="$({{ bazel }} query 'kind("source file", deps(//:wave0_governance_sources))')"
    if printf '%s\n' "${wave0_sources}" | sed -n '/^\/\//p' | grep -Eq '(^|/)(__pycache__|\.venv|node_modules|build)(/|$)|\.py[co]$'; then
      echo "Wave 0 Bazel source closure contains an ambient cache or build artifact" >&2
      exit 1
    fi
    mkdir -p {{ evidence_dir }}

# Render one estate-bound repository report. Protected CI supplies immutable,
# signed connected observations; local unsigned assertions remain diagnostic only.
_governance-report observation_scope allow_inconclusive:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p {{ evidence_dir }}
    temporary_directory="$(mktemp -d)"
    trap 'rm -rf "${temporary_directory}"' EXIT
    organization_workflows_reference="${MINDCLADE_ORGANIZATION_WORKFLOWS_REFERENCE:-../.github}"
    github_config_reference="${MINDCLADE_GITHUB_CONFIG_REFERENCE:-../github-config}"
    bootstrap_reference="${MINDCLADE_BOOTSTRAP_REFERENCE:-../bootstrap}"
    infrastructure_live_reference="${MINDCLADE_INFRASTRUCTURE_LIVE_REFERENCE:-../infrastructure-live}"
    gitops_reference="${MINDCLADE_GITOPS_REFERENCE:-../gitops}"
    organization_workflows_revision="${MINDCLADE_ORGANIZATION_WORKFLOWS_REFERENCE_REVISION:-816955feea11c5c928db6fdd5deedb2d2754c4b8}"
    github_config_revision="${MINDCLADE_GITHUB_CONFIG_REFERENCE_REVISION:-90d26eba7c9361ec391da004f1b1041e9be2cddd}"
    bootstrap_revision="${MINDCLADE_BOOTSTRAP_REFERENCE_REVISION:-a63eb85ec5804091c87c9760ce3074704e17bba7}"
    infrastructure_live_revision="${MINDCLADE_INFRASTRUCTURE_LIVE_REFERENCE_REVISION:-ac559732dd5431aed13994856acf83f82d9c7354}"
    gitops_revision="${MINDCLADE_GITOPS_REFERENCE_REVISION:-638901a42e8a262c711b1563cfffbfbd786b67f2}"
    organization_workflows_check="${MINDCLADE_ORGANIZATION_WORKFLOWS_REFERENCE_CHECK:-PASS|immutable-head|just ci|Bazel workflow governance tests passed (3/3).}"
    organization_workflows_launcher_check="${MINDCLADE_ORGANIZATION_WORKFLOWS_LAUNCHER_REFERENCE_CHECK:-BLOCKED|immutable-head|Buildkite protected-definition launcher qualification|The dispatcher supplies the definition revision as metadata but no connected immutable launcher proves that the initial loader and hooks came from that revision.}"
    github_config_check="${MINDCLADE_GITHUB_CONFIG_REFERENCE_CHECK:-PASS|immutable-head|just ci|Go, Python, Bazel presubmit, policy, OpenTofu, workflow, buildifier, and whitespace checks passed.}"
    github_config_contract_check="${MINDCLADE_GITHUB_CONFIG_CONTRACT_REFERENCE_CHECK:-PASS|immutable-head|application-source ruleset contract review|The application-source ruleset names required-check.yml, preserves an empty bypass set, and requires two approvals.}"
    bootstrap_check="${MINDCLADE_BOOTSTRAP_REFERENCE_CHECK:-BLOCKED|immutable-head|just ci|Manifest and formatting checks pass and isolated root-plan metadata validation passes; the aggregate test remains blocked by intermittent provider initialization.}"
    infrastructure_live_check="${MINDCLADE_INFRASTRUCTURE_LIVE_REFERENCE_CHECK:-PASS|immutable-head|just ci|Scoped default-deny policy, 23 security tests, formatting, and four backend-disabled CI-execution validations passed.}"
    gitops_immutable_check="${MINDCLADE_GITOPS_IMMUTABLE_REFERENCE_CHECK:-PASS|immutable-head|just validate && just bazel-test|Clean HEAD validation, 20 policy tests, 355 manifests, and Bazel 9/9 passed before later working-tree edits were observed.}"
    gitops_worktree_check="${MINDCLADE_GITOPS_WORKTREE_REFERENCE_CHECK:-}"
    connected_receipts="${MINDCLADE_CONNECTED_OBSERVATION_RECEIPTS:-}"
    connected_public_key="${MINDCLADE_CONNECTED_OBSERVATION_PUBLIC_KEY:-}"
    connected_key_version="${MINDCLADE_CONNECTED_OBSERVATION_KEY_VERSION:-}"
    connected_trust_record="${MINDCLADE_CONNECTED_OBSERVATION_TRUST_RECORD:-}"
    connected_review_record="${MINDCLADE_CONNECTED_OBSERVATION_REVIEW_RECORD:-}"
    report_arguments=(
      --repository-root .
      --manifest {{ manifest }}
      --component-schema {{ component_schema }}
      --observation-scope "{{ observation_scope }}"
      --reference-source "organization-workflows=${organization_workflows_reference}"
      --reference-source "github-config=${github_config_reference}"
      --reference-source "bootstrap=${bootstrap_reference}"
      --reference-source "infrastructure-live=${infrastructure_live_reference}"
      --reference-source "gitops=${gitops_reference}"
      --reference-revision "organization-workflows=${organization_workflows_revision}"
      --reference-revision "github-config=${github_config_revision}"
      --reference-revision "bootstrap=${bootstrap_revision}"
      --reference-revision "infrastructure-live=${infrastructure_live_revision}"
      --reference-revision "gitops=${gitops_revision}"
      --output-json {{ evidence_dir }}/repository_drift.v1.json
    )
    if [[ -n "${connected_receipts}" ]]; then
      [[ "{{ observation_scope }}" == commit ]]
      [[ -n "${connected_public_key}" && -n "${connected_key_version}" ]]
      [[ -n "${connected_trust_record}" && -n "${connected_review_record}" ]]
      report_arguments+=(
        --connected-observation-public-key "${connected_public_key}"
        --connected-observation-key-version "${connected_key_version}"
        --connected-observation-trust-record "${connected_trust_record}"
        --connected-observation-trust-record "${connected_review_record}"
      )
      receipt_count=0
      while IFS= read -r binding; do
        [[ -z "${binding}" ]] && continue
        report_arguments+=(--reference-receipt "${binding}")
        ((receipt_count += 1))
      done <<< "${connected_receipts}"
      ((receipt_count > 0))
    else
      report_arguments+=(
        --reference-check "organization-workflows=${organization_workflows_check}"
        --reference-check "organization-workflows=${organization_workflows_launcher_check}"
        --reference-check "github-config=${github_config_check}"
        --reference-check "github-config=${github_config_contract_check}"
        --reference-check "bootstrap=${bootstrap_check}"
        --reference-check "infrastructure-live=${infrastructure_live_check}"
        --reference-check "gitops=${gitops_immutable_check}"
      )
      if [[ -n "${gitops_worktree_check}" ]]; then
        report_arguments+=(--reference-check "gitops=${gitops_worktree_check}")
      fi
    fi
    if [[ "{{ allow_inconclusive }}" == true ]]; then
      report_arguments+=(
        --output-markdown docs/architecture/repository-drift-baseline.md
        --check
        --allow-inconclusive
      )
    else
      report_arguments+=(--output-markdown "${temporary_directory}/repository-drift-baseline.md")
    fi
    {{ python }} tools/repo/build_repository_drift_report.py \
      "${report_arguments[@]}"

# Validate source governance and reproduce the explicitly non-qualifying
# worktree observation committed for review.
governance: _governance-source
    just _governance-report working-tree true

# Protected Buildkite must bind a clean commit and every immutable estate
# source check. INCONCLUSIVE is a hard failure in this recipe.
governance-ci: _governance-source
    just _governance-report commit false

# Validate architecture documentation and Markdown without regenerating files.
docs:
    {{ python }} tools/docs/validate_blueprint_sources.py --manifest docs/architecture/blueprint/manifest.yaml
    {{ python }} tools/docs/render_architecture_blueprint.py --manifest docs/architecture/blueprint/manifest.yaml --check
    markdownlint-cli2

# Local cleanup at different aggressiveness levels.
[private]
_clean mode dry_run:
    #!/usr/bin/env bash
    set -euo pipefail

    mode="{{ mode }}"
    dry_run="{{ dry_run }}"

    if [[ "${dry_run}" == "dry" ]]; then
      action=("-print")
    else
      action=("-exec" "rm" "-rf" "{}" "+")
    fi

    if [[ "${mode}" == "aggressive" ]]; then
      find . \
        \( -path './.git' -o -path './.bazel*' \) -prune -o \
        \( -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" -o -name ".tox" -o -name ".nox" -o -name ".venv" \) -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
        "${action[@]}"

      for path in build dist target node_modules .coverage .coverage.* .cache; do
        if [[ -e "${path}" || -L "${path}" ]]; then
          if [[ "${dry_run}" == "dry" ]]; then
            printf '%s\n' "${path}"
          else
            rm -rf "${path}"
          fi
        fi
      done
    else
      find . \
        \( -path './.git' -o -path './.bazel*' \) -prune -o \
        \( -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" \) -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
        "${action[@]}"
    fi

clean-dry-run:
    just _clean safe dry

# Default (safe): Python and test cache artifacts only.
clean:
    just _clean safe clean

# Aggressive cleanup: safe cache cleanup + local env/build roots.
clean-aggressive:
    just _clean aggressive clean

# Deep cleanup: aggressive cleanup + local Bazel action cache root.
clean-deep:
    just clean-aggressive
    rm -rf build/bazel-user-root

# Integration-only cleanup.
clean-integration:
    just integration-down

# Full cleanup: deep cleanup + integration teardown.
clean-all:
    just clean-deep
    just clean-integration

# Regenerate only declared architecture outputs; review the resulting diff.
generate:
    {{ python }} tools/repo/render_repository_tree.py \
      --manifest {{ manifest }} \
      --appendix-a6 docs/architecture/blueprint/appendices/A06-authoritative-repository-tree.md \
      --write
    {{ python }} tools/docs/render_architecture_blueprint.py --manifest docs/architecture/blueprint/manifest.yaml

# Atomically generate descriptor, transports, OpenAPI, registries, coverage, and manifest.
generate-contracts:
    {{ uv }} run python tools/codegen/generate_protocols.py --root .

# Validate all governed JSON Schemas/fixtures and their committed digest catalog.
check-schema-drift:
    {{ uv }} run python tools/codegen/generate_schemas.py --root . --check

# Fail when a contract source change has not regenerated every committed binding.
check-contract-drift:
    {{ uv }} run python tools/codegen/generate_protocols.py --root . --check
    just check-sdk-plan

# Emit and verify the deterministic offline optional REST-provider comparison plan.
check-sdk-plan:
    {{ uv }} run python tools/codegen/sdk_generator.py plan \
      --openapi protocols/openapi/published/mindclade.openapi.yaml \
      --generation protocols/openapi/generation.yaml \
      --output-root build/sdk \
      --source-revision working-tree \
      --output sdk-generation-plan.json
    {{ uv }} run python tools/codegen/sdk_generator.py verify \
      --openapi protocols/openapi/published/mindclade.openapi.yaml \
      --generation protocols/openapi/generation.yaml \
      --output-root build/sdk \
      --source-revision working-tree \
      --plan sdk-generation-plan.json

# Execute all local source, lock, policy, and documentation gates.
check: bootstrap
    {{ uv }} lock --check
    cargo metadata --locked --no-deps --format-version=1 >/dev/null
    go list -mod=readonly -m >/dev/null
    pnpm install --frozen-lockfile --prefer-offline --ignore-scripts
    pnpm run check:manifest
    buf config ls-modules >/dev/null
    buf config ls-lint-rules >/dev/null
    buf config ls-breaking-rules >/dev/null
    just check-contract-drift
    just format-check
    just lint
    go test ./libs/go/... ./services/control_plane/... ./internal/sdk/go/... ./tools/mindcladectl/...
    PYTHONPATH=internal/sdk/python:protocols/generated/python {{ uv }} run python -m unittest discover -s internal/sdk/python/tests -v
    PYTHONPATH=workers/training_worker/python:internal/sdk/python:protocols/generated/python {{ uv }} run python -m unittest discover -s workers/training_worker/tests -v
    cargo test --workspace --locked
    pnpm --recursive --if-present run typecheck
    pnpm --recursive --if-present run test
    nix flake check --no-accept-flake-config --no-build --no-update-lock-file path:.
    just governance

# Resolve and execute the conservative Bazel test closure.
test-affected:
    #!/usr/bin/env bash
    set -euo pipefail
    targets=()
    while IFS= read -r target; do
      [[ -n "${target}" ]] && targets+=("${target}")
    done < <({{ python }} tools/ci/affected_targets.py --root . --format lines)
    if (( ${#targets[@]} == 0 )); then
      echo "No affected targets"
      exit 0
    fi
    just _ci-bazel-test "${TMPDIR:-/tmp}/mindclade-bazel-user-root" "${targets[@]}"
    just bazel-native-agreement

# Execute the exact target list emitted before a Buildkite pipeline began.
test-planned:
    #!/usr/bin/env bash
    set -euo pipefail
    plan={{ evidence_dir }}/pipeline-plan.v1.json
    [[ -f "${plan}" ]]
    targets=()
    while IFS= read -r target; do
      [[ -n "${target}" ]] && targets+=("${target}")
    done < <({{ python }} -c 'import json,sys; value=json.load(open(sys.argv[1])); print("\n".join(value["targets"]))' "${plan}")
    if (( ${#targets[@]} == 0 )); then
      echo "Plan contains no Bazel targets"
    else
      just _ci-bazel-test "${TMPDIR:-/tmp}/mindclade-bazel-user-root" "${targets[@]}"
    fi
    just bazel-native-agreement

# Resolve the declared Bazel/Nix executable contract and emit measured v2 evidence.
bazel-native-agreement:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${MINDCLADE_TOOLCHAIN_MANIFEST:?enter the pinned Nix shell first}"
    mkdir -p {{ evidence_dir }}
    {{ python }} tools/bazel/toolchain_contract.py validate \
      --manifest "${MINDCLADE_TOOLCHAIN_MANIFEST}" --verify-files
    {{ python }} tools/bazel/toolchain_contract.py resolve \
      --manifest "${MINDCLADE_TOOLCHAIN_MANIFEST}" \
      --bazel "$({{ python }} -c 'import json,os; print(json.load(open(os.environ["MINDCLADE_TOOLCHAIN_MANIFEST"]))["executables"]["bazel"]["path"])')" \
      --output {{ evidence_dir }}/bazel-toolchain-resolution.v1.json
    {{ python }} tools/bazel/toolchain_contract.py agreement \
      --manifest "${MINDCLADE_TOOLCHAIN_MANIFEST}" \
      --resolution {{ evidence_dir }}/bazel-toolchain-resolution.v1.json \
      --output {{ evidence_dir }}/bazel-native-agreement.v2.json \
      --verify-files

# Opt-in local-only cache launcher. CI and release profiles are rejected by the launcher.
bazel-local-cache *args:
    {{ python }} tools/bazel/local_cache.py \
      --checkout . --repository mindclade --system "$(nix eval --raw --impure --expr builtins.currentSystem)" \
      -- {{ args }}

vendor-refresh:
    {{ python }} tools/bazel/vendor.py refresh --repository .

vendor-drift:
    {{ python }} tools/bazel/vendor.py verify --repository .

offline-wave1:
    {{ python }} tools/bazel/vendor.py offline --repository .

# Run a bounded Wave 1 domain suite.
test-domain domain:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ domain }}" in
      contracts) just _ci-bazel-test "${TMPDIR:-/tmp}/mindclade-bazel-user-root" //:wave1_contract_tests ;;
      foundations) just _ci-bazel-test "${TMPDIR:-/tmp}/mindclade-bazel-user-root" //libs:foundation_tests ;;
      control-plane) just _ci-bazel-test "${TMPDIR:-/tmp}/mindclade-bazel-user-root" //services/control_plane:tests ;;
      local) just _ci-bazel-test "${TMPDIR:-/tmp}/mindclade-bazel-user-root" //tests:local_stack_integration_test ;;
      *) echo "Unknown Wave 1 domain: {{ domain }}" >&2; exit 64 ;;
    esac

# Scan the populated source tree and declared licenses without connected access.
security:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p {{ evidence_dir }}
    {{ python }} tools/licenses/scan_licenses.py \
      --root . \
      --output {{ evidence_dir }}/license-inventory.v1.json
    notice_check="$(mktemp)"
    trap 'rm -f "${notice_check}"' EXIT
    {{ python }} tools/licenses/generate_notices.py \
      --inventory {{ evidence_dir }}/license-inventory.v1.json \
      --output "${notice_check}"
    cmp NOTICE "${notice_check}"
    GITLEAKS_CONFIG_TOML="$(cat <<'MINDCLADE_GITLEAKS_CONFIG'
    [extend]
    useDefault = true

    [[allowlists]]
    description = "Ignore untracked local dependency and build caches"
    paths = ['''(^|/)(\.venv|node_modules|build|bazel-[^/]+)(/|$)''']

    [[allowlists]]
    description = "Immutable blueprint debt-metric prose is not an API credential"
    targetRules = ["generic-api-key"]
    condition = "AND"
    regexTarget = "line"
    regexes = ['''Debt metrics include .*deprecated API[ ]use, flaky/quarantined tests''']
    paths = ['''^docs/architecture/blueprint/provenance/MINDCLADE_MONOREPO_BLUEPRINT_v3\.4\.0_OPTIMIZED\.md$''']
    MINDCLADE_GITLEAKS_CONFIG
    )"
    export GITLEAKS_CONFIG_TOML
    gitleaks dir \
      --no-banner \
      --redact \
      --max-target-megabytes 10 \
      --report-format json \
      --report-path {{ evidence_dir }}/secret-scan.v1.json \
      .

# Buildkite fast-presubmit entrypoint.
ci-presubmit:
    just governance-ci
    just test-affected
    just integration-ci
    just security

# Buildkite protected full-CPU entrypoint.
ci-nightly:
    just ci-source-check
    just integration-ci
    just governance-ci
    just test-planned
    just ci-wave1
    just ci-cacheless-canary
    just vendor-drift

# Produce a revision-bound receipt only after the canonical source gate passes.
ci-source-check:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${MINDCLADE_SOURCE_REVISION:?missing source revision}"
    [[ "${MINDCLADE_SOURCE_REVISION}" =~ ^[0-9a-f]{40}$ ]]
    just check
    mkdir -p {{ evidence_dir }}
    {{ python }} -c 'import json,sys; print(json.dumps({"conclusion":"PASS","schema_version":"source-check.v1","source_revision":sys.argv[1],"target":"just check"},sort_keys=True,separators=(",",":")))' \
      "${MINDCLADE_SOURCE_REVISION}" > {{ evidence_dir }}/source-check.v1.json

# Execute the complete Wave 1 closure independently of affected selection.
ci-wave1:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${MINDCLADE_SOURCE_REVISION:?missing source revision}"
    [[ "${MINDCLADE_SOURCE_REVISION}" =~ ^[0-9a-f]{40}$ ]]
    just _ci-bazel-test "${TMPDIR:-/tmp}/mindclade-bazel-user-root" //:wave1_tests
    mkdir -p {{ evidence_dir }}
    {{ python }} -c 'import json,sys; print(json.dumps({"conclusion":"PASS","schema_version":"wave1-full.v1","source_revision":sys.argv[1],"target":"//:wave1_tests"},sort_keys=True,separators=(",",":")))' \
      "${MINDCLADE_SOURCE_REVISION}" > {{ evidence_dir }}/wave1-full.v1.json

# Periodically prove Wave 1 in a clean action-output root with remote caches disabled.
ci-cacheless-canary:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${MINDCLADE_SOURCE_REVISION:?missing source revision}"
    [[ "${MINDCLADE_SOURCE_REVISION}" =~ ^[0-9a-f]{40}$ ]]
    root_a="${PWD}/build/bazel-cacheless-a"
    root_b="${PWD}/build/bazel-cacheless-b"
    rm -rf "${root_a}" "${root_b}"
    just _ci-bazel-test "${root_a}" //:wave1_tests
    output_a="$({{ bazel_bin }} --nohome_rc --nosystem_rc --noworkspace_rc --output_user_root="${root_a}" --bazelrc="${PWD}/.bazelrc" cquery --config=ci --output=files //services/control_plane:control_plane_test | tail -n 1)"
    digest_a="$({{ python }} -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${output_a}")"
    just _ci-bazel-test "${root_b}" //:wave1_tests
    output_b="$({{ bazel_bin }} --nohome_rc --nosystem_rc --noworkspace_rc --output_user_root="${root_b}" --bazelrc="${PWD}/.bazelrc" cquery --config=ci --output=files //services/control_plane:control_plane_test | tail -n 1)"
    digest_b="$({{ python }} -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${output_b}")"
    [[ "${digest_a}" == "${digest_b}" ]]
    mkdir -p {{ evidence_dir }}
    {{ python }} -c 'import json,sys; print(json.dumps({"cache_mode":"disabled","conclusion":"PASS","first_output_digest":sys.argv[2],"independent_output_roots":True,"reproducibility_subject":"//services/control_plane:control_plane_test","schema_version":"cacheless-reproducibility.v1","second_output_digest":sys.argv[3],"source_revision":sys.argv[1],"target":"//:wave1_tests"},sort_keys=True,separators=(",",":")))' \
      "${MINDCLADE_SOURCE_REVISION}" "${digest_a}" "${digest_b}" > {{ evidence_dir }}/cacheless-reproducibility.v1.json

# Resolve the exact changed set and target/gate plan before Buildkite executes it.
ci-plan:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${MINDCLADE_SOURCE_REVISION:?missing source revision}"
    : "${MINDCLADE_PIPELINE_DEFINITION_REVISION:?missing pipeline definition revision}"
    : "${MINDCLADE_PIPELINE_CLASS:?missing pipeline class}"
    : "${MINDCLADE_CONTEXT_JSON:?missing trusted context JSON}"
    : "${MINDCLADE_CONTEXT_DIGEST:?missing trusted context digest}"
    : "${MINDCLADE_LAUNCHER_REVISION:?missing immutable launcher revision}"
    : "${MINDCLADE_LAUNCHER_DIGEST:?missing immutable launcher digest}"
    : "${MINDCLADE_LAUNCHER_IDENTITY:?missing immutable launcher identity}"
    : "${MINDCLADE_CACHE_MODE:?missing explicit cache mode}"
    : "${MINDCLADE_CACHE_PLATFORM:?missing cache platform}"
    : "${MINDCLADE_CACHE_ARCHITECTURE:?missing cache architecture}"
    : "${MINDCLADE_CACHE_TOOLCHAIN_DIGEST:?missing cache toolchain digest}"
    : "${MINDCLADE_CACHE_BUILD_MODE:?missing cache build mode}"
    : "${MINDCLADE_CACHE_CLASSIFICATION:?missing cache classification}"
    : "${MINDCLADE_CACHE_NAMESPACE_EPOCH:?missing cache namespace epoch}"
    : "${BUILDKITE_BUILD_ID:?missing Buildkite build ID}"
    base_arguments=()
    if [[ -n "${MINDCLADE_BASE_REVISION:-}" ]]; then
      base_arguments=(--base "${MINDCLADE_BASE_REVISION}")
    fi
    cache_activation_arguments=()
    if [[ -n "${MINDCLADE_CACHE_IAM_QUALIFICATION_DIGEST:-}" ]]; then
      cache_activation_arguments+=(
        --cache-iam-qualification-digest "${MINDCLADE_CACHE_IAM_QUALIFICATION_DIGEST}"
      )
    fi
    if [[ -n "${MINDCLADE_CACHE_WRITE_ACTIVATION_DIGEST:-}" ]]; then
      cache_activation_arguments+=(
        --cache-write-activation-digest "${MINDCLADE_CACHE_WRITE_ACTIVATION_DIGEST}"
      )
    fi
    mkdir -p {{ evidence_dir }}
    printf '%s\n' "${MINDCLADE_CONTEXT_JSON}" > {{ evidence_dir }}/trusted-context.v1.json
    {{ python }} tools/ci/pipeline_plan.py \
      --source-revision "${MINDCLADE_SOURCE_REVISION}" \
      --pipeline-definition-revision "${MINDCLADE_PIPELINE_DEFINITION_REVISION}" \
      --pipeline-class "${MINDCLADE_PIPELINE_CLASS}" \
      --launcher-revision "${MINDCLADE_LAUNCHER_REVISION}" \
      --launcher-digest "${MINDCLADE_LAUNCHER_DIGEST}" \
      --launcher-identity "${MINDCLADE_LAUNCHER_IDENTITY}" \
      --build-id "${BUILDKITE_BUILD_ID}" \
      --cache-mode "${MINDCLADE_CACHE_MODE}" \
      --cache-trust-class "${MINDCLADE_SOURCE_TRUST}" \
      --cache-platform "${MINDCLADE_CACHE_PLATFORM}" \
      --cache-architecture "${MINDCLADE_CACHE_ARCHITECTURE}" \
      --cache-toolchain-digest "${MINDCLADE_CACHE_TOOLCHAIN_DIGEST}" \
      --cache-build-mode "${MINDCLADE_CACHE_BUILD_MODE}" \
      --cache-classification "${MINDCLADE_CACHE_CLASSIFICATION}" \
      --cache-namespace-epoch "${MINDCLADE_CACHE_NAMESPACE_EPOCH}" \
      "${cache_activation_arguments[@]}" \
      --root . \
      "${base_arguments[@]}" \
      --head "${MINDCLADE_SOURCE_REVISION}" \
      --output {{ evidence_dir }}/pipeline-plan.v1.json \
      --launcher-observation-output {{ evidence_dir }}/immutable-launcher.v1.json \
      --cache-boundary-output {{ evidence_dir }}/cache-boundary.v2.json

# Emit the exact flat organization CI evidence contract for artifact upload.
ci-evidence:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${MINDCLADE_PIPELINE_DEFINITION_REVISION:?missing pipeline definition revision}"
    : "${MINDCLADE_CONTEXT_DIGEST:?missing trusted context digest}"
    : "${BUILDKITE_BUILD_ID:?missing Buildkite build ID}"
    : "${BUILDKITE_BUILD_CREATED_AT:?missing Buildkite build creation time}"
    plan={{ evidence_dir }}/pipeline-plan.v1.json
    context={{ evidence_dir }}/trusted-context.v1.json
    [[ -f "${plan}" && -f "${context}" ]]
    checks=()
    for item in \
      "immutable-launcher={{ evidence_dir }}/immutable-launcher.v1.json" \
      "cache-boundary={{ evidence_dir }}/cache-boundary.v2.json" \
      "repository-governance={{ evidence_dir }}/repository_drift.v1.json" \
      "dependency-and-license-policy={{ evidence_dir }}/license-inventory.v1.json" \
      "secret-scan={{ evidence_dir }}/secret-scan.v1.json" \
      "bazel-native-agreement={{ evidence_dir }}/bazel-native-agreement.v2.json" \
      "fresh-database-integration={{ evidence_dir }}/integration-ci.v1.json" \
      "source-check={{ evidence_dir }}/source-check.v1.json" \
      "wave1-full={{ evidence_dir }}/wave1-full.v1.json" \
      "cacheless-reproducibility={{ evidence_dir }}/cacheless-reproducibility.v1.json"; do
      report="${item#*=}"
      [[ -f "${report}" ]] && checks+=(--check "${item}")
    done
    completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    {{ python }} tools/ci/evidence_bundle.py \
      --context "${context}" \
      --context-digest "${MINDCLADE_CONTEXT_DIGEST}" \
      --pipeline-definition-revision "${MINDCLADE_PIPELINE_DEFINITION_REVISION}" \
      --plan "${plan}" \
      --build-id "${BUILDKITE_BUILD_ID}" \
      --started-at "${BUILDKITE_BUILD_CREATED_AT}" \
      --completed-at "${completed_at}" \
      "${checks[@]}" \
      --output {{ evidence_dir }}/ci-evidence.json \
      --digest-output {{ evidence_dir }}/ci-evidence.sha256

# Prohibit target classes that have no activated manifest entry.
require-activation capability:
    @echo "Capability '{{ capability }}' has no active Wave 0 target or qualification policy" >&2
    @exit 78

# Run an unsigned, non-production DeepEP communication probe on one Linux SM90
# node. Enter `nix develop --no-accept-flake-config --no-update-lock-file .#deepep` first.
test-deep-ep-gpu-intranode:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ "$(uname -s)" == Linux ]]
    gpu_count="${MINDCLADE_DEEPEP_GPUS_PER_NODE:-2}"
    [[ "${gpu_count}" =~ ^[0-9]+$ && "${gpu_count}" -ge 2 ]]
    mkdir -p {{ evidence_dir }}
    MINDCLADE_DEEPEP_NNODES=1 torchrun \
      --standalone \
      --nnodes=1 \
      --nproc-per-node="${gpu_count}" \
      third_party/packages/deep_ep/test_package.py \
      gpu-smoke \
      --scope intra-node \
      --evidence {{ evidence_dir }}/gpu-deepep-intranode.json

# Run only from the protected GPU pipeline. Buildkite parallelism supplies one
# node rank per agent; the protected agent pool supplies a shared RDZV endpoint.
test-deep-ep-gpu-multinode:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ "$(uname -s)" == Linux ]]
    [[ "${MINDCLADE_PIPELINE_CLASS:-}" == gpu ]]
    [[ "${MINDCLADE_SOURCE_TRUST:-}" == protected ]]
    : "${MINDCLADE_SOURCE_REVISION:?missing protected source revision}"
    : "${MINDCLADE_DEEPEP_NNODES:?missing node count}"
    : "${MINDCLADE_DEEPEP_NODE_RANK:?missing node rank}"
    : "${MINDCLADE_DEEPEP_RDZV_ENDPOINT:?missing protected rendezvous endpoint}"
    : "${MINDCLADE_DEEPEP_RDZV_ID:?missing protected rendezvous identity}"
    gpu_count="${MINDCLADE_DEEPEP_GPUS_PER_NODE:-2}"
    [[ "${gpu_count}" =~ ^[0-9]+$ && "${gpu_count}" -ge 2 ]]
    [[ "${MINDCLADE_DEEPEP_NNODES}" =~ ^[0-9]+$ && "${MINDCLADE_DEEPEP_NNODES}" -ge 2 ]]
    [[ "${MINDCLADE_DEEPEP_NODE_RANK}" =~ ^[0-9]+$ ]]
    [[ "${MINDCLADE_DEEPEP_RDZV_ID}" =~ ^[A-Za-z0-9._-]+$ ]]
    mkdir -p {{ evidence_dir }}
    torchrun \
      --nnodes="${MINDCLADE_DEEPEP_NNODES}" \
      --nproc-per-node="${gpu_count}" \
      --node-rank="${MINDCLADE_DEEPEP_NODE_RANK}" \
      --rdzv-backend=c10d \
      --rdzv-endpoint="${MINDCLADE_DEEPEP_RDZV_ENDPOINT}" \
      --rdzv-id="${MINDCLADE_DEEPEP_RDZV_ID}" \
      third_party/packages/deep_ep/test_package.py \
      gpu-smoke \
      --scope multi-node \
      --evidence {{ evidence_dir }}/gpu-deepep-multinode-node-${MINDCLADE_DEEPEP_NODE_RANK}.json

ci-gpu:
    just require-activation gpu
    just test-deep-ep-gpu-intranode

ci-gpu-multinode:
    just require-activation gpu
    just test-deep-ep-gpu-multinode

ci-release: (require-activation "release")

qualify target:
    @echo "Qualification target '{{ target }}' is not active in Wave 0" >&2
    @exit 78

package target:
    @echo "Release target '{{ target }}' is not active in Wave 0" >&2
    @exit 78

integration-up:
    #!/usr/bin/env bash
    set -euo pipefail
    compose=(docker compose -f deploy/local/compose.yaml)
    "${compose[@]}" up -d --wait postgres
    if ! "${compose[@]}" run --rm migrate-control-plane; then
      "${compose[@]}" down --volumes --remove-orphans
      exit 1
    fi
    if ! "${compose[@]}" run --rm rehearse-control-plane-migrations; then
      "${compose[@]}" down --volumes --remove-orphans
      exit 1
    fi

integration-test:
    #!/usr/bin/env bash
    set -euo pipefail
    dsn='postgres://mindclade@127.0.0.1:55432/mindclade?sslmode=disable'
    postgres_targets=()
    while IFS= read -r target; do
      postgres_targets+=("${target}")
    done < <({{ uv }} run python tools/qualification/training_rehearsal.py --list-integration-targets)
    [[ "${#postgres_targets[@]}" -gt 0 ]]
    just _ci-bazel-test "${TMPDIR:-/tmp}/mindclade-bazel-user-root" \
      --test_env="MINDCLADE_TEST_POSTGRES_DSN=${dsn}" \
      --test_env=MINDCLADE_REQUIRE_POSTGRES_INTEGRATION=1 \
      //:all_contract_tests \
      "${postgres_targets[@]}" \
      //tests:artifact_commit_integration_test \
      //tests:control_worker_integration_test \
      //tests:local_stack_integration_test

# Recreate an empty database, rehearse every migration down/up, and run the
# complete contract/runtime suite with PostgreSQL integration made mandatory.
integration-ci:
    #!/usr/bin/env bash
    set -euo pipefail
    compose=(docker compose -f deploy/local/compose.yaml)
    "${compose[@]}" down --volumes --remove-orphans
    trap 'docker compose -f deploy/local/compose.yaml down --volumes --remove-orphans' EXIT
    just integration-up
    just integration-test
    source_revision="${MINDCLADE_SOURCE_REVISION:-$(git rev-parse HEAD)}"
    [[ "${source_revision}" =~ ^[0-9a-f]{40}$ ]]
    mkdir -p {{ evidence_dir }}
    {{ uv }} run python tools/qualification/training_rehearsal.py \
      --root . \
      --source-revision "${source_revision}" \
      --passed-check cross_language=//:all_contract_tests \
      --passed-check database=//services/control_plane:control_plane_test \
      --passed-check event=//services/control_plane/internal/platform/eventprojection:event_projection_test \
      --passed-check gateway=//services/control_plane:control_plane_grpc_registration_test \
      --passed-check grpc=//services/control_plane:control_plane_grpc_registration_test \
      --passed-check sdk=//:all_contract_tests \
      --integration-output {{ evidence_dir }}/integration-ci.v1.json \
      --output {{ evidence_dir }}/training-vertical-rehearsal.v1.json
    {{ uv }} run python tools/qualification/readiness_report.py \
      --root . \
      --plan docs/architecture/authoritative-contract-integration-plan.md \
      --criterion-map tools/qualification/authoritative-integration-criteria.v1.json \
      --rehearsal {{ evidence_dir }}/training-vertical-rehearsal.v1.json \
      --expected-source-revision "${source_revision}" \
      --output {{ evidence_dir }}/authoritative-integration-readiness.v2.json

integration-down:
    docker compose -f deploy/local/compose.yaml down --volumes --remove-orphans
