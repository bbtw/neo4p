"""
Validate a snapshotted planning graph.

The graph holds two kinds of node: steps (client-facing tasks) and branch
points (nodes that exist only to carry a condition). A conditional
transition is step -branch-> branch node -direct-> step, with the condition
living on the branch edge; an unconditional transition is a direct
step -> step edge. Nothing about which labels or relationship-type names
mean "step" or "branch" is hardcoded — schema.infer_schema() derives it from
the graph's own structure every run (see that module's docstring for the
two signals it uses). The graphml file is the only input this pipeline
needs; there is no separate schema file to keep in sync with it.

Four layers:
  1. structural - is the graph shaped the way you think it is?
  2. paths      - enumerate every route a client could take, and flag any
                  route that is not on the approved list
  3. rules      - check every route against approved invariants (precedence,
                  mutual exclusion) instead of the exact path list
  4. scenario   - do known client profiles produce the expected task sequence?

Layers 2-4 only ever reason about steps: collapse_criteria() first resolves
every step -branch-> branch node -direct-> step chain into a plain
step -> step edge carrying that branch's condition.

Usage:
    python validate.py snapshots/20260806T142301Z/graph.graphml expectations.yaml

Writes paths.json and validation.json into the snapshot directory.
Exit code 0 = all checks passed, 1 = something failed. Safe to run as an
automated gate in whatever process governs graph changes.

Takes a graphml file produced by apoc.export.graphml.* — scoped query or
whole-database, useTypes on or off — as long as it is already scoped to the
flow you want validated. There is no live Neo4j connection anywhere in this
pipeline; the graphml file on disk is the only input. normalize_graph()
reconciles pure export-format differences (which attribute holds the
relationship type, exporter-assigned vs. business node ids); schema.infer_schema()
then reads the graph's actual shape to work out what's a step, what's a
branch, and what the branch condition looks like. Nothing here filters out
unrelated nodes or edges: if you feed it more than the flow (e.g. a
whole-database export with no scoping query), the extra material shows up
as unreachable nodes or unexpected dead ends in check_structure()'s
failures rather than being silently dropped.
"""

import json
import sys
from pathlib import Path

import networkx as nx
import yaml

from schema import GraphSchema, infer_schema

# A combinatorial graph can have astronomically many simple paths. If we blow
# past this, the graph is too branchy to review path-by-path and you should
# know that rather than wait for the script to finish.
MAX_PATHS = 5000


# --------------------------------------------------------------------------
# 0. normalize a plain apoc.export.graphml.* export into this pipeline's
#    internal attribute conventions (`rel`, business-id node keys)
# --------------------------------------------------------------------------

def normalize_graph(graph: nx.DiGraph) -> nx.DiGraph:
    """Reconcile export-format differences only — not domain schema, which
    infer_schema() derives from structure instead. Two things a graphml
    writer can vary regardless of domain:
      - which edge attribute holds the relationship type. This pipeline
        reads it from `rel` everywhere past this point; apoc.export.graphml.*
        calls it `label` instead. This picks whichever of a short list of
        common names is present on every edge and copies it into `rel`.
      - node identity: apoc.export.graphml.* keys graphml nodes on an
        exporter-assigned id (e.g. "n188"), not the node's own business `id`
        property. If a node carries an `id` property that differs from its
        graphml node id, this relabels the graph to use it, so node identity
        is stable across re-exports of the same graph.
    A no-op on a graphml that already uses `rel` and business ids as its
    node keys (e.g. a hand-authored test fixture).
    """
    REL_KEY_CANDIDATES = ("rel", "type", "label")
    edges = list(graph.edges(data=True))
    if edges and not all("rel" in data for _, _, data in edges):
        for key in REL_KEY_CANDIDATES:
            if key != "rel" and all(key in data for _, _, data in edges):
                for _, _, data in edges:
                    data["rel"] = data.pop(key)
                break

    id_map = {}
    for node, data in graph.nodes(data=True):
        business_id = data.get("id")
        if business_id and business_id != node:
            id_map[node] = business_id
    if id_map:
        if len(set(id_map.values())) != len(id_map):
            counts = {v: list(id_map.values()).count(v) for v in id_map.values()}
            dupes = sorted(v for v, c in counts.items() if c > 1)
            raise ValueError(f"duplicate business ids while normalizing graph: {dupes}")
        graph = nx.relabel_nodes(graph, id_map)

    return graph


