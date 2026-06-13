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

The seed file is graph-native JSON with top-level `nodes` and `relationships` lists. Use multiple `HAS_TASK` relationships when a task belongs to multiple needs or subneeds.

Imported nodes also receive the shared `FinancialPlanningGraph` label so the import script can replace this graph without touching unrelated Neo4j data.

## Import Into Neo4j

Set credentials for your local Neo4j instance:

```sh
cp .env.example .env
```

Then edit `.env` with your local Neo4j password.

Preview the seed import:

```sh
uv run kg-import-graph --dry-run
```

Import the graph:

```sh
uv run kg-import-graph
```

Export the graph from Neo4j in the same JSON format:

```sh
uv run kg-export-graph --output data/financial-planning-graph.json
```

Omit `--output` to print the JSON to stdout.

## Run The Viewer

Start the local server:

```sh
uv run kg-viewer
```

Or use the repo run script:

```sh
./run.sh
```

The script reads `KG_VIEWER_PORT` from `.env`, stops any existing listener on that port, then starts the viewer.

Open:

```text
http://127.0.0.1:8000
```

The viewer reads from Neo4j through the local Python API. If the graph does not load, check that Neo4j is running, the graph has been imported, and the `NEO4J_*` environment variables match your local credentials.

The old script path still works for direct Python usage:

```sh
uv run python scripts/import_graph.py --dry-run
uv run python scripts/export_graph.py --output data/financial-planning-graph.json
```
