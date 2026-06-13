#!/usr/bin/env python3
"""Serve the financial planning graph viewer and Neo4j-backed API."""

import argparse
import base64
import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from kg_viewer.config import ROOT, load_local_env
from kg_viewer.import_graph import DEFAULT_SEED, flatten_graph, load_seed

STATIC_DIR = ROOT / "static"


class Neo4jClient:
    def __init__(self, uri: str, database: str, user: str, password: str) -> None:
        self.endpoint = f"{uri.rstrip('/')}/db/{database}/tx/commit"
        self.user = user
        self.password = password

    def query(self, statement: str, parameters: dict | None = None) -> list[dict]:
        payload = {
            "statements": [
                {
                    "statement": statement,
                    "parameters": parameters or {},
                    "resultDataContents": ["row"],
                }
            ]
        }
        token = base64.b64encode(f"{self.user}:{self.password}".encode("utf-8")).decode(
            "ascii"
        )
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Neo4j HTTP error {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not connect to Neo4j: {error.reason}") from error

        errors = data.get("errors", [])
        if errors:
            raise RuntimeError(errors)

        results = data.get("results", [])
        if not results:
            return []
        return [item["row"] for item in results[0].get("data", [])]

    def graph(self) -> dict:
        rows = self.query(
            """
            MATCH (n:FinancialPlanningGraph)
            OPTIONAL MATCH (n)-[r:HAS_SUBNEED|HAS_TASK]->(m:FinancialPlanningGraph)
            RETURN collect(DISTINCT {
              id: n.id,
              name: n.name,
              description: n.description,
              labels: labels(n)
            }) AS nodes,
            collect(DISTINCT {
              source: n.id,
              target: m.id,
              type: type(r)
            }) AS relationships
            """
        )
        if not rows:
            return {"nodes": [], "relationships": [], "hierarchy": []}

        nodes = rows[0][0]
        relationships = [
            relationship
            for relationship in rows[0][1]
            if relationship.get("target") is not None
        ]
        return {
            "nodes": sorted(nodes, key=lambda node: (node_type(node), node["name"])),
            "relationships": sorted(
                relationships,
                key=lambda relationship: (
                    relationship["type"],
                    relationship["source"],
                    relationship["target"],
                ),
            ),
            "hierarchy": build_hierarchy(nodes, relationships),
        }

    def node(self, node_id: str) -> dict | None:
        rows = self.query(
            """
            MATCH (n:FinancialPlanningGraph {id: $id})
            OPTIONAL MATCH (parent:FinancialPlanningGraph)-[incoming:HAS_SUBNEED|HAS_TASK]->(n)
            OPTIONAL MATCH (n)-[outgoing:HAS_SUBNEED|HAS_TASK]->(child:FinancialPlanningGraph)
            RETURN {
              id: n.id,
              name: n.name,
              description: n.description,
              labels: labels(n),
              parents: collect(DISTINCT {
                id: parent.id,
                name: parent.name,
                relationship: type(incoming)
              }),
              children: collect(DISTINCT {
                id: child.id,
                name: child.name,
                relationship: type(outgoing)
              })
            } AS node
            """,
            {"id": node_id},
        )
        if not rows:
            return None
        node = rows[0][0]
        node["parents"] = [item for item in node["parents"] if item.get("id")]
        node["children"] = [item for item in node["children"] if item.get("id")]
        return node

    def wipe_graph(self) -> None:
        self.query("MATCH (n:FinancialPlanningGraph) DETACH DELETE n")

    def import_seed(self, seed_path: Path) -> dict:
        seed = load_seed(seed_path)
        nodes, relationships = flatten_graph(seed)
        self.wipe_graph()
        self.query(
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
        self.query(
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
        return {"nodes": len(nodes), "relationships": len(relationships)}

    def export_seed(self) -> dict:
        nodes = [
            row[0]
            for row in self.query(
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
            for row in self.query(
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


def node_type(node: dict) -> str:
    labels = set(node.get("labels", []))
    if "Need" in labels:
        return "Need"
    if "Subneed" in labels:
        return "Subneed"
    if "Task" in labels:
        return "Task"
    return "Node"


def build_hierarchy(nodes: list[dict], relationships: list[dict]) -> list[dict]:
    by_id = {node["id"]: {**node, "type": node_type(node)} for node in nodes}
    children_by_parent: dict[str, list[dict]] = {}
    for relationship in relationships:
        children_by_parent.setdefault(relationship["source"], []).append(
            {
                **by_id[relationship["target"]],
                "relationship": relationship["type"],
            }
        )

    needs = [node for node in by_id.values() if node["type"] == "Need"]
    hierarchy = []
    for need in sorted(needs, key=lambda item: item["name"]):
        need_children = children_by_parent.get(need["id"], [])
        subneeds = []
        direct_tasks = []
        for child in sorted(need_children, key=lambda item: (item["type"], item["name"])):
            if child["type"] == "Subneed":
                child["tasks"] = sorted(
                    children_by_parent.get(child["id"], []),
                    key=lambda item: item["name"],
                )
                subneeds.append(child)
            elif child["type"] == "Task":
                direct_tasks.append(child)
        hierarchy.append({**need, "subneeds": subneeds, "tasks": direct_tasks})
    return hierarchy


class ViewerHandler(SimpleHTTPRequestHandler):
    client: Neo4jClient

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/graph":
            try:
                self.write_json(self.client.graph())
            except RuntimeError as error:
                self.write_json({"error": str(error)}, status=502)
            return
        if self.path == "/api/graph/export":
            try:
                self.write_json(self.client.export_seed())
            except RuntimeError as error:
                self.write_json({"error": str(error)}, status=502)
            return
        if self.path.startswith("/api/nodes/"):
            node_id = unquote(self.path.removeprefix("/api/nodes/"))
            try:
                node = self.client.node(node_id)
            except RuntimeError as error:
                self.write_json({"error": str(error)}, status=502)
                return
            if node is None:
                self.write_json({"error": "node not found"}, status=404)
                return
            self.write_json(node)
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/graph/wipe":
            try:
                self.client.wipe_graph()
            except RuntimeError as error:
                self.write_json({"error": str(error)}, status=502)
                return
            self.write_json({"status": "ok"})
            return
        if self.path == "/api/graph/import":
            try:
                counts = self.client.import_seed(DEFAULT_SEED)
            except (RuntimeError, ValueError) as error:
                self.write_json({"error": str(error)}, status=502)
                return
            self.write_json({"status": "ok", **counts})
            return
        self.write_json({"error": "not found"}, status=404)

    def write_json(self, value: dict, status: int = 200) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        print(format % args)


def parse_args() -> argparse.Namespace:
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("KG_VIEWER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("KG_VIEWER_PORT", "8000")))
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "http://localhost:7474"))
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ViewerHandler.client = Neo4jClient(
        args.neo4j_uri,
        args.neo4j_database,
        args.neo4j_user,
        args.neo4j_password,
    )
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    print(f"Serving viewer at http://{args.host}:{args.port}")
    print(f"Using Neo4j at {args.neo4j_uri}, database {args.neo4j_database}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
