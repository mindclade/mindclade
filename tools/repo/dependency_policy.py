#!/usr/bin/env python3.12
"""Validate the typed, acyclic Mindclade component dependency graph."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

EDGE_KINDS = {
    "compile-api",
    "runtime",
    "protocol",
    "data-artifact",
    "tool-codegen",
    "test-only",
    "deployment",
    "operational",
}
VISIBILITIES = {"private", "component", "repository", "public"}
ACYCLIC_KINDS = {"compile-api", "protocol", "data-artifact", "tool-codegen", "deployment"}
LAYER_ORDER = {
    "protocols": 0,
    "libs": 1,
    "bio": 2,
    "data": 3,
    "runtime": 3,
    "kernels": 4,
    "models": 5,
    "training": 6,
    "evaluation": 6,
    "inference": 6,
    "agents": 7,
    "services": 8,
    "workers": 8,
    "sdk": 9,
    "kits": 9,
    "apps": 10,
    "examples": 11,
}


def _cycle(nodes: set[str], edges: list[tuple[str, str]]) -> list[str] | None:
    graph: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        graph[source].append(target)
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            start = stack.index(node)
            return [*stack[start:], node]
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for target in sorted(graph[node]):
            found = visit(target)
            if found:
                return found
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(nodes):
        found = visit(node)
        if found:
            return found
    return None


def validate_dependency_graph(
    components: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    identities = {str(component.get("name")) for component in components}
    edges: list[dict[str, Any]] = []
    for component in components:
        source = str(component.get("name", ""))
        source_path = str(component.get("path", ""))
        source_layer = source_path.split("/", 1)[0]
        dependencies = component.get("dependencies", [])
        if not isinstance(dependencies, Sequence) or isinstance(dependencies, (str, bytes)):
            errors.append(f"{source}: dependencies must be an array")
            continue
        for dependency in cast(Sequence[object], dependencies):
            if not isinstance(dependency, Mapping):
                errors.append(f"{source}: dependency must be an object")
                continue
            dependency = cast(Mapping[str, Any], dependency)
            edge: dict[str, Any] = {
                "source": source,
                "target": str(dependency.get("component", "")),
                "kind": str(dependency.get("kind", "")),
                "visibility": str(dependency.get("visibility", "")),
                "owner": str(dependency.get("owner", component.get("owner", ""))),
                "justification": str(dependency.get("justification", "")),
                "scope": str(dependency.get("scope", "normal")),
                "exception": dependency.get("exception"),
            }
            edges.append(edge)
            if edge["target"] not in identities:
                errors.append(f"{source}: unknown dependency {edge['target']!r}")
            if edge["kind"] not in EDGE_KINDS:
                errors.append(f"{source} -> {edge['target']}: invalid edge kind {edge['kind']!r}")
            if edge["visibility"] not in VISIBILITIES:
                errors.append(f"{source} -> {edge['target']}: invalid visibility")
            if not edge["owner"] or not edge["justification"] or not edge["scope"]:
                errors.append(f"{source} -> {edge['target']}: edge lacks owner/justification/scope")
            target_component = next(
                (candidate for candidate in components if candidate.get("name") == edge["target"]),
                None,
            )
            if target_component and edge["kind"] == "compile-api" and not edge["exception"]:
                target_layer = str(target_component.get("path", "")).split("/", 1)[0]
                if LAYER_ORDER.get(source_layer, -1) < LAYER_ORDER.get(target_layer, -1):
                    errors.append(
                        f"{source} -> {edge['target']}: compile edge points backward "
                        f"({source_layer} -> {target_layer})"
                    )
    cyclic_edges = [
        (edge["source"], edge["target"])
        for edge in edges
        if edge["kind"] in ACYCLIC_KINDS and not edge["exception"]
    ]
    cycle = _cycle(identities, cyclic_edges)
    if cycle:
        errors.append("dependency cycle: " + " -> ".join(cycle))
    return errors, sorted(edges, key=lambda edge: (edge["source"], edge["target"], edge["kind"]))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path, help="JSON object containing a components array")
    args = parser.parse_args(argv)
    value = json.loads(args.graph.read_text(encoding="utf-8"))
    errors, edges = validate_dependency_graph(value.get("components", []))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"edges": edges}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
