# neo4p

Pulls a Neo4j planning graph — the graph that decides which financial-planning
tasks get suggested to a client — snapshots it to GraphML, and validates it
before it's allowed to influence what a real customer sees.

See [docs/reference.html](docs/reference.html) for the full writeup: why this
exists, the advisor-copilot opportunity and semantic-layer framing, future
applications, why a graph complements a rules engine, what each validator
layer checks, and how a reviewer signs off on a graph with combinatorial paths.

## Why this exists

The graph is a directed planning workflow of tasks (build emergency fund → pay down
high-interest debt → capture the 401k match → ...), connected by `HAS_CHILD`
edges. Where a task's next step depends on the client, `CRITERIA_BRANCH`
edges — each carrying a `condition_key`/`condition_value` — fan out from that
task to a `CriteriaNode` per branch, and each criteria node's `HAS_CHILD`
edge points at the task that branch resolves to. Walking the graph from an
entry point for a given client produces the ordered task list they're shown.
Neo4j stores this planning knowledge graph, not customer records. Today it
powers the firm's next-best-message application: customer facts supplied at
traversal time filter the eligible task candidates, and the customer's current
step plus the graph's ordering determine which candidate should come next.
The next proposed high-value use is an advisor copilot backed by a governed
planning semantic layer: the KG supplies ordered, explainable planning context,
while a service maps customer facts and exposes approved business queries.
Because this output reaches real customers, a bad edge, a missing
precondition, or an accidental new route through the graph is a compliance
and trust problem, not just a bug.

`validate.py` exists to catch that before a graph change ships, not after a
client has acted on it.

## Pipeline

```
Neo4j --snapshot.py--> snapshots/<timestamp>/graph.graphml
                        + manifest.json  (when, source, HEAD commit, sha256)
                               |
                               v
                        validate.py  (checked against expectations.yaml)
                               |
                               +--> paths.json        structural routes found
                               +--> validation.json   pass/fail report
```

`make_sample_graph.py` builds a small graph directly, no Neo4j required, so
the pipeline can be run and understood end to end.

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

`validate.py` runs four complementary layers — structural, path enumeration,
rule invariants, and named scenarios — against `expectations.yaml`, then
writes `paths.json` (every structural route found) and `validation.json`
(pass/fail report) into the snapshot directory. It exits 1 on failure, so it
can serve as a CI gate; this repository's workflow applies that gate to the
generated sample graph.

## expectations.yaml

The file every validation run checks the graph against. Kept in version
control next to the code, so a graph change that breaks an expected
recommendation fails the build instead of reaching a client.

- `expected_entries` / `expected_terminals` — the exact entry points and the
  allowed set of dead ends.
- `approved_paths` — every simple structural route the graph is allowed to
  contain.
- `rules` — precedence and mutual-exclusion invariants applied to enumerated
  routes on each run, including new routes introduced by future graph changes.
  Bootstrap candidates from a verified graph with `mine_rules.py`.
- `scenarios` — concrete client profiles with the step sequence they must
  produce.

See [docs/reference.html](docs/reference.html) for what each validator layer
actually checks and how a reviewer signs off on a graph with combinatorial
paths.
