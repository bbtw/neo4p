"""
Validate one knowledge graph against its declared shape and its baseline.

Three files in, one verdict out:

    graph.graphml       what the graph is now
    shape.yaml          how to read it (see shape.py) — declared, not guessed
    expectations.yaml   what it is allowed to do (the committed baseline)

Five layers, run in order. Each is independent and each reports what it
checked, not just what failed:

  0. shape     - does the graph match what shape.yaml claims about it?
                 Every later layer reads the graph through the shape, so
                 this runs first and stops everything if it fails.
  1. structure - is the graph shaped the way you think? (acyclic, entries
                 and terminals as expected, nothing unreachable, every step
                 carrying its required documentation)
  2. paths     - enumerate every route a client could take; flag any route
                 not on the approved list, and any approved route that has
                 gone missing
  3. rules     - check every route against declared invariants (precedence,
                 mutual exclusion) rather than the exact path list, so
                 routes that don't exist yet are covered too
  4. scenarios - do known client profiles walk the exact expected sequence?

Layers 2-4 reason only about steps: collapse_branches() first resolves every
step -branch-> branch node -direct-> step chain into a plain step -> step
edge carrying that branch's condition.

Usage:
    python validate.py graph.graphml shape.yaml expectations.yaml

Writes paths.json and validation.json next to the graphml. Exit code 0 = all
checks passed, 1 = something failed, 2 = could not run the checks at all
(bad shape file, unreadable graph). Safe as an automated deploy gate.

There is no live Neo4j connection anywhere in this pipeline; the graphml file
on disk is the only graph input, typically produced by apoc.export.graphml.*
(scoped query or whole-database, useTypes on or off). normalize_graph()
reconciles pure export-format differences — which attribute holds the
relationship type, exporter-assigned vs. business node ids — and nothing
else. Nothing here filters out unrelated nodes: feed it a whole-database
export with no scoping query and the extra material surfaces as unreachable
nodes and unexpected dead ends in layer 1, rather than being silently
dropped.
"""

import argparse
import json
import sys
from pathlib import Path

import networkx as nx
import yaml

from shape import GraphShape, check_shape, load_shape

# A combinatorial graph can have astronomically many simple paths. Past this,
# the graph is too branchy to review path-by-path and you should be told so
# rather than left waiting on a script that never finishes.
MAX_PATHS = 5000


# --------------------------------------------------------------------------
# 0. normalize export-format differences into this pipeline's conventions
# --------------------------------------------------------------------------

