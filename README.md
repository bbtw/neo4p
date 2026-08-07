# neo4p

Pulls a Neo4j planning graph — the graph that decides which financial-planning
tasks get suggested to a client — snapshots it to GraphML, and validates it
before it's allowed to influence what a real customer sees.

See [docs/reference.html](docs/reference.html) for the full writeup: why this
exists, why a graph and not a rules engine like Drools, what each validator
layer checks, and how a reviewer signs off on a graph with combinatorial
paths.

## Why this exists

The graph is a directed sequence of steps (build emergency fund → pay down
high-interest debt → capture the 401k match → ...), where each edge is a
condition on a client's profile. Walking the graph from an entry point for a
given client produces the ordered task list they're shown. Because this
output reaches real customers, a bad edge, a missing precondition, or an
accidental new route through the graph is a compliance and trust problem, not
just a bug.

`validate.py` exists to catch that before a graph change ships, not after a
client has acted on it.

## Pipeline

```
Neo4j --snapshot.py--> snapshots/<timestamp>/graph.graphml
                        + manifest.json  (when, source, script commit, sha256)
                               |
                               v
                        validate.py  (checked against expectations.yaml)
                               |
                               +--> paths.json        every client journey found
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

`validate.py` runs four independent layers — structural, path enumeration,
rule invariants, and named scenarios — against `expectations.yaml`, then
writes `paths.json` (every client journey) and `validation.json` (pass/fail
report) into the snapshot directory. Exits 1 on failure, so it's safe to run
in CI.

## expectations.yaml

The file every validation run checks the graph against. Kept in version
control next to the code, so a graph change that breaks an expected
recommendation fails the build instead of reaching a client.

- `expected_entries` / `expected_terminals` — the only steps allowed to have
  no predecessor / no successor.
- `approved_paths` — every client journey the graph is allowed to produce.
- `rules` — precedence and mutual-exclusion invariants that cover journeys
  that don't exist yet, not just the ones enumerated today. Bootstrap
  candidates from a verified graph with `mine_rules.py`.
- `scenarios` — concrete client profiles with the step sequence they must
  produce.

See [docs/reference.html](docs/reference.html) for what each validator layer
actually checks and how a reviewer signs off on a graph with combinatorial
paths.
