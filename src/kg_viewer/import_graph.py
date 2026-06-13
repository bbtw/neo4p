"""Import the financial planning graph seed into Neo4j."""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from kg_viewer.config import ROOT, load_local_env

DEFAULT_SEED = ROOT / "data" / "financial-planning-graph.json"


def load_seed(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def flatten_graph(seed: dict) -> tuple[list[dict], list[dict]]:
    nodes = []
    relationships = []
    seen = set()
    seen_relationships = set()

    for node in seed["nodes"]:
        node_id = node["id"]
        label = node["label"]
        if label not in {"Need", "Subneed", "Task"}:
            raise ValueError(f"unsupported node label: {label}")
        if node_id in seen:
            raise ValueError(f"duplicate node id: {node_id}")
        seen.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "name": node["name"],
                "description": node.get("description", ""),
            }
        )

    for relationship in seed["relationships"]:
        source = relationship["source"]
        target = relationship["target"]
        relationship_type = relationship["type"]
        key = (source, target, relationship_type)
        if relationship_type not in {"HAS_SUBNEED", "HAS_TASK"}:
            raise ValueError(f"unsupported relationship type: {relationship_type}")
        if source not in seen:
            raise ValueError(f"relationship source does not exist: {source}")
        if target not in seen:
            raise ValueError(f"relationship target does not exist: {target}")
        if key in seen_relationships:
            raise ValueError(
                f"duplicate relationship: {source} -[{relationship_type}]-> {target}"
            )
        seen_relationships.add(key)
        relationships.append(
            {"source": source, "target": target, "type": relationship_type}
        )

    return nodes, relationships


def neo4j_request(endpoint: str, payload: dict, user: str, password: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Neo4j HTTP error {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not connect to Neo4j: {error.reason}") from error


def run_cypher(
    endpoint: str,
    user: str,
    password: str,
    statement: str,
    parameters: dict | None = None,
) -> None:
    result = neo4j_request(
        endpoint,
        {
            "statements": [
                {
                    "statement": statement,
                    "parameters": parameters or {},
                }
            ]
        },
        user,
        password,
    )
    errors = result.get("errors", [])
    if errors:
        raise RuntimeError(errors)


def import_graph(args: argparse.Namespace) -> None:
    seed = load_seed(args.seed)
    nodes, relationships = flatten_graph(seed)

    if args.dry_run:
        print(f"Seed file: {args.seed}")
        print(f"Nodes: {len(nodes)}")
        print(f"Relationships: {len(relationships)}")
        return

    endpoint = f"{args.uri.rstrip('/')}/db/{args.database}/tx/commit"

    for label in ("Need", "Subneed", "Task"):
        run_cypher(
            endpoint,
            args.user,
            args.password,
            (
                f"CREATE CONSTRAINT financial_planning_{label.lower()}_id "
                f"IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            ),
        )

    run_cypher(
        endpoint,
        args.user,
        args.password,
        "MATCH (n:FinancialPlanningGraph) DETACH DELETE n",
    )

    run_cypher(
        endpoint,
        args.user,
        args.password,
        """
        UNWIND $nodes AS node
        CALL {
          WITH node
          WITH node WHERE node.label = "Need"
          CREATE (n:FinancialPlanningGraph:Need {
            id: node.id,
            name: node.name,
            description: node.description
          })
        }
        CALL {
          WITH node
          WITH node WHERE node.label = "Subneed"
          CREATE (n:FinancialPlanningGraph:Subneed {
            id: node.id,
            name: node.name,
            description: node.description
          })
        }
        CALL {
          WITH node
          WITH node WHERE node.label = "Task"
          CREATE (n:FinancialPlanningGraph:Task {
            id: node.id,
            name: node.name,
            description: node.description
          })
        }
        """,
        {"nodes": nodes},
    )

    run_cypher(
        endpoint,
        args.user,
        args.password,
        """
        UNWIND $relationships AS rel
        MATCH (from:FinancialPlanningGraph {id: rel.source})
        MATCH (to:FinancialPlanningGraph {id: rel.target})
        CALL {
          WITH rel, from, to
          WITH rel, from, to WHERE rel.type = "HAS_SUBNEED"
          CREATE (from)-[:HAS_SUBNEED]->(to)
        }
        CALL {
          WITH rel, from, to
          WITH rel, from, to WHERE rel.type = "HAS_TASK"
          CREATE (from)-[:HAS_TASK]->(to)
        }
        """,
        {"relationships": relationships},
    )

    print(f"Imported {len(nodes)} nodes and {len(relationships)} relationships.")


def parse_args() -> argparse.Namespace:
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "http://localhost:7474"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        import_graph(parse_args())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