def normalize_graph(graph) -> nx.DiGraph:
    """Reconcile export-format differences only — never domain meaning, which
    comes from shape.yaml. Three things a graphml writer can vary:

      - which edge attribute holds the relationship type. This pipeline reads
        `rel` everywhere past this point; apoc.export.graphml.* calls it
        `label`. Whichever of a short candidate list is present on every edge
        gets copied into `rel`.
      - node identity: APOC keys graphml nodes on an exporter-assigned id
        ("n188"), not the node's business `id` property. If a node carries an
        `id` that differs from its graphml key, the graph is relabelled to
        use it, so identity is stable across re-exports.
      - parallel edges: an export containing two relationships between the
        same pair of nodes reads back as a MultiDiGraph, on which the rest of
        this module's DiGraph assumptions quietly break. Rejected outright.

    A no-op on a graphml that already uses `rel` and business ids (e.g. a
    hand-authored fixture).
    """
    if graph.is_multigraph():
        parallel = sorted(
            {(u, v) for u, v, k in graph.edges(keys=True) if k > 0}
        )
        raise ValueError(
            "graph has parallel relationships between the same pair of nodes "
            f"(e.g. {parallel[:3]}), which this pipeline cannot validate "
            "unambiguously — scope the export to one relationship type per pair"
        )
    if not graph.is_directed():
        raise ValueError("graph is undirected; a planning flow must be directed")

    REL_KEY_CANDIDATES = ("rel", "type", "label")
    edges = list(graph.edges(data=True))
    if edges and not all("rel" in data for _, _, data in edges):
        for key in REL_KEY_CANDIDATES:
            if key != "rel" and all(key in data for _, _, data in edges):
                for _, _, data in edges:
                    data["rel"] = data.pop(key)
                break

    # Business ids are stringified: an APOC export with useTypes:true can
    # yield integer ids, and later sorted() calls over a mix of str and int
    # node keys raise TypeError.
    id_map = {}
    for node, data in graph.nodes(data=True):
        business_id = data.get("id")
        if business_id is not None and business_id != "" and str(business_id) != node:
            id_map[node] = str(business_id)
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
    shape: GraphShape,
    expected_entries: list[str],
    expected_terminals: list[str],
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

    # Every step carries its required documentation. Branch nodes are exempt
    # — they hold a condition, not client-facing documentation. Which nodes
    # those are comes from the declared labels, so a node cannot become
    # exempt by accident.
    for node, data in graph.nodes(data=True):
        if shape.is_branch_node(data):
            continue
        missing = [a for a in shape.required_step_attrs if not data.get(a)]
        if missing:
            failures.append(f"step {node!r} missing {missing}")

    # Every branch edge carries what a branch edge is declared to carry.
    for src, dst, data in graph.edges(data=True):
        if not shape.is_branch_edge(data):
            continue
        missing = [a for a in shape.required_branch_attrs if a not in data]
        if missing:
            failures.append(f"branch {src!r} -> {dst!r} missing {missing}")

    return failures


# --------------------------------------------------------------------------
# 1b. collapse branch nodes into plain step -> step edges
# --------------------------------------------------------------------------

def collapse_branches(graph: nx.DiGraph, shape: GraphShape) -> nx.DiGraph:
    """Resolve every step -branch-> branch node -direct-> step chain into a
    direct step -> step edge carrying the branch's condition, so path
    enumeration, rule checks and scenario walks only ever see steps.

    Assumes check_shape() has already passed: every branch node has exactly
    one child and is reached only by branch edges. Anything still surprising
    at this point raises rather than dropping data.
    """
    collapsed = nx.DiGraph()
    for node, data in graph.nodes(data=True):
        if not shape.is_branch_node(data):
            collapsed.add_node(node, **data)

    for src, dst, data in graph.edges(data=True):
        if shape.is_branch_node(graph.nodes[src]):
            continue  # the branch node's own outgoing edge, folded in below

        if shape.is_branch_node(graph.nodes[dst]):
            children = list(graph.successors(dst))
            if len(children) != 1:
                raise ValueError(
                    f"branch node {dst!r} must have exactly one direct child, "
                    f"found {sorted(children)}"
                )
            target = children[0]
        else:
            target = dst

        # Two branches from the same source resolving to the same step would
        # overwrite each other in a plain DiGraph, silently discarding the
        # first branch's condition. That is a real modelling ambiguity, not
        # something to paper over.
        if collapsed.has_edge(src, target) and collapsed.edges[src, target] != data:
            raise ValueError(
                f"two distinct transitions from {src!r} both resolve to "
                f"{target!r} with different conditions "
                f"({collapsed.edges[src, target]} vs {data}); the graph cannot "
                "express which one applies"
            )
        collapsed.add_edge(src, target, **data)

    return collapsed


# --------------------------------------------------------------------------
# 2. path enumeration
# --------------------------------------------------------------------------

