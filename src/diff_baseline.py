"""
Diff a new graph version against the frozen baseline, for sign-off.

validate.py answers "does the graph still match the baseline?" as a
mechanical gate. This produces the review artifact for when it doesn't:
exactly which client journeys a graph change added or removed relative to
the committed expectations.yaml, whether the added journeys break a baseline
rule, and whether baseline scenarios still walk the expected sequence. A
reviewer signs off on this delta — never by re-reading the full path list.

Usage:
    python diff_baseline.py new_graph.graphml shape.yaml baseline_expectations.yaml [--update]

Writes change_report.md next to the new graphml. With --update, also writes
expectations.yaml.new next to it: approved_paths, entries and terminals
updated to the new graph, rules and scenarios carried over from the baseline
untouched. Promoting that file over the committed baseline (its git diff =
this report) is the sign-off. It is written to a `.new` path deliberately —
the baseline is never overwritten by the tool that diffs against it.

Exit code 0 = no change from baseline, 1 = changes found (see report),
2 = cannot diff (cycle, path explosion, bad shape file, shape mismatch).
"""

import argparse
import sys
from pathlib import Path

import networkx as nx
import yaml

from shape import check_shape, load_shape
from validate import (
    check_rules,
    check_scenarios,
    collapse_branches,
    enumerate_paths,
    normalize_graph,
)


def fmt_path(path: list[str]) -> str:
    return " -> ".join(path)


def set_delta(name: str, old: set[str], new: set[str]) -> list[str]:
    lines = []
    for item in sorted(new - old):
        lines.append(f"+ {name} added: {item}")
    for item in sorted(old - new):
        lines.append(f"- {name} removed: {item}")
    return lines


def build_report(
    graphml: Path, baseline_path: Path, baseline: dict, new: dict
) -> tuple[str, bool]:
    """Return (markdown report, changed?)."""
    old_paths = {tuple(p) for p in baseline.get("approved_paths", [])}
    new_paths = {tuple(p) for p in new["paths"]}
    added = sorted(new_paths - old_paths)
    removed = sorted(old_paths - new_paths)
    unchanged = len(old_paths & new_paths)

    structure = set_delta(
        "entry", set(baseline["expected_entries"]), set(new["entries"])
    ) + set_delta(
        "terminal", set(baseline["expected_terminals"]), set(new["terminals"])
    )

    # Baseline rules and scenarios applied to the NEW graph: does the change
    # break an invariant or reroute a known profile?
    rule_failures = check_rules(new["paths"], baseline.get("rules", []))
    scenario_failures = check_scenarios(
        new["collapsed"], baseline.get("scenarios", []), new["shape"]
    )

    changed = bool(added or removed or structure)

    lines = [
        "# Change report",
        "",
        f"- new graph: `{graphml}`",
        f"- baseline: `{baseline_path}`",
        f"- shape: `{new['shape'].source}`",
        f"- journeys: {unchanged} unchanged, {len(added)} added, {len(removed)} removed",
        "",
    ]

    if not changed:
        lines += ["No structural changes from baseline.", ""]

    if structure:
        lines += ["## Entry / terminal changes", ""]
        lines += [f"- `{line}`" for line in structure] + [""]

    if added:
        lines += ["## Added journeys (need sign-off)", ""]
        lines += [f"- `{fmt_path(list(p))}`" for p in added] + [""]

    if removed:
        lines += ["## Removed journeys (previously approved, no longer possible)", ""]
        lines += [f"- `{fmt_path(list(p))}`" for p in removed] + [""]

    lines += ["## Baseline rules applied to new graph", ""]
    if rule_failures:
        lines += [f"- VIOLATION: {f}" for f in rule_failures] + [""]
    else:
        lines += [f"- all {len(baseline.get('rules', []))} baseline rules hold", ""]

    lines += ["## Baseline scenarios applied to new graph", ""]
    if scenario_failures:
        lines += [f"- FAILED: {f}" for f in scenario_failures] + [""]
    else:
        count = len(baseline.get("scenarios", []))
        lines += [f"- all {count} baseline scenarios produce their expected sequence", ""]

    return "\n".join(lines), changed


def die(message: str) -> None:
    """Exit 2 — 'the diff could not run' — distinct from exit 1, 'the diff ran
    and found changes'. A caller branching on status must be able to tell
    those apart."""
    print(message, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diff a new graph against the committed baseline.",
    )
    parser.add_argument("graphml", type=Path, help="the NEW graph version")
    parser.add_argument("shape", type=Path, help="shape.yaml for this graph")
    parser.add_argument("baseline", type=Path, help="committed expectations.yaml")
    parser.add_argument(
        "--update",
        action="store_true",
        help="also write expectations.yaml.new with paths refreshed to the new graph",
    )
    args = parser.parse_args()

    for path in (args.graphml, args.shape, args.baseline):
        if not path.exists():
            die(f"cannot diff: no such file: {path}")

    try:
        shape = load_shape(args.shape)
        baseline = yaml.safe_load(args.baseline.read_text()) or {}
        graph = normalize_graph(nx.read_graphml(args.graphml))
    except ValueError as exc:
        die(f"cannot diff: {exc}")

    shape_failures = check_shape(graph, shape)
    if shape_failures:
        die(
            "cannot diff: the new graph does not match shape.yaml:\n"
            + "\n".join(f"  - {f}" for f in shape_failures)
        )

    if not nx.is_directed_acyclic_graph(graph):
        die(f"cannot diff: new graph contains a cycle: {nx.find_cycle(graph)}")

    entries = sorted(n for n, d in graph.in_degree() if d == 0)
    terminals = sorted(n for n, d in graph.out_degree() if d == 0)
    try:
        collapsed = collapse_branches(graph, shape)
        paths = enumerate_paths(collapsed, entries, terminals)
    except ValueError as exc:
        die(f"cannot diff: {exc}")

    new = {
        "entries": entries,
        "terminals": terminals,
        "paths": paths,
        "collapsed": collapsed,
        "shape": shape,
    }
    report, changed = build_report(args.graphml, args.baseline, baseline, new)

    report_path = args.graphml.parent / "change_report.md"
    report_path.write_text(report + "\n")
    print(report)
    print(f"wrote {report_path}")

    if args.update:
        updated = {
            "expected_entries": entries,
            "expected_terminals": terminals,
            "approved_paths": paths,
            "rules": baseline.get("rules", []),
            "scenarios": baseline.get("scenarios", []),
        }
        # Deliberately a `.new` path: writing straight to expectations.yaml
        # would silently clobber the committed baseline this just diffed
        # against, before anyone has read the report.
        outpath = args.graphml.parent / "expectations.yaml.new"
        outpath.write_text(
            f"# Updated from baseline {args.baseline} for {args.graphml}.\n"
            "# Review change_report.md, then promote this over the committed\n"
            "# baseline: its git diff is the sign-off record.\n"
            + yaml.dump(updated, sort_keys=False, default_flow_style=False)
        )
        print(f"wrote {outpath} (rules and scenarios carried over from baseline)")
        print(f"promote it with:  mv {outpath} {args.baseline}")

    sys.exit(1 if changed else 0)


if __name__ == "__main__":
    main()
