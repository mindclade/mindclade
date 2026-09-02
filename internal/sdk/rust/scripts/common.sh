#!/bin/sh
# shellcheck shell=sh
#
# Shared preamble for the internal Rust SDK packaging scripts. This file is
# sourced, never executed.
#
# Every script in this directory is a thin, auditable wrapper around a command
# the repository already runs for this crate. The scripts do not reimplement
# build, lint, format, or test policy; they narrow the repository-wide `just`
# recipes to the one crate a Rust SDK contributor works in, so joining the crate
# needs a directory listing rather than a reading of the root justfile.
#
# `just format`, `just lint`, and `just check` remain the repository-wide
# authority. When a wrapper and a recipe disagree, the recipe is right and the
# wrapper is the bug.

# The crate this directory packages, and its Bazel equivalents.
SDK_PACKAGE_DIR="internal/sdk/rust"
SDK_CARGO_PACKAGE="mindclade-internal-sdk"
SDK_BAZEL_LIBRARY="//internal/sdk/rust:mindclade_internal_sdk"
SDK_BAZEL_TEST="//internal/sdk/rust:mindclade_internal_sdk_test"
CARGO="${CARGO:-cargo}"

# announce names the command a script is about to run. A packaging script that
# hides what it delegates to cannot be audited.
announce() {
  printf '==> %s\n' "$*" >&2
}

# require_tool fails with a specific, actionable message when a declared tool is
# absent, instead of letting the shell report a bare "command not found".
require_tool() {
  if command -v "$1" >/dev/null 2>&1; then
    return 0
  fi
  printf 'error: %s is required but is not on PATH.\n' "$1" >&2
  printf 'remedy: %s\n' "$2" >&2
  return 1
}

# bazel_requested reports whether the caller opted into the Bazel authority,
# which is what CI runs. The native cargo path is the default because it is the
# one a contributor iterates in.
bazel_requested() {
  [ "${MINDCLADE_BAZEL:-0}" = "1" ]
}

# cargo_run runs one cargo subcommand. Callers pass `--locked` where a lockfile
# is consulted: a wrapper that silently re-resolved dependencies would turn a
# governance change into a developer convenience.
cargo_run() {
  require_tool "${CARGO}" \
    "install the pinned Rust toolchain; see docs/development or run 'nix develop'."
  announce "${CARGO} $*"
  "${CARGO}" "$@"
}

# repository_root prints the repository root, so a script behaves identically
# whatever directory it is invoked from. It ascends from the invoked script's
# own location to the directory that owns the Cargo workspace and the task
# runner, rather than trusting the caller's shell state, git, or a hard-coded
# depth.
repository_root() {
  directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
  while [ "${directory}" != "/" ]; do
    if [ -f "${directory}/Cargo.toml" ] && [ -f "${directory}/justfile" ]; then
      printf '%s\n' "${directory}"
      return 0
    fi
    directory=$(dirname -- "${directory}")
  done
  printf 'error: could not locate the repository root above %s.\n' "$0" >&2
  return 1
}

CDPATH='' cd -- "$(repository_root)"