def enumerate_paths(
    graph: nx.DiGraph, entries: list[str], terminals: list[str]
) -> list[list[str]]:
    """Every simple route from an entry point to an endpoint, sorted for
    diffing. A node that is both an entry and a terminal is a real, if
    degenerate, zero-step journey and is emitted as a single-node path, so it
    can be approved in expectations.yaml like any other."""
    paths = []
    for entry in sorted(entries):
        if entry not in graph:
            continue
        for terminal in sorted(terminals):
            if terminal not in graph:
                continue
            if entry == terminal:
                paths.append([entry])
                continue
            if not nx.has_path(graph, entry, terminal):
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
    """Check every path against declared invariants instead of an exact list.

    Covers routes that don't exist yet, not just the ones enumerated today —
    see propose_shape.py / mine_rules.py for generating an initial rule set
    from the current path list.
    """
    failures = []
    for rule in rules:
        kind = rule.get("type")
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
                overlap = steps & set(path)
                if steps <= set(path):
                    failures.append(
                        f"mutual exclusion rule violated: {sorted(overlap)} "
                        f"appear together in {path}"
                    )
        else:
            failures.append(f"unknown rule type: {kind!r}")
    return failures


# --------------------------------------------------------------------------
# 4. scenario checks
# --------------------------------------------------------------------------

def edge_allowed(profile: dict, data: dict, shape: GraphShape) -> bool:
    """Conditions are a declared key/value attribute pair, not an expression
    string, so this is a plain lookup. Never eval() a condition pulled from a
    database.

    An edge carrying no condition attribute is unconditional — always taken.
    Because both attribute names come from shape.yaml and are validated to be
    declared together, there is no case where a half-identified condition
    silently evaluates to "never matches".
    """
    if not shape.has_condition() or shape.condition_key_attr not in data:
        return True
    return profile.get(data[shape.condition_key_attr]) == data.get(
        shape.condition_value_attr
    )


def walk(graph: nx.DiGraph, start: str, profile: dict, shape: GraphShape) -> list[str]:
    """Follow the one edge whose condition the profile satisfies, until we stop."""
    path = [start]
    node = start
    seen = {start}

    while True:
        options = [
            dst for _, dst, data in graph.out_edges(node, data=True)
            if edge_allowed(profile, data, shape)
        ]
        if not options:
            return path
        if len(options) > 1:
            raise ValueError(f"ambiguous branch at {node!r}: {sorted(options)}")

        node = options[0]
        if node in seen:
            raise ValueError(f"walk revisited {node!r}; the graph contains a cycle")
        seen.add(node)
        path.append(node)


def check_scenarios(
    graph: nx.DiGraph, scenarios: list[dict], shape: GraphShape
) -> list[str]:
    failures = []
    for case in scenarios:
        name = case["name"]
        if case["start"] not in graph:
            failures.append(f"scenario {name!r}: start step {case['start']!r} not in graph")
            continue
        if not shape.has_condition():
            failures.append(
                f"scenario {name!r}: shape declares no condition attributes, so "
                "no profile can steer a branch — declare condition_key_attr and "
                "condition_value_attr, or remove the scenarios"
            )
            continue
        try:
            actual = walk(graph, case["start"], case["profile"], shape)
        except ValueError as exc:
            failures.append(f"scenario {name!r}: {exc}")
            continue
        if actual != case["expected_path"]:
            failures.append(
                f"scenario {name!r}: expected {case['expected_path']}, got {actual}"
            )
    return failures


# --------------------------------------------------------------------------

