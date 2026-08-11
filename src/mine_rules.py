"""
Mine candidate precedence and mutual-exclusion rules from a graph's current,
already-approved paths.

Treats paths.json as ground truth: every invariant found here already holds
in the graph today. Writes candidates for review, not enforced rules — merge
the ones you actually mean into expectations.yaml's `rules:` list, then
validate.py's check_rules() enforces them on every future run.

Usage:
    python mine_rules.py paths.json

Reads the paths.json that validate.py writes, and drops mined_rules.yaml
next to it.
"""

import argparse
import json
from itertools import combinations
from pathlib import Path

import yaml


def mine_precedence(paths: list[list[str]], entries: set[str]) -> list[dict]:
    """a before b, for every pair that always appears in the same relative
    order. Skips pairs starting at an entry point: an entry preceding
    everything is guaranteed by definition, not a discovered invariant."""
    rules = []
    nodes = {n for path in paths for n in path} - entries
    for a, b in combinations(sorted(nodes), 2):
        orders = {
            "before" if path.index(a) < path.index(b) else "after"
            for path in paths
            if a in path and b in path
        }
        if orders == {"before"}:
            rules.append({"type": "precedence", "before": a, "after": b})
        elif orders == {"after"}:
            rules.append({"type": "precedence", "before": b, "after": a})
    return rules


def mine_mutual_exclusion(paths: list[list[str]], terminals: set[str]) -> list[dict]:
    """Pairs of steps that never appear on the same path. Skips terminal
    pairs: a path has exactly one terminal by construction, so any two
    terminals are trivially mutually exclusive."""
    rules = []
    nodes = {n for path in paths for n in path}
    for a, b in combinations(sorted(nodes), 2):
        if a in terminals and b in terminals:
            continue
        if not any(a in path and b in path for path in paths):
            rules.append({"type": "mutual_exclusion", "steps": [a, b]})
    return rules


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mine candidate rules from an enumerated path list.",
    )
    parser.add_argument("paths", type=Path, help="paths.json written by validate.py")
    paths_path = parser.parse_args().paths
    paths = json.loads(paths_path.read_text())

    entries = {path[0] for path in paths}
    terminals = {path[-1] for path in paths}

    rules = mine_precedence(paths, entries) + mine_mutual_exclusion(paths, terminals)

    outpath = paths_path.parent / "mined_rules.yaml"
    outpath.write_text(
        "# Candidate rules mined from paths.json. Review each one, then merge\n"
        "# the ones you actually mean into expectations.yaml's `rules:` list.\n"
        + yaml.dump(rules, sort_keys=False, default_flow_style=False)
    )
    print(f"wrote {len(rules)} candidate rules to {outpath}")


if __name__ == "__main__":
    main()
