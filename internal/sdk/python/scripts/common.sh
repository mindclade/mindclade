#!/usr/bin/env bash
# shellcheck shell=bash
#
# Shared preamble for the internal Python SDK packaging scripts. This file is
# sourced, never executed.
#
# Every script in this directory is a thin, auditable wrapper around a command
# the repository already runs for this package. The scripts do not reimplement
# build, lint, format, or test policy; they narrow the repository-wide `just`
# recipes to the one package a Python SDK contributor works in, so joining the
# package needs a directory listing rather than a reading of the root justfile.
#
# `just format`, `just lint`, and `just test-python` remain the repository-wide
# authority. When a wrapper and a recipe disagree, the recipe is right and the
# wrapper is the bug.

# The package this directory packages, its interpreter search path, and its
# Bazel equivalents.
SDK_PACKAGE_DIR="internal/sdk/python"
SDK_TEST_DIR="internal/sdk/python/tests"
SDK_PYTHONPATH="internal/sdk/python:protocols/generated/python"
SDK_PYRIGHT_PROJECT="internal/sdk/python/pyproject.toml"
SDK_BAZEL_LIBRARY="//internal/sdk/python:mindclade_internal_sdk"
SDK_BAZEL_TEST="//internal/sdk/python:tests"
readonly SDK_PACKAGE_DIR SDK_TEST_DIR SDK_PYTHONPATH SDK_PYRIGHT_PROJECT
readonly SDK_BAZEL_LIBRARY SDK_BAZEL_TEST

# repository_root prints the repository root, so a script behaves identically
# whatever directory it is invoked from. It ascends from this file's own
# location to the directory that owns the workspace and the task runner, rather
# than trusting the caller's shell state, git, or a hard-coded depth.
repository_root() {
  local directory
  directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  while [[ "${directory}" != "/" ]]; do
    if [[ -f "${directory}/pyproject.toml" && -f "${directory}/justfile" ]]; then
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

# uv_run runs a command inside the repository's pinned virtual environment.
# `uv` owns the environment for the whole repository, so the wrappers borrow it
# rather than resolving an interpreter of their own.
uv_run() {
  require_tool "${UV:-uv}" \
    "install uv; see docs/development or run 'nix develop'."
  announce "${UV:-uv} run $*"
  "${UV:-uv}" run "$@"
}
