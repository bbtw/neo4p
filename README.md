# KG Viewer

Read-only viewer for a financial planning task graph backed by Neo4j.

## Graph Model

The current model has three node labels:

- `Need`
- `Subneed`
- `Task`

The current model has two relationship types:

- `(:Need)-[:HAS_SUBNEED]->(:Subneed)`
- `(:Subneed)-[:HAS_TASK]->(:Task)`

A need can also connect directly to a broad task:

- `(:Need)-[:HAS_TASK]->(:Task)`

Imported nodes also receive the shared `FinancialPlanningGraph` label so the import script can replace this graph without touching unrelated Neo4j data.

## Import Into Neo4j

Set credentials for your local Neo4j instance:

```sh
export NEO4J_URI="http://localhost:7474"
export NEO4J_DATABASE="neo4j"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your-password"
```

Preview the seed import:

```sh
uv run kg-import-graph --dry-run
```

Import the graph:

```sh
uv run kg-import-graph
```

## Run The Viewer

Start the local server:

```sh
uv run kg-viewer
```

Open:

```text
http://127.0.0.1:8000
```

The viewer reads from Neo4j through the local Python API. If the graph does not load, check that Neo4j is running, the graph has been imported, and the `NEO4J_*` environment variables match your local credentials.

The old script path still works for direct Python usage:

```sh
uv run python scripts/import_graph.py --dry-run
```
