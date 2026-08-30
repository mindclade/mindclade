set dotenv-load := false
set export := false
set shell := ["bash", "-euo", "pipefail", "-c"]

uv := env_var_or_default("UV", "uv")
python := env_var_or_default("PYTHON", "python3.12")
bazel := env_var_or_default("BAZEL", "bazel") + " --nohome_rc --noworkspace_rc --output_user_root=" + justfile_directory() + "/build/bazel-user-root --bazelrc=" + justfile_directory() + "/.bazelrc"
manifest := "docs/architecture/repository-path-manifest.yaml"
component_schema := "tools/repo/component.schema.json"
evidence_dir := "build/evidence"

default:
    @just --list

# Verify the exact local tools and generated dependency locks.
bootstrap:
    {{ python }} tools/dev/bootstrap.py --root .

# Run non-connected environment diagnostics.
doctor:
    {{ python }} tools/dev/doctor.py --root .

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
    organization_workflows_revision="${MINDCLADE_ORGANIZATION_WORKFLOWS_REFERENCE_REVISION:-6399abc50c4678d0dff7f33bbd7f6868043ef736}"
    github_config_revision="${MINDCLADE_GITHUB_CONFIG_REFERENCE_REVISION:-8cdf1f256c0d9310c825fd05ab068295488070a6}"
    bootstrap_revision="${MINDCLADE_BOOTSTRAP_REFERENCE_REVISION:-620d17fcd589cdeb8cef7c292f47e2b7be3b4987}"
    infrastructure_live_revision="${MINDCLADE_INFRASTRUCTURE_LIVE_REFERENCE_REVISION:-c6eded5a2dafd47d62eb587f76d21bb17a9343f0}"
    gitops_revision="${MINDCLADE_GITOPS_REFERENCE_REVISION:-a74d7447b05fca142d54a09504f4d0a9050b9e73}"
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

# Regenerate only declared architecture outputs; review the resulting diff.
generate:
    {{ python }} tools/repo/render_repository_tree.py \
      --manifest {{ manifest }} \
      --appendix-a6 docs/architecture/blueprint/appendices/A06-authoritative-repository-tree.md \
      --write
    {{ python }} tools/docs/render_architecture_blueprint.py --manifest docs/architecture/blueprint/manifest.yaml

# Execute all local source, lock, policy, and documentation gates.
check: bootstrap
    {{ uv }} lock --check
    cargo metadata --locked --no-deps --format-version=1 >/dev/null
    go list -mod=readonly -m >/dev/null
    pnpm install --lockfile-only --frozen-lockfile --offline --ignore-scripts
    pnpm run check
    buf config ls-modules >/dev/null
    buf config ls-lint-rules >/dev/null
    buf config ls-breaking-rules >/dev/null
    if [[ -d protocols ]] && [[ -n "$(find protocols -type f -name '*.proto' -print -quit)" ]]; then buf lint; fi
    ruff check .buildkite tools
    ruff format --check .buildkite tools
    pyright .buildkite tools
    actionlint -no-color
    yamllint -c .yamllint.yaml .
    nix flake check path:. --no-build
    just docs
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
    {{ bazel }} test --config=ci "${targets[@]}"
    mkdir -p {{ evidence_dir }}
    printf '%s\n' '{"conclusion":"PASS","schema_version":"bazel-native-agreement.v1"}' > \
      {{ evidence_dir }}/bazel-native-agreement.v1.json

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
      {{ bazel }} test --config=ci "${targets[@]}"
    fi
    printf '%s\n' '{"conclusion":"PASS","schema_version":"bazel-native-agreement.v1"}' > \
      {{ evidence_dir }}/bazel-native-agreement.v1.json

# Wave 0 has no active product domain.
test-domain domain:
    @echo "Domain '{{ domain }}' is not active in Wave 0" >&2
    @exit 78

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
    just security

# Buildkite protected full-CPU entrypoint.
ci-nightly:
    just check
    just governance-ci
    {{ bazel }} test --config=ci //...
    mkdir -p {{ evidence_dir }}
    printf '%s\n' '{"conclusion":"PASS","schema_version":"bazel-native-agreement.v1"}' > \
      {{ evidence_dir }}/bazel-native-agreement.v1.json

# Resolve the exact changed set and target/gate plan before Buildkite executes it.
ci-plan:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${MINDCLADE_SOURCE_REVISION:?missing source revision}"
    : "${MINDCLADE_PIPELINE_DEFINITION_REVISION:?missing pipeline definition revision}"
    : "${MINDCLADE_PIPELINE_CLASS:?missing pipeline class}"
    : "${MINDCLADE_CONTEXT_JSON:?missing trusted context JSON}"
    : "${MINDCLADE_CONTEXT_DIGEST:?missing trusted context digest}"
    base_arguments=()
    if [[ -n "${MINDCLADE_BASE_REVISION:-}" ]]; then
      base_arguments=(--base "${MINDCLADE_BASE_REVISION}")
    fi
    mkdir -p {{ evidence_dir }}
    printf '%s\n' "${MINDCLADE_CONTEXT_JSON}" > {{ evidence_dir }}/trusted-context.v1.json
    {{ python }} tools/ci/pipeline_plan.py \
      --source-revision "${MINDCLADE_SOURCE_REVISION}" \
      --pipeline-definition-revision "${MINDCLADE_PIPELINE_DEFINITION_REVISION}" \
      --pipeline-class "${MINDCLADE_PIPELINE_CLASS}" \
      --root . \
      "${base_arguments[@]}" \
      --head "${MINDCLADE_SOURCE_REVISION}" \
      --output {{ evidence_dir }}/pipeline-plan.v1.json

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
      "repository-governance={{ evidence_dir }}/repository_drift.v1.json" \
      "dependency-and-license-policy={{ evidence_dir }}/license-inventory.v1.json" \
      "secret-scan={{ evidence_dir }}/secret-scan.v1.json" \
      "bazel-native-agreement={{ evidence_dir }}/bazel-native-agreement.v1.json"; do
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

ci-gpu: (require-activation "gpu")

ci-release: (require-activation "release")

qualify target:
    @echo "Qualification target '{{ target }}' is not active in Wave 0" >&2
    @exit 78

package target:
    @echo "Release target '{{ target }}' is not active in Wave 0" >&2
    @exit 78

integration-up:
    @echo "Local integration services are deferred until the Wave 1 kernel" >&2
    @exit 78

integration-test:
    @echo "Integration tests are deferred until the Wave 1 kernel" >&2
    @exit 78
