# neo4p

Pulls a Neo4j planning graph — the graph that decides which financial-planning
tasks get suggested to a client — snapshots it to GraphML, and validates it
before it's allowed to influence what a real customer sees.

See [docs/reference.html](docs/reference.html) for the full writeup: why this
exists, how the KG could support a planning digital assistant and semantic
layer, why a graph complements a rules engine, what each validator layer
checks, and how a reviewer signs off on a graph with combinatorial paths.

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
The same knowledge could support a planning digital assistant backed by a
governed planning semantic layer: the KG supplies ordered, explainable planning
context, while a service maps customer facts and exposes approved business
queries.
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
can serve as a mechanical gate in whatever process governs graph changes.

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
well-formed draft of the wrong graph.

`bootstrap.py` derives entries and terminals from the topology, enumerates
every path into `approved_paths`, and mines candidate `rules` — reusing
`validate.py`'s and `mine_rules.py`'s own functions, so the draft is by
construction what validation would compute. It aborts on structural problems
(e.g. a cycle) and refuses to overwrite an existing file.

`verify_baseline.py` is the independent check: it queries the live graph over
Bolt — never reading the graphml — and confirms the draft's entries and
terminals match the live degree structure, every approved-path step has a
real edge, and no live task is missing from the path list (the signature of
a stale or partial export).

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

`diff_baseline.py` writes `change_report.md` next to the new snapshot: which
client journeys the change added, which previously approved journeys are no
longer possible, any entry/terminal changes, and whether the added journeys
violate a baseline rule or reroute a baseline scenario. Exit 0 means the
graph is unchanged from the baseline; exit 1 means there is a delta to review.

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
