"""
Diff a new graph version against the frozen baseline, for sign-off.

validate.py answers "does the graph still match the baseline?" as a
mechanical gate.
This script produces the review artifact for when it doesn't: exactly which
client journeys a graph change added or removed relative to the committed
expectations.yaml, whether the added journeys break any baseline rule, and
whether baseline scenarios still walk the expected sequence. A reviewer signs
off on this delta — never by re-reading the full path list.

Usage:
    python diff_baseline.py <new_graph.graphml> <baseline_expectations.yaml> [--update]

Writes change_report.md next to the new graphml. With --update, also writes
expectations.yaml next to it: approved_paths, entries, and terminals updated
to the new graph, required_step_attrs/rules/scenarios carried over from the
baseline untouched. Committing that file (its git diff = this report) is the
sign-off.

Exit code 0 = no change from baseline, 1 = changes found (see report),
2 = cannot diff (e.g. cycle or path explosion).

Accepts a plain apoc.export.graphml.* export directly — no live Neo4j
connection needed (see validate.normalize_graph for the details).
"""

import sys
from pathlib import Path

import networkx as nx
import yaml

from schema import infer_schema
from validate import (
    check_rules,
    check_scenarios,
    collapse_criteria,
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
        new["collapsed"], baseline.get("scenarios", []), new["schema"]
    )

    changed = bool(added or removed or structure)

    lines = [
        "# Change report",
        "",
        f"- new graph: `{graphml}`",
        f"- baseline: `{baseline_path}`",
        f"- journeys: {unchanged} unchanged, {len(added)} added, {len(removed)} removed",
        "",
    ]

    if not changed:
        lines += ["No structural changes from baseline.", ""]

    if structure:
        lines += ["## Entry / terminal changes", ""]
        lines += [f"- `{l}`" for l in structure] + [""]

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
        lines += [
            f"- all {len(baseline.get('scenarios', []))} baseline scenarios "
            "produce their expected sequence",
            "",
        ]

    return "\n".join(lines), changed


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--update"]
    update = "--update" in sys.argv
    graphml, baseline_path = Path(args[0]), Path(args[1])

    baseline = yaml.safe_load(baseline_path.read_text())
    graph = normalize_graph(nx.read_graphml(graphml))

    if not nx.is_directed_acyclic_graph(graph):
        sys.exit(f"cannot diff: new graph contains a cycle: {nx.find_cycle(graph)}")

    entries = sorted(n for n, d in graph.in_degree() if d == 0)
    terminals = sorted(n for n, d in graph.out_degree() if d == 0)
    schema = infer_schema(graph)
    try:
        collapsed = collapse_criteria(graph)
        paths = enumerate_paths(collapsed, entries, terminals)
    except ValueError as exc:
        sys.exit(f"cannot diff: {exc}")

    new = {
        "entries": entries,
        "terminals": terminals,
        "paths": paths,
        "collapsed": collapsed,
        "schema": schema,
    }
    report, changed = build_report(graphml, baseline_path, baseline, new)

    report_path = graphml.parent / "change_report.md"
    report_path.write_text(report + "\n")
    print(report)
    print(f"wrote {report_path}")

    if update:
        updated = {
            "expected_entries": entries,
            "expected_terminals": terminals,
            "required_step_attrs": baseline.get("required_step_attrs", []),
            "approved_paths": paths,
            "rules": baseline.get("rules", []),
            "scenarios": baseline.get("scenarios", []),
        }
        outpath = graphml.parent / "expectations.yaml"
        outpath.write_text(
            f"# Updated from baseline {baseline_path} for {graphml}.\n"
            "# Review change_report.md, then commit: its git diff is the sign-off.\n"
            + yaml.dump(updated, sort_keys=False, default_flow_style=False)
        )
        print(f"wrote {outpath} (rules and scenarios carried over from baseline)")

    sys.exit(1 if changed else 0)


if __name__ == "__main__":
    main()