def run(graphml_path: Path, shape_path: Path, expectations_path: Path) -> dict:
    """Run every layer. Returns the report dict; writes nothing."""
    shape = load_shape(shape_path)
    graph = normalize_graph(nx.read_graphml(graphml_path))
    config = yaml.safe_load(expectations_path.read_text()) or {}

    entries = config["expected_entries"]
    terminals = config["expected_terminals"]

    layers = {}
    paths = []

    # Layer 0 — the premise for everything else.
    layers["shape"] = check_shape(graph, shape)
    if layers["shape"]:
        return {
            "graphml": str(graphml_path),
            "shape_file": str(shape_path),
            "expectations": str(expectations_path),
            "passed": False,
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "path_count": 0,
            "layers": layers,
            "failures": layers["shape"],
            "stopped_after": "shape",
        }

    layers["structure"] = check_structure(graph, shape, entries, terminals)

    try:
        collapsed = collapse_branches(graph, shape)
    except ValueError as exc:
        layers["structure"] = layers["structure"] + [str(exc)]
        collapsed = None

    layers["paths"] = []
    layers["rules"] = []
    layers["scenarios"] = []

    if collapsed is not None:
        # Path enumeration never terminates on a cyclic graph.
        if nx.is_directed_acyclic_graph(graph):
            try:
                paths = enumerate_paths(collapsed, entries, terminals)
                layers["paths"] = check_paths(paths, config.get("approved_paths", []))
                layers["rules"] = check_rules(paths, config.get("rules", []))
            except ValueError as exc:
                layers["paths"] = [str(exc)]
        else:
            layers["paths"] = ["skipped: graph contains a cycle"]

        layers["scenarios"] = check_scenarios(
            collapsed, config.get("scenarios", []), shape
        )

    failures = [f for layer in layers.values() for f in layer]

    return {
        "graphml": str(graphml_path),
        "shape_file": str(shape_path),
        "expectations": str(expectations_path),
        "passed": not failures,
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "step_count": sum(
            1 for _, d in graph.nodes(data=True) if not shape.is_branch_node(d)
        ),
        "path_count": len(paths),
        "counts": {
            "approved_paths": len(config.get("approved_paths", [])),
            "rules": len(config.get("rules", [])),
            "scenarios": len(config.get("scenarios", [])),
        },
        "layers": layers,
        "failures": failures,
        "paths": paths,
    }


LAYER_LABELS = {
    "shape": "graph matches shape.yaml",
    "structure": "entries, terminals, reachability, required attributes",
    "paths": "every route is on the approved list",
    "rules": "declared invariants hold on every route",
    "scenarios": "known profiles walk their expected sequence",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a knowledge graph against its shape and baseline.",
    )
    parser.add_argument("graphml", type=Path, help="graph.graphml to validate")
    parser.add_argument("shape", type=Path, help="shape.yaml describing how to read it")
    parser.add_argument(
        "expectations", type=Path, help="expectations.yaml — the committed baseline"
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help="where to write paths.json and validation.json (default: next to the graphml)",
    )
    args = parser.parse_args()

    for path in (args.graphml, args.shape, args.expectations):
        if not path.exists():
            print(f"no such file: {path}", file=sys.stderr)
            sys.exit(2)

    # Print the shape before anything else: it is the premise every result
    # below depends on, so it should never be something you go look up.
    try:
        print(load_shape(args.shape).describe())
        print()
        report = run(args.graphml, args.shape, args.expectations)
    except (ValueError, KeyError) as exc:
        print(f"cannot validate: {exc}", file=sys.stderr)
        sys.exit(2)

    outdir = args.outdir or args.graphml.parent
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "paths.json").write_text(json.dumps(report.pop("paths", []), indent=2) + "\n")
    (outdir / "validation.json").write_text(json.dumps(report, indent=2) + "\n")

    # Report every layer, passing or failing — a gate that only ever prints
    # failures gives you no way to tell "checked and clean" from "never ran".
    for name, description in LAYER_LABELS.items():
        results = report["layers"].get(name)
        if results is None:
            print(f"  ---- {name:<10} not reached ({description})")
            continue
        if results:
            print(f"  FAIL {name:<10} {len(results)} problem(s) ({description})")
            for line in results:
                print(f"         - {line}")
        else:
            print(f"  ok   {name:<10} {description}")

    print()
    if report["failures"]:
        print(f"FAILED — {len(report['failures'])} problem(s)")
        sys.exit(1)

    counts = report["counts"]
    print(
        f"PASSED — {report['step_count']} steps, {report['edge_count']} edges, "
        f"{report['path_count']} client journeys checked against "
        f"{counts['approved_paths']} approved, {counts['rules']} rules, "
        f"{counts['scenarios']} scenarios"
    )


if __name__ == "__main__":
    main()