# --------------------------------------------------------------------------
# 1. structural checks
# --------------------------------------------------------------------------

def check_structure(
    graph: nx.DiGraph,
    expected_entries: list[str],
    expected_terminals: list[str],
    required_step_attrs: tuple = (),
) -> list[str]:
    """Return a list of failure strings. Empty list means the graph is sound."""
    failures = []
    schema = infer_schema(graph)

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

    # Every step carries its required metadata. Branch nodes are exempt —
    # they hold a condition, not client-facing documentation.
    for node, data in graph.nodes(data=True):
        if schema.is_branch(node):
            continue
        missing = [a for a in required_step_attrs if not data.get(a)]
        if missing:
            failures.append(f"task {node!r} missing {missing}")

    # Every branch-type edge should carry what the rest of its type carries.
    # Plain direct edges are unconditional by construction and exempt.
    if schema.required_branch_attrs:
        for src, dst, data in graph.edges(data=True):
            if data.get("rel") not in schema.branching_rels:
                continue
            missing = [a for a in schema.required_branch_attrs if a not in data]
            if missing:
                failures.append(f"branch {src!r} -> {dst!r} missing {missing}")

    return failures


# --------------------------------------------------------------------------
# 1b. collapse branch nodes into plain step -> step edges
# --------------------------------------------------------------------------

def collapse_criteria(graph: nx.DiGraph) -> nx.DiGraph:
    """Resolve every step -branch-> branch node -direct-> step chain into a
    direct step -> step edge carrying the branch's condition, so path
    enumeration, rule checks, and scenario walks only ever see steps.
    """
    schema = infer_schema(graph)
    collapsed = nx.DiGraph()
    for node, data in graph.nodes(data=True):
        if not schema.is_branch(node):
            collapsed.add_node(node, **data)

    for src, dst, data in graph.edges(data=True):
        rel = data.get("rel")
        if rel not in schema.branching_rels and src in collapsed and dst in collapsed:
            collapsed.add_edge(src, dst, **data)
        elif rel in schema.branching_rels:
            children = [c for c in graph.successors(dst) if not schema.is_branch(c)]
            if len(children) != 1:
                raise ValueError(
                    f"branch node {dst!r} must have exactly one direct child, "
                    f"found {children}"
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

def edge_allowed(profile: dict, data: dict, schema: GraphSchema) -> bool:
    """
    Conditions are stored as a key/value pair, not as an expression string,
    so this is a plain lookup. Never eval() a condition pulled from a database.

    An edge with no condition attribute on it (schema couldn't identify one,
    or this particular edge doesn't carry one) is treated as unconditional —
    always taken.
    """
    if not schema.condition_key_attr or schema.condition_key_attr not in data:
        return True
    return profile.get(data[schema.condition_key_attr]) == data.get(schema.condition_value_attr)


def walk(graph: nx.DiGraph, start: str, profile: dict, schema: GraphSchema = None) -> list[str]:
    """Follow the one edge whose condition the profile satisfies, until we stop."""
    if schema is None:
        schema = infer_schema(graph)

    path = [start]
    node = start

    while True:
        options = [
            dst for _, dst, data in graph.out_edges(node, data=True)
            if edge_allowed(profile, data, schema)
        ]
        if not options:
            return path
        if len(options) > 1:
            raise ValueError(f"ambiguous branch at {node!r}: {sorted(options)}")

        node = options[0]
        path.append(node)


def check_scenarios(
    graph: nx.DiGraph, scenarios: list[dict], schema: GraphSchema = None
) -> list[str]:
    if schema is None:
        schema = infer_schema(graph)

    failures = []
    for case in scenarios:
        name = case["name"]
        if case["start"] not in graph:
            failures.append(f"scenario {name!r}: start step {case['start']!r} not in graph")
            continue
        try:
            actual = walk(graph, case["start"], case["profile"], schema)
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

    graph = normalize_graph(nx.read_graphml(graphml_path))
    config = yaml.safe_load(expectations_path.read_text())

    entries = config["expected_entries"]
    terminals = config["expected_terminals"]
    required_step_attrs = tuple(config.get("required_step_attrs", []))

    failures = check_structure(graph, entries, terminals, required_step_attrs)
    schema = infer_schema(graph)

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

        failures += check_scenarios(collapsed, config.get("scenarios", []), schema)

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
