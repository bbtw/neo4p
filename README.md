# neo4p

Snapshot a Neo4j planning graph to GraphML and validate it: structural checks,
every client journey the graph can produce, and known client scenarios.

## Setup

```
uv sync
```

## Usage

Without Neo4j, using a generated sample graph:

```
cd src
uv run python make_sample_graph.py
uv run python validate.py snapshots/sample/graph.graphml expectations.yaml
```

Against a real Neo4j instance:

```
cd src
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... uv run python snapshot.py
uv run python validate.py snapshots/<timestamp>/graph.graphml expectations.yaml
```

`validate.py` writes `paths.json` (every client journey) and `validation.json`
(pass/fail report) into the snapshot directory, and exits 1 on failure, so it
is safe to run in CI.
