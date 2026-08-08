# neo4p

Validation pipeline for a Neo4j graph: snapshot it out of Neo4j, check it
against a committed baseline (`expectations.yaml`), and gate any change to
the graph on that check passing before it ships.

## Setup

```
uv sync
```

## Scripts — what each produces and checks

| Script | Reads | Produces | Checks |
|---|---|---|---|
| `snapshot.py` | live Neo4j (Bolt) | `graph.graphml`, `manifest.json` (when, source, HEAD commit, sha256) | nothing — export only |
| `bootstrap.py` | a `graph.graphml` | a draft `expectations.yaml` | derives entries/terminals from topology, enumerates `approved_paths`, mines candidate `rules`. Aborts on structural problems (e.g. a cycle); refuses to overwrite an existing file |
| `verify_baseline.py` | a draft `expectations.yaml` + live Neo4j (Bolt) | pass/fail to stdout | independently confirms the draft's entries/terminals match live degree structure, every approved-path step has a real edge, and no live task is missing — never reads the graphml |
| `validate.py` | a `graph.graphml` + `expectations.yaml` | `paths.json` (every structural route found), `validation.json` (pass/fail report) | four layers: structural, path enumeration, rule invariants, named scenarios. Exit 1 on any failure |
| `diff_baseline.py` | a new `graph.graphml` + the committed `expectations.yaml` | `change_report.md`, and with `--update` a new `expectations.yaml` | which client journeys were added/removed, entry/terminal changes, whether added journeys violate a baseline rule or reroute a scenario. Exit 0 = no delta, exit 1 = delta to review |
| `mine_rules.py` | a `graph.graphml` | candidate `rules` | used internally by `bootstrap.py`; can also be run standalone to re-mine rules for review |

Every script takes a `graph.graphml` path as input. That file has to come
from `snapshot.py` against a real Neo4j instance, or be a graphml you place
there yourself — nothing in this pipeline fabricates a graph.

## The full lifecycle

### 0. Where you start: a live graph, no baseline

You have a graph in Neo4j and no `expectations.yaml`. There's nothing to
validate against yet, so the only place to start is trusting today's graph:
whatever it currently does is treated as correct, and gets captured as the
baseline. "Bootstrapping" here means recording what the graph does today,
not judging whether it should.

### 1. Capture the baseline (one-time)

```
cd src

# a. export the live graph — writes manifest.json (counts + sha256)
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... uv run python snapshot.py

# b. derive a draft baseline from that export
uv run python bootstrap.py snapshots/<timestamp>/graph.graphml
# writes snapshots/<timestamp>/expectations.yaml

# c. independently verify the draft against the live graph, bypassing the export
NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... uv run python verify_baseline.py snapshots/<timestamp>/expectations.yaml
```

Use `snapshot.py` for the export, not APOC or Neo4j Browser — the pipeline
expects its attribute conventions (`labels`, `rel`), and a foreign export
produces a well-formed draft of the wrong graph.

Steps (a)–(c) go through three different code paths on purpose, so they
cross-check each other. If `verify_baseline.py` fails, stop — don't freeze
a draft that doesn't match the live graph, investigate the mismatch first.

### 2. Freeze it

Commit the verified `expectations.yaml` wherever you keep things under
change control — git, versioned object storage, your firm's
change-management system. This file is now **the baseline**: everything
from here on is checked against it. Keep `manifest.json` alongside it; its
sha256 pins exactly which graph export the baseline mirrors.

Optional hardening, not required to have a working baseline: read through
`approved_paths` and the mined `rules` once as a human audit of the existing
graph, and add rules the graph should follow but doesn't currently violate,
plus hand-written `scenarios` — concrete client profiles pinned to a
required step sequence. `bootstrap.py` can't derive scenarios from topology
alone.

### 3. Ongoing: gate every deploy against the baseline

From here on, run this wherever a graph change could actually reach a
client — a deployment step, or a scheduled snapshot-and-validate job that
also catches out-of-band edits made directly in Neo4j:

```
cd src
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... uv run python snapshot.py
uv run python validate.py snapshots/<timestamp>/graph.graphml expectations.yaml
```

`paths.json` and `validation.json` are written into the snapshot directory.
Exit 1 blocks the deploy.

### 4. When you intend to change the graph

Don't hand-edit `expectations.yaml` to match a new graph — review the
change first:

```
cd src
# export the new graph version, then:
uv run python diff_baseline.py snapshots/<new>/graph.graphml <path to committed expectations.yaml> --update
```

This writes `change_report.md`: which client journeys the change added,
which previously approved journeys are no longer possible, any
entry/terminal changes, and whether the added journeys violate a baseline
rule or reroute a scenario. `--update` also writes a new draft
`expectations.yaml` — `approved_paths`, entries, and terminals refreshed to
the new graph, `rules` and `scenarios` carried over untouched.

Review loop:

1. Read `change_report.md` — it lists exactly what changed and nothing else.
2. Intended → promote the updated `expectations.yaml` to be the new
   baseline (replacing the file from step 2), and retain the report with
   your approval as the sign-off record.
3. Not intended → fix the graph, re-run.

Then go back to step 3: the new baseline is what every subsequent
`validate.py` run checks against.

None of this depends on git or GitHub — baselines are plain files pinned by
`manifest.json`'s sha256, and `change_report.md` is the change record.

## expectations.yaml

The file every validation run checks the graph against.

- `expected_entries` / `expected_terminals` — the exact entry points and the
  allowed set of dead ends.
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
