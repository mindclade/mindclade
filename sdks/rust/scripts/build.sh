#!/bin/sh
# Build the internal Rust SDK.
#
# This crate is never published: `Cargo.toml` sets `publish = false` and
# consumers depend on it by path from a source revision of this monorepo.
# "Build" is therefore the check that the crate and its test targets compile
# against the committed lockfile and the generated bindings of the same
# revision.
#
# MINDCLADE_BAZEL=1 additionally builds the Bazel library target, which is the
# authority CI uses.
#
# Arguments are forwarded to cargo, so `scripts/build --release` works.

set -eu

. "$(dirname -- "$0")/common.sh"

cargo_run build --package "${SDK_CARGO_PACKAGE}" --all-targets --locked "$@"

if bazel_requested; then
  require_tool bazel "install Bazelisk, or unset MINDCLADE_BAZEL to use the native toolchain."
  announce "bazel build ${SDK_BAZEL_LIBRARY}"
  bazel build "${SDK_BAZEL_LIBRARY}"
fi
