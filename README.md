# neo4p

Validation pipeline for a Neo4j graph: hand it a `graph.graphml` file, check
it against a committed baseline (`expectations.yaml`), and gate any change to
the graph on that check passing before it ships. Nothing in this pipeline
holds a live Neo4j connection — the graphml file on disk is the only input,
typically produced by running `apoc.export.graphml.*` inside Neo4j (Browser,
cypher-shell, or however you normally run Cypher against it).

## Setup

```
uv sync
```

## Scripts — what each produces and checks

| Script | Reads | Produces | Checks |
|---|---|---|---|
| `bootstrap.py` | a `graph.graphml` | a draft `expectations.yaml` | derives entries/terminals/`required_step_attrs` from topology, enumerates `approved_paths`, mines candidate `rules`. Aborts on structural problems (e.g. a cycle); refuses to overwrite an existing file |
| `validate.py` | a `graph.graphml` + `expectations.yaml` | `paths.json` (every structural route found), `validation.json` (pass/fail report) | four layers: structural, path enumeration, rule invariants, named scenarios. Exit 1 on any failure |
| `diff_baseline.py` | a new `graph.graphml` + the committed `expectations.yaml` | `change_report.md`, and with `--update` a new `expectations.yaml` | which client journeys were added/removed, entry/terminal changes, whether added journeys violate a baseline rule or reroute a scenario. Exit 0 = no delta, exit 1 = delta to review |
| `mine_rules.py` | a `graph.graphml` | candidate `rules` | used internally by `bootstrap.py`; can also be run standalone to re-mine rules for review |

Every script takes a `graph.graphml` path as input: a plain
`apoc.export.graphml.*` export (scoped query or whole-database, `useTypes`
on or off), or any other graphml you place there yourself — nothing in this
pipeline fabricates a graph. `validate.normalize_graph()` reconciles pure
export-format differences (which attribute holds the relationship type,
exporter-assigned vs. business node ids) before anything else runs; see
`tests/test_apoc_compat.py` for a worked example against a real APOC-shaped
export.

## The full lifecycle

### 0. Where you start: a live graph, no baseline

You have a graph in Neo4j and no `expectations.yaml`. There's nothing to
validate against yet, so the only place to start is trusting today's graph:
whatever it currently does is treated as correct, and gets captured as the
baseline. "Bootstrapping" here means recording what the graph does today,
not judging whether it should.

### 1. Capture the baseline (one-time)

```
# a. inside Neo4j, export the flow you want governed — scope the query to
#    just that flow, or export the whole database and let validate.py's
#    structural checks flag anything unscoped as an unexpected dead end:
CALL apoc.export.graphml.query(
  "MATCH (n)-[r]->(m) RETURN n, r, m", "graph.graphml", {useTypes: true}
)

# b. derive a draft baseline from that export
cd src
uv run python bootstrap.py path/to/graph.graphml
# writes expectations.yaml next to the graphml
```

`bootstrap.py` (via `validate.normalize_graph()`) works with APOC's own
attribute conventions directly — `label` for relationship type,
exporter-assigned node ids reconciled against each node's business `id`
property. No separate export step or foreign-format translation needed.

### 2. Freeze it

Commit the verified `expectations.yaml` — and the `graph.graphml` it was
drafted from — wherever you keep things under change control: git,
versioned object storage, your firm's change-management system. This file
is now **the baseline**: everything from here on is checked against it. If
you want a fixed pin on exactly which export it mirrors, record the
graphml's checksum yourself (e.g. `sha256sum graph.graphml`) alongside it.

Optional hardening, not required to have a working baseline: read through
`approved_paths` and the mined `rules` once as a human audit of the existing
graph, and add rules the graph should follow but doesn't currently violate,
plus hand-written `scenarios` — concrete client profiles pinned to a
required step sequence. `bootstrap.py` can't derive scenarios from topology
alone.

### 3. Ongoing: gate every deploy against the baseline

From here on, run this wherever a graph change could actually reach a
client — a deployment step, or a scheduled export-and-validate job that also
catches out-of-band edits made directly in Neo4j:

```
# re-run the same apoc.export.graphml.* call to get a fresh graph.graphml, then:
cd src
uv run python validate.py path/to/graph.graphml expectations.yaml
```

`paths.json` and `validation.json` are written next to the graphml.
Exit 1 blocks the deploy.

### 4. When you intend to change the graph

Don't hand-edit `expectations.yaml` to match a new graph — review the
change first:

```
# export the new graph version, then:
cd src
uv run python diff_baseline.py path/to/new-graph.graphml <path to committed expectations.yaml> --update
```

This writes `change_report.md`: which client journeys the change added,
which previously approved journeys are no longer possible, any
entry/terminal changes, and whether the added journeys violate a baseline
rule or reroute a scenario. `--update` also writes a new draft
`expectations.yaml` — `approved_paths`, entries, and terminals refreshed to
the new graph, `required_step_attrs`/`rules`/`scenarios` carried over
untouched.

Review loop:

1. Read `change_report.md` — it lists exactly what changed and nothing else.
2. Intended → promote the updated `expectations.yaml` (and the new
   `graph.graphml`) to be the new baseline, and retain the report with your
   approval as the sign-off record.
3. Not intended → fix the graph, re-export, re-run.

Then go back to step 3: the new baseline is what every subsequent
`validate.py` run checks against.

None of this depends on git or GitHub, or on Neo4j being reachable at
validation time — baselines are plain files, and `change_report.md` is the
change record.

## expectations.yaml

The file every validation run checks the graph against.

- `expected_entries` / `expected_terminals` — the exact entry points and the
  allowed set of dead ends.
- `required_step_attrs` — attributes every step node must carry (e.g.
  `rationale`, `source_doc`). Bootstrapped as whatever every current step
  happens to share, then hand-trimmed to what should actually be mandatory.
- `approved_paths` — every simple structural route the graph is allowed to
  contain.
- `rules` — precedence and mutual-exclusion invariants applied to enumerated
  routes on each run, including new routes introduced by future graph
  changes. Bootstrap candidates from a verified graph with `mine_rules.py`.
- `scenarios` — concrete client profiles with the step sequence they must
  produce. Always hand-written — `bootstrap.py` cannot derive these from
  topology.

See [docs/reference.html](docs/reference.html) for what each validator layer
actually checks and how a reviewer signs off on a graph with combinatorial
paths.
