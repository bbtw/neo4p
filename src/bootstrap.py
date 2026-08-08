"""
Bootstrap a draft expectations.yaml from a graph that has none.

For the cold-start case: you have a graph.graphml but no expectations file to
validate it against. This script derives everything derivable from the graph
itself — entry points, terminals, the full path list, and candidate rules
mined from those paths — and writes a draft expectations.yaml.

The draft is DESCRIPTIVE, not normative: it approves whatever the graph
currently does, bugs included. It catches nothing on day one. The one-time
human review of the draft is the audit of the existing graph; committing the
reviewed file is what turns it into a baseline that catches every change
after it. Scenarios cannot be derived from topology and are left as an empty
stub to hand-write.

Usage:
    python bootstrap.py snapshots/sample/graph.graphml [out.yaml]

Writes expectations.yaml next to the graphml unless an output path is given.
Refuses to overwrite an existing file. Exit code 0 = draft written,
1 = graph problems prevent bootstrapping (e.g. a cycle).
"""

import sys
from pathlib import Path

import networkx as nx
import yaml

from mine_rules import mine_mutual_exclusion, mine_precedence
from validate import (
    check_structure,
    collapse_criteria,
    enumerate_paths,
)

HEADER = """\
# GENERATED BASELINE — draft expectations.yaml bootstrapped from:
#   {graphml}
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
    graphml_path = Path(sys.argv[1])
    outpath = (
        Path(sys.argv[2]) if len(sys.argv) > 2
        else graphml_path.parent / "expectations.yaml"
    )
    if outpath.exists():
        sys.exit(f"refusing to overwrite existing {outpath} — move it first")

    graph = nx.read_graphml(graphml_path)

    # Derive what validate.py would otherwise be told.
    entries = sorted(n for n, d in graph.in_degree() if d == 0)
    terminals = sorted(n for n, d in graph.out_degree() if d == 0)

    # Structural problems are real findings even with no expectations yet.
    # Entry/terminal checks pass trivially (we just derived them); the rest —
    # cycles, orphans, missing rationale/source_doc, bare branches — are not
    # things a baseline should silently bless.
    problems = check_structure(graph, entries, terminals)
    for line in problems:
        print(f"  ! {line}")

    if not nx.is_directed_acyclic_graph(graph):
        sys.exit("cannot bootstrap: fix the cycle above and rerun")

    try:
        collapsed = collapse_criteria(graph)
        paths = enumerate_paths(collapsed, entries, terminals)
    except ValueError as exc:
        sys.exit(f"cannot bootstrap: {exc}")

    path_entries = {p[0] for p in paths}
    path_terminals = {p[-1] for p in paths}
    rules = mine_precedence(paths, path_entries) + mine_mutual_exclusion(
        paths, path_terminals
    )

    draft = {
        "expected_entries": entries,
        "expected_terminals": terminals,
        "approved_paths": paths,
        "rules": rules,
        "scenarios": [],
    }
    outpath.write_text(
        HEADER.format(graphml=graphml_path)
        + yaml.dump(draft, sort_keys=False, default_flow_style=False)
    )

    print(
        f"wrote draft baseline to {outpath}: {len(entries)} entries, "
        f"{len(terminals)} terminals, {len(paths)} paths, "
        f"{len(rules)} candidate rules, 0 scenarios (hand-write these)"
    )
    if problems:
        print(f"{len(problems)} structural problems above need fixing before review")


if __name__ == "__main__":
    main()
