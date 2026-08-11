"""
Bootstrap a draft expectations.yaml from a graph that has none.

For the cold-start case: you have a graph.graphml and a reviewed shape.yaml,
but nothing to validate against yet. This derives everything derivable from
the graph itself — entry points, terminals, the full path list, and candidate
rules mined from those paths — and writes a draft baseline.

The draft is DESCRIPTIVE, not normative: it approves whatever the graph
currently does, bugs included. It catches nothing on day one. The one-time
human review of the draft is the audit of the existing graph; committing the
reviewed file is what turns it into a baseline that catches every change
after it. Scenarios cannot be derived from topology and are left as an empty
stub to hand-write.

Requires shape.yaml first — run propose_shape.py if you don't have one. The
shape decides which nodes are steps and which are branch points, so it has
to be settled before "what paths exist" means anything.

Usage:
    python bootstrap.py graph.graphml shape.yaml [-o expectations.yaml]

Writes expectations.yaml next to the graphml unless -o is given, and refuses
to overwrite an existing file. Exit code 0 = draft written and the graph is
structurally clean, 1 = structural problems found (the draft is still
written, so you can see what it would have approved), 2 = cannot bootstrap
at all (cycle, bad shape file, path explosion).
"""

import argparse
import sys
from pathlib import Path

import networkx as nx
import yaml

from mine_rules import mine_mutual_exclusion, mine_precedence
from shape import check_shape, load_shape
from validate import (
    check_structure,
    collapse_branches,
    enumerate_paths,
    normalize_graph,
)

HEADER = """\
# GENERATED BASELINE — draft expectations.yaml bootstrapped from:
#   graph: {graphml}
#   shape: {shape}
#
# Everything below describes what the graph CURRENTLY does, bugs included.
# Validating the same graph against this file passes by construction.
# Before committing:
#   1. Review approved_paths: every journey listed here gets signed off.
#   2. Review rules: keep only the invariants you actually mean to enforce,
#      and hand-write rules the miner cannot see (e.g. mutual exclusion
#      against steps that do not exist in the graph yet).
#   3. Write scenarios: known client profiles and the exact task sequence
#      each must produce. These cannot be derived from topology.
# The git diff of this file is the review record for every change after it.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draft an expectations.yaml baseline from a graph.",
    )
    parser.add_argument("graphml", type=Path)
    parser.add_argument("shape", type=Path, help="reviewed shape.yaml for this graph")
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args()

    outpath = args.out or args.graphml.parent / "expectations.yaml"
    for path in (args.graphml, args.shape):
        if not path.exists():
            print(f"no such file: {path}", file=sys.stderr)
            sys.exit(2)
    if outpath.exists():
        print(f"refusing to overwrite existing {outpath} — move it first", file=sys.stderr)
        sys.exit(2)

    try:
        shape = load_shape(args.shape)
        graph = normalize_graph(nx.read_graphml(args.graphml))
    except ValueError as exc:
        print(f"cannot bootstrap: {exc}", file=sys.stderr)
        sys.exit(2)

    print(shape.describe())
    print()

    # The shape has to fit before anything derived from it means anything.
    shape_failures = check_shape(graph, shape)
    if shape_failures:
        print("cannot bootstrap: the graph does not match shape.yaml:", file=sys.stderr)
        for line in shape_failures:
            print(f"  - {line}", file=sys.stderr)
        sys.exit(2)

    entries = sorted(n for n, d in graph.in_degree() if d == 0)
    terminals = sorted(n for n, d in graph.out_degree() if d == 0)

    # Structural problems are real findings even with no baseline yet.
    # Entry/terminal checks pass trivially (we just derived them); cycles,
    # orphans and missing required attrs are not things a baseline should
    # silently bless.
    problems = check_structure(graph, shape, entries, terminals)

    if not nx.is_directed_acyclic_graph(graph):
        print("cannot bootstrap: graph contains a cycle", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        sys.exit(2)

    try:
        collapsed = collapse_branches(graph, shape)
        paths = enumerate_paths(collapsed, entries, terminals)
    except ValueError as exc:
        print(f"cannot bootstrap: {exc}", file=sys.stderr)
        sys.exit(2)

    rules = mine_precedence(paths, {p[0] for p in paths}) + mine_mutual_exclusion(
        paths, {p[-1] for p in paths}
    )

    draft = {
        "expected_entries": entries,
        "expected_terminals": terminals,
        "approved_paths": paths,
        "rules": rules,
        "scenarios": [],
    }
    outpath.write_text(
        HEADER.format(graphml=args.graphml, shape=args.shape)
        + yaml.dump(draft, sort_keys=False, default_flow_style=False)
    )

    print(
        f"wrote draft baseline to {outpath}: {len(entries)} entries, "
        f"{len(terminals)} terminals, {len(paths)} paths, "
        f"{len(rules)} candidate rules, 0 scenarios (hand-write these)"
    )

    if problems:
        # Exit non-zero: a CI wrapper checking only the status code must not
        # read "draft written" as "graph is clean".
        print(f"\n{len(problems)} structural problem(s) to fix before review:")
        for line in problems:
            print(f"  - {line}")
        sys.exit(1)


if __name__ == "__main__":
    main()
