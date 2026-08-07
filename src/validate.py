"""
Validate a snapshotted planning graph.

Three layers:
  1. structural - is the graph shaped the way you think it is?
  2. paths      - enumerate every route a client could take, and flag any
                  route that is not on the approved list
  3. scenario   - do known client profiles produce the expected step sequence?

Usage:
    python validate.py snapshots/20260806T142301Z/graph.graphml expectations.yaml

Writes paths.json and validation.json into the snapshot directory.
Exit code 0 = all checks passed, 1 = something failed. Safe to run in CI.
"""

import json
import sys
from pathlib import Path

import networkx as nx
import yaml

REQUIRED_NODE_ATTRS = ("rationale", "source_doc")
REQUIRED_EDGE_ATTRS = ("condition_key", "condition_value")

# A combinatorial graph can have astronomically many simple paths. If we blow
# past this, the graph is too branchy to review path-by-path and you should
# know that rather than wait for the script to finish.
MAX_PATHS = 5000


# --------------------------------------------------------------------------
# 1. structural checks
# --------------------------------------------------------------------------

def check_structure(graph, expected_entries, expected_terminals):
    """Return a list of failure strings. Empty list means the graph is sound."""
    failures = []

    # A recommendation flow should never loop back on itself.
    if not nx.is_directed_acyclic_graph(graph):
        failures.append(f"graph contains a cycle: {nx.find_cycle(graph)}")

    # Entry points are the steps nothing leads to.
    entries = {n for n, d in graph.in_degree() if d == 0}
    if entries != set(expected_entries):
        failures.append(
            f"entry points changed: expected {sorted(expected_entries)}, "
            f"found {sorted(entries)}"
        )

    # Every step must be reachable from some entry point.
    reachable = set(entries)
    for entry in entries:
        reachable |= nx.descendants(graph, entry)
    orphans = set(graph) - reachable
    if orphans:
        failures.append(f"unreachable steps: {sorted(orphans)}")

    # Dead ends must be intentional endpoints, not accidents.
    terminals = {n for n, d in graph.out_degree() if d == 0}
    unexpected = terminals - set(expected_terminals)
    if unexpected:
        failures.append(f"unexpected dead ends: {sorted(unexpected)}")

    # Every step carries its justification.
    for node, data in graph.nodes(data=True):
        missing = [a for a in REQUIRED_NODE_ATTRS if not data.get(a)]
        if missing:
            failures.append(f"node {node!r} missing {missing}")

    # Every transition states the condition under which it is taken.
    for src, dst, data in graph.edges(data=True):
        missing = [a for a in REQUIRED_EDGE_ATTRS if a not in data]
        if missing:
            failures.append(f"edge {src!r} -> {dst!r} missing {missing}")

    return failures


# --------------------------------------------------------------------------
# 2. path enumeration
# --------------------------------------------------------------------------

def enumerate_paths(graph, entries, terminals):
    """Every simple route from an entry point to an endpoint, sorted for diffing."""
    paths = []
    for entry in sorted(entries):
        for terminal in sorted(terminals):
            if entry == terminal or not nx.has_path(graph, entry, terminal):
                continue
            for path in nx.all_simple_paths(graph, entry, terminal):
                paths.append(path)
                if len(paths) > MAX_PATHS:
                    raise ValueError(
                        f"more than {MAX_PATHS} distinct client journeys; "
                        "the graph is too branchy to review path-by-path"
                    )
    return sorted(paths)


def check_paths(actual, approved):
    """Flag journeys nobody signed off on, and signed-off journeys that vanished."""
    failures = []
    actual_set = {tuple(p) for p in actual}
    approved_set = {tuple(p) for p in approved}

    for path in sorted(actual_set - approved_set):
        failures.append(f"unapproved client journey: {list(path)}")
    for path in sorted(approved_set - actual_set):
        failures.append(f"approved journey no longer possible: {list(path)}")

    return failures


# --------------------------------------------------------------------------
# 3. scenario checks
# --------------------------------------------------------------------------

def edge_allowed(profile, data):
    """
    Conditions are stored as a key/value pair, not as an expression string,
    so this is a plain lookup. Never eval() a condition pulled from a database.
    """
    return profile.get(data["condition_key"]) == data["condition_value"]


def walk(graph, start, profile):
    """Follow the one edge whose condition the profile satisfies, until we stop."""
    path = [start]
    node = start

    while True:
        options = [
            dst for _, dst, data in graph.out_edges(node, data=True)
            if edge_allowed(profile, data)
        ]
        if not options:
            return path
        if len(options) > 1:
            raise ValueError(f"ambiguous branch at {node!r}: {sorted(options)}")

        node = options[0]
        path.append(node)


def check_scenarios(graph, scenarios):
    failures = []
    for case in scenarios:
        name = case["name"]
        try:
            actual = walk(graph, case["start"], case["profile"])
        except ValueError as exc:
            failures.append(f"scenario {name!r}: {exc}")
            continue
        if actual != case["expected_path"]:
            failures.append(
                f"scenario {name!r}: expected {case['expected_path']}, got {actual}"
            )
    return failures


# --------------------------------------------------------------------------

def main():
    graphml_path, expectations_path = Path(sys.argv[1]), Path(sys.argv[2])
    outdir = graphml_path.parent

    graph = nx.read_graphml(graphml_path)
    config = yaml.safe_load(expectations_path.read_text())

    entries = config["expected_entries"]
    terminals = config["expected_terminals"]

    failures = check_structure(graph, entries, terminals)

    # Only enumerate paths if the graph is acyclic; otherwise it never terminates.
    paths = []
    if nx.is_directed_acyclic_graph(graph):
        try:
            paths = enumerate_paths(graph, entries, terminals)
            (outdir / "paths.json").write_text(json.dumps(paths, indent=2) + "\n")
            failures += check_paths(paths, config.get("approved_paths", []))
        except ValueError as exc:
            failures.append(str(exc))

    failures += check_scenarios(graph, config["scenarios"])

    report = {
        "graphml": str(graphml_path),
        "passed": not failures,
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "path_count": len(paths),
        "failures": failures,
    }
    (outdir / "validation.json").write_text(json.dumps(report, indent=2) + "\n")

    if failures:
        print(f"FAILED ({len(failures)} problems)\n")
        for line in failures:
            print(f"  - {line}")
        sys.exit(1)

    print(
        f"PASSED - {graph.number_of_nodes()} nodes, "
        f"{graph.number_of_edges()} edges, {len(paths)} client journeys"
    )


if __name__ == "__main__":
    main()
