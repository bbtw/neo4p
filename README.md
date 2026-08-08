# neo4p

Validation pipeline for a Neo4j graph: snapshot it out of Neo4j, check it
against a committed baseline (`expectations.yaml`), and gate any change to
the graph on that check passing before it ships.

## Scripts — what each produces and checks

| Script | Reads | Produces | Checks |
|---|---|---|---|
| `snapshot.py` | live Neo4j (Bolt) | `graph.graphml`, `manifest.json` (when, source, HEAD commit, sha256) | nothing — export only |
| `validate.py` | a `graph.graphml` + `expectations.yaml` | `paths.json` (every structural route found), `validation.json` (pass/fail report) | four layers: structural, path enumeration, rule invariants, named scenarios. Exit 1 on any failure |
| `bootstrap.py` | a `graph.graphml` | a draft `expectations.yaml` | derives entries/terminals from topology, enumerates `approved_paths`, mines candidate `rules`. Aborts on structural problems (e.g. a cycle); refuses to overwrite an existing file |
| `verify_baseline.py` | a draft `expectations.yaml` + live Neo4j (Bolt) | pass/fail to stdout | independently confirms the draft's entries/terminals match live degree structure, every approved-path step has a real edge, and no live task is missing — never reads the graphml |
| `diff_baseline.py` | a new `graph.graphml` + the committed `expectations.yaml` | `change_report.md`, and with `--update` a new `expectations.yaml` | which client journeys were added/removed, entry/terminal changes, whether added journeys violate a baseline rule or reroute a scenario. Exit 0 = no delta, exit 1 = delta to review |
| `mine_rules.py` | a `graph.graphml` | candidate `rules` | used internally by `bootstrap.py`; can also be run standalone to re-mine rules for review |

## Order of operations

**First time (no `expectations.yaml` yet):** `snapshot.py` → `bootstrap.py`
→ `verify_baseline.py` → freeze the result as the committed baseline. See
"Bootstrapping" below.

**Every deploy / scheduled check (baseline already exists):** `snapshot.py`
→ `validate.py` against the committed `expectations.yaml`. Exit 1 blocks
the deploy.

**Reviewing a graph change (baseline already exists):** `snapshot.py` on
the new graph → `diff_baseline.py` against the committed `expectations.yaml`
→ review `change_report.md` → if approved, promote the `--update`d
`expectations.yaml` to be the new baseline. See "Signing off" below.

## Setup

```
uv sync
```

## Usage

Every script takes a `graph.graphml` path as input. That file has to come
from `snapshot.py` against a real Neo4j instance, or be a graphml you place
there yourself — nothing in this pipeline fabricates a graph.

```
cd src
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... uv run python snapshot.py
uv run python validate.py snapshots/<timestamp>/graph.graphml expectations.yaml
```

`paths.json` and `validation.json` are written into the snapshot directory.

## Bootstrapping: a complete baseline of the live graph

Cold start — you have a live graph but no expectations.yaml. The goal is a
complete, verified record of what the graph does today. Four steps, the first
three through different code paths so they cross-check each other:

```
cd src
# 1. export the live graph (writes manifest.json with counts + sha256)
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... uv run python snapshot.py

# 2. derive the baseline from the snapshot
uv run python bootstrap.py snapshots/<timestamp>/graph.graphml

# 3. cross-check the baseline against the live graph, bypassing the export
NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... uv run python verify_baseline.py snapshots/<timestamp>/expectations.yaml

# 4. freeze it: designate this file as the current baseline in whatever
#    controlled store you use (the manifest's sha256 pins the graph it mirrors)
```

Export with `snapshot.py`, not APOC or Neo4j Browser — the pipeline expects
its attribute conventions (`labels`, `rel`), and a foreign export produces a
well-formed draft of the wrong graph. `bootstrap.py` reuses `validate.py`'s
and `mine_rules.py`'s own functions, so the draft is by construction what
validation would compute.

After step 4 the baseline is complete for its purpose: `approved_paths` is an
exhaustive record of every route in today's graph, so any future change —
edge added, node removed, route created — fails validation as a path diff.
The baseline is descriptive: it records whatever the graph currently does,
bugs included, and validating the same graph against it passes by
construction. From here, every future graph version is reviewed as a delta
against this file (see below).

Optional hardening, separate from capturing the baseline: read the paths and
mined rules once as an audit of the existing graph, and add what the miner
cannot derive from today's topology — rules the graph currently violates,
rules about steps that don't exist yet, and `scenarios` pinning which branch
a given client profile must take.

## Signing off on graph changes

Once the baseline is committed, every new graph version is reviewed as a
delta against it — never by re-reading the full path list:

```
cd src
# export the new graph version, then:
uv run python diff_baseline.py snapshots/<new>/graph.graphml <committed expectations.yaml> --update
```

With `--update` it also writes a new `expectations.yaml` — `approved_paths`,
entries, and terminals updated to the new graph, rules and scenarios carried
over untouched. The sign-off loop is:

1. review `change_report.md` — it lists exactly what changed and nothing else;
2. if the changes are intended, promote the updated `expectations.yaml` to be
   the new current baseline, and retain the report with the approval in your
   change-management process — report + approval is the sign-off record;
3. if not, fix the graph and re-run.

None of this depends on git or GitHub: baselines are plain files pinned by
the manifest's sha256, and the report is the change record. `validate.py`
stays the mechanical gate — run it against the current baseline wherever
graph changes actually happen (a deployment step, or a scheduled
snapshot-and-validate job that catches out-of-band edits to the live graph
as drift). It exits 1 on any deviation, forcing every change through this
review loop.

## expectations.yaml

The file every validation run checks the graph against. Kept under change
control — git, versioned object storage, or your firm's change-management
system — so a graph change that breaks an expected recommendation fails
validation instead of reaching a client.

- `expected_entries` / `expected_terminals` — the exact entry points and the
  allowed set of dead ends.
- `approved_paths` — every simple structural route the graph is allowed to
  contain.
- `rules` — precedence and mutual-exclusion invariants applied to enumerated
  routes on each run, including new routes introduced by future graph changes.
  Bootstrap candidates from a verified graph with `mine_rules.py`.
- `scenarios` — concrete client profiles with the step sequence they must
  produce. Always hand-written — `bootstrap.py` cannot derive these from
  topology.

See [docs/reference.html](docs/reference.html) for what each validator layer
actually checks and how a reviewer signs off on a graph with combinatorial
paths.
