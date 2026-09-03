#!/usr/bin/env bash
# shellcheck shell=bash
#
# Shared preamble for the internal Go SDK packaging scripts. This file is
# sourced, never executed.
#
# Every script in this directory is a thin, auditable wrapper around a command
# the repository already runs for this package. The scripts do not reimplement
# build, lint, or test policy; they narrow the repository-wide `just` recipes to
# the one package a Go SDK contributor works in, so joining the package needs a
# directory listing rather than a reading of the root justfile.
#
# Two toolchains are supported, and which one runs is declared rather than
# guessed: the native Go toolchain runs by default because it is what a
# contributor iterates with, and Bazel — the authority CI uses — runs as well
# when MINDCLADE_BAZEL=1 is set.

# The Go package this directory packages, and its Bazel equivalents.
SDK_GO_PACKAGE="./sdks/go/mindclade"
SDK_GO_PATTERN="./sdks/go/..."
SDK_BAZEL_LIBRARY="//sdks/go/mindclade:mindclade"
SDK_BAZEL_TEST="//sdks/go/mindclade:mindclade_test"
readonly SDK_GO_PACKAGE SDK_GO_PATTERN SDK_BAZEL_LIBRARY SDK_BAZEL_TEST

# repository_root prints the repository root, so a script behaves identically
# whatever directory it is invoked from. It ascends from this file's own
# location to the directory that owns the repository module and task runner,
# rather than trusting the caller's shell state, git, or a hard-coded depth.
repository_root() {
  local directory
  directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  while [[ "${directory}" != "/" ]]; do
    if [[ -f "${directory}/go.mod" && -f "${directory}/justfile" ]]; then
      printf '%s\n' "${directory}"
      return 0
    fi
    directory="$(dirname -- "${directory}")"
  done
  printf 'error: could not locate the repository root above %s.\n' "${BASH_SOURCE[0]}" >&2
  return 1
}

# announce names the command a script is about to run. A packaging script that
# hides what it delegates to cannot be audited.
announce() {
  printf '==> %s\n' "$*" >&2
}

# require_tool fails with a specific, actionable message when a declared tool is
# absent, instead of letting the shell report a bare "command not found".
require_tool() {
  local tool="$1"
  local remedy="$2"
  if ! command -v "${tool}" >/dev/null 2>&1; then
    printf 'error: %s is required but is not on PATH.\n' "${tool}" >&2
    printf 'remedy: %s\n' "${remedy}" >&2
    return 1
  fi
}

# bazel_requested reports whether the caller opted into the Bazel authority.
bazel_requested() {
  [[ "${MINDCLADE_BAZEL:-0}" == "1" ]]
}
