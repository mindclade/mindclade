#!/usr/bin/env python3.12
"""Resolve Bazel target source membership by reading BUILD files.

`verify_repository_path_manifest.py` proves two things about every target a
governed path declares: that the target exists, and that the target actually
contains the path. The first was always textual. The second shelled out to
`bazel query`, so wherever Bazel could not run -- an offline checkout, a
sandbox that cannot reach `releases.bazel.build` -- the membership half was
skipped and a path could claim a target that did not contain it.

This reads the BUILD files instead. That is only defensible because this
estate's Starlark is small: across 105 BUILD files there is not one `select()`
and not one list comprehension, no macro expands to more than one target, and
every `test_suite` names its members explicitly. The grammar that remains is
string literals, lists, `glob()`, module-level string-list variables, and `+`
between them.

The evaluator is built on `ast` rather than regular expressions because the
subset of Starlark used here is also valid Python, and because an unmodelled
construct then arrives as an unhandled node type rather than as a silently
wrong answer. Every such node raises `BuildGraphError`.

That strictness is the point. A membership checker that quietly under-reports
is worse than none at all: it converts a gate that is visibly skipped into one
that is invisibly green.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

BUILD_FILE_NAME = "BUILD.bazel"

# The attributes through which a file can belong to a target. This is the same
# list the Bazel query used, so the two definitions of "membership" agree.
MEMBERSHIP_ATTRIBUTES = (
    "srcs",
    "hdrs",
    "textual_hdrs",
    "tests",
    "data",
    "deps",
    "runtime_deps",
    "exports",
    "actual",
    "embed",
)

# Directories Bazel itself is told to ignore. The entries in .bazelignore are
# repository-root-relative paths, not bare names, and the distinction matters:
# the root `build/` holds Bazel's own install cache (62 further BUILD files of
# embedded_tools), while `internal/sdk/python/scripts/build` is an ordinary
# governed file that happens to share the name. Matching by name alone silently
# drops it from its own package.
IGNORED_ROOTS = frozenset({".direnv", ".git", "build", "node_modules", "result", "target"})

# Names ignored at any depth, because they appear throughout the tree.
IGNORED_NAMES = frozenset({"node_modules", "__pycache__", ".git"})

# Calls that appear at the top level of a BUILD file and declare no target.
NON_TARGET_CALLS = frozenset({"load", "package", "licenses", "exports_files"})


class BuildGraphError(Exception):
    """A BUILD file used a construct this reader does not model."""


@dataclass(frozen=True, slots=True)
class Target:
    package: str
    name: str
    rule: str
    attributes: Mapping[str, tuple[str, ...]]

    @property
    def label(self) -> str:
        return f"//{self.package}:{self.name}"


def _translate(pattern: str) -> str:
    """Turn one Bazel glob pattern into a regular expression over a relative path."""

    segments = pattern.split("/")
    pieces: list[str] = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            # A trailing `**` must match at least one segment; an interior one
            # may match none, so `a/**/b` covers `a/b`.
            pieces.append(r"[^/]+(?:/[^/]+)*" if last else r"(?:[^/]+/)*")
            continue
        literal = "".join(
            "[^/]*" if character == "*" else re.escape(character) for character in segment
        )
        pieces.append(literal if last else literal + "/")
    return "".join(pieces)


def _matcher(patterns: tuple[str, ...]) -> re.Pattern[str]:
    if not patterns:
        return re.compile(r"(?!)")
    return re.compile("|".join(f"(?:{_translate(pattern)})" for pattern in patterns) + r"\Z")


def _package_files(root: Path, package: str) -> tuple[str, ...]:
    """Every file in a package, stopping at sub-package boundaries.

    A directory holding its own BUILD.bazel belongs to that package, not this
    one, so a glob here must not reach into it. Getting this wrong is how a
    textual reader claims a target owns files that Bazel assigns elsewhere.
    """

    base = root / package if package else root
    found: list[str] = []

    def walk(directory: Path, prefix: str) -> None:
        for entry in sorted(directory.iterdir()):
            relative = f"{prefix}{entry.name}"
            if entry.is_symlink():
                continue
            if entry.is_file():
                found.append(relative)
                continue
            if not entry.is_dir():
                continue
            if entry.name in IGNORED_NAMES:
                continue
            repository_relative = f"{package}/{relative}" if package else relative
            if repository_relative in IGNORED_ROOTS:
                continue
            if (entry / BUILD_FILE_NAME).is_file():
                continue
            walk(entry, f"{relative}/")

    if base.is_dir():
        walk(base, "")
    return tuple(found)


class _Evaluator:
    """Evaluate the expression subset a BUILD attribute may use."""

    def __init__(self, root: Path, package: str, variables: Mapping[str, tuple[str, ...]]) -> None:
        self._root = root
        self._package = package
        self._variables = variables

    def evaluate(self, node: ast.expr) -> tuple[str, ...]:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return (node.value,)
            raise BuildGraphError(f"non-string constant in an attribute: {node.value!r}")
        if isinstance(node, ast.List | ast.Tuple):
            return tuple(item for element in node.elts for item in self.evaluate(element))
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, ast.Add):
                raise BuildGraphError("only `+` may join attribute values")
            return self.evaluate(node.left) + self.evaluate(node.right)
        if isinstance(node, ast.Name):
            if node.id not in self._variables:
                raise BuildGraphError(f"attribute reads an undefined variable: {node.id}")
            return self._variables[node.id]
        if isinstance(node, ast.Call):
            return self._call(node)
        raise BuildGraphError(f"unsupported expression in a BUILD attribute: {type(node).__name__}")

    def _call(self, node: ast.Call) -> tuple[str, ...]:
        if not isinstance(node.func, ast.Name) or node.func.id != "glob":
            name = node.func.id if isinstance(node.func, ast.Name) else "<expression>"
            raise BuildGraphError(f"unsupported call in a BUILD attribute: {name}")
        include: tuple[str, ...] = ()
        exclude: tuple[str, ...] = ()
        if node.args:
            include = self.evaluate(node.args[0])
        for keyword in node.keywords:
            if keyword.arg == "include":
                include = self.evaluate(keyword.value)
            elif keyword.arg == "exclude":
                exclude = self.evaluate(keyword.value)
            elif keyword.arg in {"allow_empty", "exclude_directories"}:
                continue
            else:
                raise BuildGraphError(f"unsupported glob keyword: {keyword.arg}")
        included = _matcher(include)
        excluded = _matcher(exclude)
        return tuple(
            candidate
            for candidate in _package_files(self._root, self._package)
            if included.match(candidate) and not excluded.match(candidate)
        )


def _parse_package(root: Path, package: str) -> dict[str, Target]:
    build_file = (root / package / BUILD_FILE_NAME) if package else (root / BUILD_FILE_NAME)
    if not build_file.is_file():
        raise BuildGraphError(f"package has no {BUILD_FILE_NAME}: //{package}")
    try:
        module = ast.parse(build_file.read_text(encoding="utf-8"), filename=str(build_file))
    except SyntaxError as error:  # pragma: no cover - a malformed BUILD file
        raise BuildGraphError(f"{build_file} is not parseable: {error}") from error

    variables: dict[str, tuple[str, ...]] = {}
    targets: dict[str, Target] = {}
    evaluator = _Evaluator(root, package, variables)

    for statement in module.body:
        if isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                raise BuildGraphError(f"{build_file}: unsupported assignment target")
            variables[statement.targets[0].id] = evaluator.evaluate(statement.value)
            continue
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise BuildGraphError(
                f"{build_file}: unsupported top-level statement {type(statement).__name__}"
            )
        call = statement.value
        if not isinstance(call.func, ast.Name):
            raise BuildGraphError(f"{build_file}: unsupported top-level call")
        rule = call.func.id
        if rule in NON_TARGET_CALLS:
            continue
        attributes: dict[str, tuple[str, ...]] = {}
        name: str | None = None
        for keyword in call.keywords:
            if keyword.arg == "name":
                name = ast.literal_eval(keyword.value)
                continue
            if keyword.arg not in MEMBERSHIP_ATTRIBUTES:
                continue
            attributes[keyword.arg] = evaluator.evaluate(keyword.value)
        if name is None:
            raise BuildGraphError(f"{build_file}: {rule} declares no name")
        targets[name] = Target(package, name, rule, attributes)
    return targets


class BuildGraph:
    """A lazily loaded index of every package this reader has been asked about."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._packages: dict[str, dict[str, Target]] = {}

    def package(self, package: str) -> dict[str, Target]:
        if package not in self._packages:
            self._packages[package] = _parse_package(self._root, package)
        return self._packages[package]

    def target(self, label: str) -> Target:
        package, _, name = label[2:].partition(":")
        targets = self.package(package)
        if name not in targets:
            raise BuildGraphError(f"no such target: {label}")
        return targets[name]

    def sources(self, label: str) -> set[str]:
        """Every repository file reachable from `label` through membership attributes.

        A label whose package/name pair is a file on disk is a source; anything
        else is another target to walk. That is the same rule the Bazel query
        applied to its output, so the two produce the same set.
        """

        sources: set[str] = set()
        visited: set[str] = set()
        pending = [label]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            target = self.target(current)
            for attribute in MEMBERSHIP_ATTRIBUTES:
                for value in target.attributes.get(attribute, ()):
                    resolved = _canonical_label(target.package, value)
                    if resolved is None:
                        continue
                    package, name = _package_and_name(resolved)
                    path = f"{package}/{name}" if package else name
                    if (self._root / path).is_file():
                        sources.add(path)
                    elif resolved not in visited:
                        pending.append(resolved)
        return sources


