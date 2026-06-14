# GraphViewer

GraphViewer is a local financial planning knowledge graph viewer backed by Neo4j.

The project models planning work as reusable graph nodes instead of a single
tree. A task can belong to more than one planning context, which matters for
real planning workflows. For example, `Review beneficiary designations` can be
part of estate planning, life insurance, and retirement savings. `Update
customer profile` can support cash flow, retirement readiness, and estate
planning.

The browser UI is a two-tier card board:

- **Overview**: a summary card followed by one column per planning need, each
  showing its subneeds with a proportional task-count bar. Click any need column
  to drill in.
- **Need detail**: the selected need's subneeds become columns of task cards.
  A breadcrumb at the top lets you return to the overview or jump directly to
  another need with the ▾ switcher.

## Interacting With The Board

- Click a need column on the overview to open its detail view.
- Click a task card to open the detail drawer on the right. The drawer shows
  every need the task belongs to, with color-coded dots. Click **Go →** on any
  other need to jump there and scroll the task into view.
- Tasks that appear in more than one need show colored dots labeled **Also in**
  directly on the card.
- Close the drawer by clicking **✕**, pressing `Esc`, or clicking empty
  board space.
- Open the command palette with `⌘K` (or `Ctrl+K`) to search across needs,
  subneeds, and tasks. Selecting a result navigates directly to it.

## Graph Model

The graph has three node labels:

- `Need`: a broad planning domain, such as Cash Flow, Tax, or Estate.
- `Subneed`: a more specific planning area within a need.
- `Task`: a reusable planning action.

Relationship types:

- `(:Need)-[:HAS_SUBNEED]->(:Subneed)`
- `(:Need)-[:HAS_TASK]->(:Task)`
- `(:Subneed)-[:HAS_TASK]->(:Task)`

The seed file is graph-native JSON with top-level `nodes` and `relationships`
lists:

```json
{
  "nodes": [
    {
      "id": "review_beneficiary_designations",
      "label": "Task",
      "name": "Review beneficiary designations",
      "description": ""
    }
  ],
  "relationships": [
    {
      "source": "estate_planning",
      "target": "review_beneficiary_designations",
      "type": "HAS_TASK"
    }
  ]
}
```

Use multiple `HAS_TASK` relationships when one task belongs to multiple needs
or subneeds. The board shows that task under each parent; the graph still
treats it as one node with multiple incoming edges.

Imported nodes also receive the shared `FinancialPlanningGraph` label so the
import script can replace this graph without touching unrelated Neo4j data.

## Setup

Install dependencies with `uv`, then create a local environment file:

```sh
cp .env.example .env
```

Edit `.env` with your local Neo4j settings:

```text
NEO4J_URI=http://localhost:7474
NEO4J_DATABASE=neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=change-me
KG_VIEWER_HOST=127.0.0.1
KG_VIEWER_PORT=8000
```

## Run The Viewer

Start the local server:

```sh
./run.sh
```

The run script reads `KG_VIEWER_PORT` from `.env`, stops any existing listener
on that port, then starts the viewer.

Open:

```text
http://127.0.0.1:8000
```

The viewer reads from Neo4j through the local Python API. If the graph does not
load, check that Neo4j is running, the graph has been imported, and the
`NEO4J_*` environment variables match your local credentials.

## Import And Export

Preview the seed import without writing to Neo4j:

```sh
uv run kg-import-graph --dry-run
```

Import `data/financial-planning-graph.json` into Neo4j:

```sh
uv run kg-import-graph
```

Export the current Neo4j graph back to the same JSON format:

```sh
uv run kg-export-graph --output data/financial-planning-graph.json
```

Omit `--output` to print the JSON to stdout:

```sh
uv run kg-export-graph
```

The old script paths still work for direct Python usage:

```sh
uv run python scripts/import_graph.py --dry-run
uv run python scripts/export_graph.py --output data/financial-planning-graph.json
```

## UI Graph Actions

The toolbar `···` overflow menu includes three graph operation buttons:

- `Load JSON`: replaces the Neo4j planning graph with `data/financial-planning-graph.json`.
- `Export JSON`: downloads the current Neo4j graph as `financial-planning-graph.json`.
- `Wipe Graph`: deletes only nodes labeled `FinancialPlanningGraph`.

`Load JSON` and `Wipe Graph` are destructive for this app graph, so the browser
asks for confirmation before running them.
