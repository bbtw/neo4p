"""Export the Neo4j financial planning graph seed as JSON."""

import argparse
import json
import os
import sys
from pathlib import Path

from kg_viewer.config import load_local_env
from kg_viewer.server import Neo4jClient


def export_seed(client: Neo4jClient) -> dict:
    nodes = [
        row[0]
        for row in client.query(
            """
            MATCH (n:FinancialPlanningGraph)
            WITH n,
              CASE
                WHEN n:Need THEN "Need"
                WHEN n:Subneed THEN "Subneed"
                WHEN n:Task THEN "Task"
              END AS label
            RETURN {
              id: n.id,
              label: label,
              name: n.name,
              description: coalesce(n.description, "")
            } AS node
            ORDER BY label, n.name, n.id
            """
        )
    ]
    relationships = [
        row[0]
        for row in client.query(
            """
            MATCH (source:FinancialPlanningGraph)-[r:HAS_SUBNEED|HAS_TASK]->(target:FinancialPlanningGraph)
            RETURN {
              source: source.id,
              target: target.id,
              type: type(r)
            } AS relationship
            ORDER BY type(r), source.id, target.id
            """
        )
    ]
    return {"nodes": nodes, "relationships": relationships}


def export_graph(args: argparse.Namespace) -> None:
    client = Neo4jClient(args.uri, args.database, args.user, args.password)
    seed = export_seed(client)
    body = json.dumps(seed, indent=2) + "\n"

    if args.output is None:
        print(body, end="")
        return

    args.output.write_text(body, encoding="utf-8")
    print(
        f"Exported {len(seed['nodes'])} nodes and "
        f"{len(seed['relationships'])} relationships to {args.output}."
    )


def parse_args() -> argparse.Namespace:
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "http://localhost:7474"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    return parser.parse_args()


def main() -> int:
    try:
        export_graph(parse_args())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