def _canonical_label(package: str, value: str) -> str | None:
    """Normalise one attribute value to `//package:name`, or None if external.

    External repositories are terminal here exactly as they were under the
    Bazel query, which skipped every label beginning with `@`. Their contents
    are not repository paths, so they can never satisfy a manifest entry.
    """

    if value.startswith("@"):
        return None
    # npm_link_all_packages synthesises one `:node_modules/<package>` label per
    # npm dependency. They name packages inside node_modules, never repository
    # paths, so they are terminal exactly as `@external` labels are.
    if ":node_modules/" in value:
        return None
    if value.startswith("//"):
        body = value[2:]
        if ":" in body:
            return f"//{body}"
        return f"//{body}:{body.rpartition('/')[2]}"
    if value.startswith(":"):
        return f"//{package}:{value[1:]}"
    return f"//{package}:{value}" if package else f"//:{value}"


def _package_and_name(label: str) -> tuple[str, str]:
    package, _, name = label[2:].partition(":")
    return package, name


def target_sources(root: Path, label: str) -> tuple[set[str], str | None]:
    """Drop-in replacement for the Bazel-backed membership query.

    Returns the same `(sources, failure_detail)` shape the caller already
    handles, so a construct this reader does not model surfaces as the same
    kind of reported error a Bazel failure did -- never as an empty set, which
    would read as "this target contains nothing" and pass every check below it.
    """

    try:
        return BuildGraph(root).sources(label), None
    except BuildGraphError as error:
        return set(), str(error)
