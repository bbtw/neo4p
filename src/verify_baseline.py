"""
Verify a bootstrapped expectations.yaml against the LIVE Neo4j graph.

Independent cross-check for the cold-start workflow: bootstrap.py derives the
draft from a graphml export, so a stale, truncated, or wrongly-exported file
would produce a faithful mirror of the wrong graph. This script goes around
the export entirely — it queries the live graph over Bolt and checks that the
draft's entries, terminals, and every approved path exist there.

It does not enumerate live paths (that is validate.py's job on the snapshot);
it checks that nothing the draft asserts is contradicted by the live graph:

  - expected_entries    == live nodes with no incoming planning edge
  - expected_terminals  == live task nodes with no outgoing planning edge
  - every consecutive task pair in every approved path is connected in the
    live graph, either directly (HAS_CHILD) or via a criteria node
  - live task count matches the number of distinct tasks the draft mentions,
    so the draft is not silently missing part of the graph

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \
        python verify_baseline.py expectations.yaml

Exit code 0 = draft consistent with live graph, 1 = mismatches found.
"""

import os
import sys
from pathlib import Path

import yaml
from neo4j import Driver, GraphDatabase

ENTRY_QUERY = """
MATCH (n)
WHERE (n:Task OR n:CriteriaNode)
  AND NOT ()-[:HAS_CHILD|CRITERIA_BRANCH]->(n)
RETURN n.id AS id
"""

TERMINAL_QUERY = """
MATCH (n:Task)
WHERE NOT (n)-[:HAS_CHILD|CRITERIA_BRANCH]->()
RETURN n.id AS id
"""

TASK_QUERY = "MATCH (n:Task) RETURN n.id AS id"

# Two tasks are consecutive on a journey iff connected directly or via one
# criteria node — the same shape collapse_criteria() flattens in validate.py.
STEP_QUERY = """
MATCH (a:Task {id: $src})
WHERE (a)-[:HAS_CHILD]->(:Task {id: $dst})
   OR (a)-[:CRITERIA_BRANCH]->(:CriteriaNode)-[:HAS_CHILD]->(:Task {id: $dst})
RETURN count(*) > 0 AS connected
"""


def fetch_ids(driver: Driver, query: str) -> set[str]:
    with driver.session() as session:
        return {rec["id"] for rec in session.run(query)}


def step_connected(driver: Driver, src: str, dst: str) -> bool:
    with driver.session() as session:
        return session.run(STEP_QUERY, src=src, dst=dst).single()["connected"]


def compare_sets(name: str, draft: set[str], live: set[str]) -> list[str]:
    failures = []
    if draft - live:
        failures.append(f"{name} in draft but not live graph: {sorted(draft - live)}")
    if live - draft:
        failures.append(f"{name} in live graph but not draft: {sorted(live - draft)}")
    return failures


def verify(driver: Driver, draft: dict) -> list[str]:
    failures = []

    failures += compare_sets(
        "entries", set(draft["expected_entries"]), fetch_ids(driver, ENTRY_QUERY)
    )
    failures += compare_sets(
        "terminals", set(draft["expected_terminals"]), fetch_ids(driver, TERMINAL_QUERY)
    )

    paths = draft.get("approved_paths", [])
    checked: set[tuple[str, str]] = set()
    for path in paths:
        for src, dst in zip(path, path[1:]):
            if (src, dst) in checked:
                continue
            checked.add((src, dst))
            if not step_connected(driver, src, dst):
                failures.append(
                    f"approved step {src!r} -> {dst!r} has no edge in live graph"
                )

    draft_tasks = {n for path in paths for n in path}
    live_tasks = fetch_ids(driver, TASK_QUERY)
    if live_tasks - draft_tasks:
        failures.append(
            "live tasks on no approved path (draft may be from a stale or "
            f"partial export): {sorted(live_tasks - draft_tasks)}"
        )

    return failures


def main() -> None:
    draft = yaml.safe_load(Path(sys.argv[1]).read_text())

    uri = os.environ["NEO4J_URI"]
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        failures = verify(driver, draft)
    finally:
        driver.close()

    if failures:
        print(f"MISMATCH ({len(failures)} problems)\n")
        for line in failures:
            print(f"  - {line}")
        sys.exit(1)

    print(
        f"CONSISTENT - draft matches live graph: "
        f"{len(draft['expected_entries'])} entries, "
        f"{len(draft['expected_terminals'])} terminals, "
        f"{len(draft.get('approved_paths', []))} paths spot-checked"
    )


if __name__ == "__main__":
    main()
