"""
Validate a snapshotted planning graph.

The graph holds two kinds of node: Task (a client-facing step) and
CriteriaNode (a branch point). A conditional transition is
task -CRITERIA_BRANCH-> criteria node -HAS_CHILD-> task, with the
condition_key/condition_value living on the CRITERIA_BRANCH edge; an
unconditional transition is a direct task -HAS_CHILD-> task edge.

Four layers:
  1. structural - is the graph shaped the way you think it is?
  2. paths      - enumerate every route a client could take, and flag any
                  route that is not on the approved list
  3. rules      - check every route against approved invariants (precedence,
                  mutual exclusion) instead of the exact path list
  4. scenario   - do known client profiles produce the expected task sequence?

Layers 2-4 only ever reason about tasks: collapse_criteria() first resolves
every task -CRITERIA_BRANCH-> criteria node -HAS_CHILD-> task chain into a
plain task -> task edge carrying that branch's condition.

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

REQUIRED_TASK_ATTRS = ("rationale", "source_doc")
REQUIRED_BRANCH_ATTRS = ("condition_key", "condition_value")

# A combinatorial graph can have astronomically many simple paths. If we blow
# past this, the graph is too branchy to review path-by-path and you should
# know that rather than wait for the script to finish.
MAX_PATHS = 5000


def is_task(data: dict) -> bool:
    return "Task" in data.get("labels", "").split(";")


# --------------------------------------------------------------------------
# 1. structural checks
# --------------------------------------------------------------------------

def check_structure(
    graph: nx.DiGraph, expected_entries: list[str], expected_terminals: list[str]
) -> list[str]:
    """Return a list of failure strings. Empty list means the graph is sound."""
    failures = []

    # A recommendation flow should never loop back on itself.
    if not nx.is_directed_acyclic_graph(graph):
        failures.append(f"graph contains a cycle: {nx.find_cycle(graph)}")

    # Entry points are the nodes nothing leads to.
    entries = {n for n, d in graph.in_degree() if d == 0}
    if entries != set(expected_entries):
        failures.append(
            f"entry points changed: expected {sorted(expected_entries)}, "
            f"found {sorted(entries)}"
        )

    # Every node must be reachable from some entry point.
    reachable = set(entries)
    for entry in entries:
        reachable |= nx.descendants(graph, entry)
    orphans = set(graph) - reachable
    if orphans:
        failures.append(f"unreachable nodes: {sorted(orphans)}")

    # Dead ends must be intentional endpoints, not accidents.
    terminals = {n for n, d in graph.out_degree() if d == 0}
    unexpected = terminals - set(expected_terminals)
    if unexpected:
        failures.append(f"unexpected dead ends: {sorted(unexpected)}")

    # Every task carries its justification. Criteria nodes are branch points,
    # not client-facing steps, so they're exempt.
    for node, data in graph.nodes(data=True):
        if not is_task(data):
            continue
        missing = [a for a in REQUIRED_TASK_ATTRS if not data.get(a)]
        if missing:
            failures.append(f"task {node!r} missing {missing}")

    # Every branch states the condition under which it is taken. Plain
    # HAS_CHILD edges between two tasks are unconditional by construction.
    for src, dst, data in graph.edges(data=True):
        if data.get("rel") != "CRITERIA_BRANCH":
            continue
        missing = [a for a in REQUIRED_BRANCH_ATTRS if a not in data]
        if missing:
            failures.append(f"branch {src!r} -> {dst!r} missing {missing}")

    return failures


# --------------------------------------------------------------------------
# 1b. collapse criteria nodes into plain task -> task edges
# --------------------------------------------------------------------------

def collapse_criteria(graph: nx.DiGraph) -> nx.DiGraph:
    """Resolve every task -CRITERIA_BRANCH-> criteria node -HAS_CHILD-> task
    chain into a direct task -> task edge carrying the branch's condition, so
    path enumeration, rule checks, and scenario walks only ever see tasks.
    """
    collapsed = nx.DiGraph()
    for node, data in graph.nodes(data=True):
        if is_task(data):
            collapsed.add_node(node, **data)

    for src, dst, data in graph.edges(data=True):
        rel = data.get("rel")
        if rel == "HAS_CHILD" and src in collapsed and dst in collapsed:
            collapsed.add_edge(src, dst, **data)
        elif rel == "CRITERIA_BRANCH":
            children = [c for c in graph.successors(dst) if is_task(graph.nodes[c])]
            if len(children) != 1:
                raise ValueError(
                    f"criteria node {dst!r} must have exactly one HAS_CHILD "
                    f"task, found {children}"
                )
            collapsed.add_edge(src, children[0], **data)

    return collapsed


# --------------------------------------------------------------------------
# 2. path enumeration
# --------------------------------------------------------------------------

def enumerate_paths(
    graph: nx.DiGraph, entries: list[str], terminals: list[str]
) -> list[list[str]]:
    """Every simple route from an entry point to an endpoint, sorted for diffing."""
    paths = []
    for entry in sorted(entries):
        if entry not in graph:
            continue
        for terminal in sorted(terminals):
            if terminal not in graph or entry == terminal or not nx.has_path(graph, entry, terminal):
                continue
            for path in nx.all_simple_paths(graph, entry, terminal):
                paths.append(path)
                if len(paths) > MAX_PATHS:
                    raise ValueError(
                        f"more than {MAX_PATHS} distinct client journeys; "
                        "the graph is too branchy to review path-by-path"
                    )
    return sorted(paths)


def check_paths(actual: list[list[str]], approved: list[list[str]]) -> list[str]:
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
# 3. rule checks
# --------------------------------------------------------------------------

def check_rules(paths: list[list[str]], rules: list[dict]) -> list[str]:
    """Check every path against approved invariants instead of an exact list.

    Covers paths that don't exist yet, not just the ones enumerated today —
    see mine_rules.py for generating an initial rule set from the current
    path list.
    """
    failures = []
    for rule in rules:
        kind = rule["type"]
        if kind == "precedence":
            before, after = rule["before"], rule["after"]
            for path in paths:
                if before in path and after in path and path.index(before) > path.index(after):
                    failures.append(
                        f"precedence rule violated: {before!r} must come "
                        f"before {after!r}: {path}"
                    )
        elif kind == "mutual_exclusion":
            steps = set(rule["steps"])
            for path in paths:
                if steps <= set(path):
                    failures.append(
                        f"mutual exclusion rule violated: {sorted(steps)} "
                        f"both appear in {path}"
                    )
        else:
            failures.append(f"unknown rule type: {kind!r}")
    return failures


# --------------------------------------------------------------------------
# 4. scenario checks
# --------------------------------------------------------------------------

def edge_allowed(profile: dict, data: dict) -> bool:
    """
    Conditions are stored as a key/value pair, not as an expression string,
    so this is a plain lookup. Never eval() a condition pulled from a database.
    """
    return profile.get(data["condition_key"]) == data["condition_value"]


def walk(graph: nx.DiGraph, start: str, profile: dict) -> list[str]:
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


def check_scenarios(graph: nx.DiGraph, scenarios: list[dict]) -> list[str]:
    failures = []
    for case in scenarios:
        name = case["name"]
        if case["start"] not in graph:
            failures.append(f"scenario {name!r}: start step {case['start']!r} not in graph")
            continue
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

def main() -> None:
    graphml_path, expectations_path = Path(sys.argv[1]), Path(sys.argv[2])
    outdir = graphml_path.parent

    graph = nx.read_graphml(graphml_path)
    config = yaml.safe_load(expectations_path.read_text())

    entries = config["expected_entries"]
    terminals = config["expected_terminals"]

    failures = check_structure(graph, entries, terminals)

    try:
        collapsed = collapse_criteria(graph)
    except ValueError as exc:
        failures.append(str(exc))
        collapsed = None

    paths = []
    if collapsed is not None:
        # Only enumerate paths if the graph is acyclic; otherwise it never terminates.
        if nx.is_directed_acyclic_graph(graph):
            try:
                paths = enumerate_paths(collapsed, entries, terminals)
                (outdir / "paths.json").write_text(json.dumps(paths, indent=2) + "\n")
                failures += check_paths(paths, config.get("approved_paths", []))
                failures += check_rules(paths, config.get("rules", []))
            except ValueError as exc:
                failures.append(str(exc))

        failures += check_scenarios(collapsed, config.get("scenarios", []))

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
