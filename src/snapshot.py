"""
Pull the planning graph out of Neo4j and write a dated, hashed snapshot.

Output layout:
    snapshots/20260806T142301Z/
        graph.graphml    <- the frozen graph
        manifest.json    <- when, where from, what code, and a SHA-256 of the graph

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... python snapshot.py
"""

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
from neo4j import Driver, GraphDatabase

NODE_QUERY = """
MATCH (n:Step)
RETURN n.id AS id, labels(n) AS labels, properties(n) AS props
"""

# Queried separately from nodes so that isolated steps are not silently dropped.
EDGE_QUERY = """
MATCH (a:Step)-[r]->(b:Step)
RETURN a.id AS src, b.id AS dst, type(r) AS rel, properties(r) AS props
"""


def clean(props: dict) -> dict:
    """GraphML only stores scalars. Drop nulls, join lists, keep numbers as numbers."""
    out = {}
    for key, value in props.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            out[key] = ";".join(str(v) for v in value)
        else:
            out[key] = value
    return out


def fetch_graph(driver: Driver) -> nx.DiGraph:
    graph = nx.DiGraph()

    with driver.session() as session:
        for rec in session.run(NODE_QUERY):
            if rec["id"] is None:
                raise ValueError(f"Step node has no id (labels={rec['labels']})")
            graph.add_node(
                rec["id"],
                labels=";".join(rec["labels"]),
                **clean(rec["props"]),
            )

        for rec in session.run(EDGE_QUERY):
            for end in (rec["src"], rec["dst"]):
                if end not in graph:
                    raise ValueError(f"Edge references unknown node id: {end!r}")
            graph.add_edge(
                rec["src"],
                rec["dst"],
                rel=rec["rel"],
                **clean(rec["props"]),
            )

    return graph


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def write_snapshot(
    graph: nx.DiGraph, uri: str, root: Path = Path("snapshots")
) -> tuple[Path, dict]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = root / stamp
    outdir.mkdir(parents=True, exist_ok=True)

    graphml = outdir / "graph.graphml"
    nx.write_graphml(graph, graphml)

    manifest = {
        "captured_at_utc": stamp,
        "source_uri": uri,
        "script_commit": git_commit(),
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "graphml_sha256": hashlib.sha256(graphml.read_bytes()).hexdigest(),
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    return outdir, manifest


def main() -> None:
    uri = os.environ["NEO4J_URI"]
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])

    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        graph = fetch_graph(driver)
    finally:
        driver.close()

    outdir, manifest = write_snapshot(graph, uri)
    print(f"wrote {outdir}")
    print(f"  {manifest['node_count']} nodes, {manifest['edge_count']} edges")
    print(f"  sha256 {manifest['graphml_sha256']}")


if __name__ == "__main__":
    main()
