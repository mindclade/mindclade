#!/usr/bin/env bash
# Build the internal Go SDK.
#
# The native build compiles the package and its tests without running them, so
# a compile break in test-only code is caught here rather than in `scripts/test`.
# MINDCLADE_BAZEL=1 additionally builds the Bazel library target, which is the
# authority CI uses.

set -euo pipefail

# shellcheck source=sdks/go/mindclade/scripts/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cd -- "$(repository_root)"

require_tool go "install the pinned Go toolchain; see docs/development or run 'nix develop'."

announce "go build ${SDK_GO_PATTERN}"
go build "${SDK_GO_PATTERN}"

# `go vet` type-checks the test files too, so it is the compile gate for the
# whole package rather than for its non-test half.
announce "go vet ${SDK_GO_PATTERN}"
go vet "${SDK_GO_PATTERN}"

if bazel_requested; then
  require_tool bazel "install Bazelisk, or unset MINDCLADE_BAZEL to use the native toolchain."
  announce "bazel build ${SDK_BAZEL_LIBRARY}"
  bazel build "${SDK_BAZEL_LIBRARY}"
fi
