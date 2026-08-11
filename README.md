# neo4p

Test, govern and manage small knowledge graphs. Point it at a graph export,
check it against a committed baseline, and gate any change on that check
passing before it ships.

Each graph you govern is described by **three files in a directory of its
own**, so graphs of different shapes can live side by side under one
pipeline:

```
graphs/
  sample/
    graph.graphml        what the graph is now (an APOC export)
    shape.yaml           how to read it — labels, branch rels, conditions
    expectations.yaml    what it is allowed to do — the committed baseline
  some-other-kg/
    graph.graphml
    shape.yaml           a completely different vocabulary; same pipeline
    expectations.yaml
```

Nothing here holds a live Neo4j connection. The graphml file on disk is the
only graph input, typically produced by `apoc.export.graphml.*` inside Neo4j.

## Setup

```
uv sync
```

## The shape file is the point

`shape.yaml` states in plain terms how to read one graph:

```yaml
step_labels:   [Task]           # nodes that are client-facing steps
branch_labels: [CriteriaNode]   # nodes that exist only to carry a condition
branch_rels:   [CRITERIA_BRANCH]

condition_key_attr:   condition_key    # names a client-profile field
condition_value_attr: condition_value  # the value it must equal

required_step_attrs:   [rationale, source_doc]
required_branch_attrs: [condition_key, condition_value]
```

Everything downstream hangs off these facts: what counts as a step, which
nodes get collapsed away before path checks, which nodes must carry
documentation. They used to be **inferred** from graph topology on every run.
They are now **declared**, and `validate.py` prints the shape it used before
printing a single result.

That change is the whole reason to trust the output. Under inference, a
single incidental edge property — a timestamp, a tracking id — could
reclassify a real client-facing step as a branch point. That step was then
deleted from the graph before path enumeration *and* exempted from
`required_step_attrs`, so a client-facing step could ship with no rationale
and no source document while validation reported zero failures. Both repro
cases are pinned as regression tests in `tests/test_shape.py`.

## propose_shape.py determines or refuses — it never guesses

Writing a shape file by hand for every graph is work, so `propose_shape.py`
derives what it can from the graph. Every field it emits is either
**determined** — backed by evidence that admits one reading — or
**UNRESOLVED**, left blank with the reason and the question you need to
answer. It never breaks a tie, never classifies from a sample of one, and
never takes the first of several candidates.

```
? condition value: 2 attributes differ between sibling branches —
  ['audit_ts', 'condition_value']. Any of them could be the value being
  matched; the rest are probably incidental (timestamps, weights, audit fields)

condition_value_attr: UNRESOLVED
```

A draft containing `UNRESOLVED` will not load. `validate.py` exits 2 and names
every field still outstanding, so a half-determined shape cannot reach a
deploy gate by being ignored.

Exit `0` = complete shape determined. Exit `1` = fields need your decision.
Exit `2` = could not read the graph.

The three things it refuses on, and why none of them are fixable by trying
harder:

- **A pass-through label with no fork.** A branch point that never branches
  and an ordinary intermediate step are the same shape. `risk_disclosure`,
  a real regulatory step that always sits between two others, is
  indistinguishable from a condition-carrier by topology alone.
- **Two attributes that both vary between siblings.** An audit timestamp on a
  branch edge varies exactly like the real condition value does.
- **A label sharing no attributes with the dominant step label.** That is what
  unrelated material from an unscoped export looks like — and also what a
  legitimately different kind of step looks like.

Even when it determines a complete shape, read it once: "determined from this
graph" is not "correct for your domain."

## Scripts

| Script | Reads | Produces |
|---|---|---|
| `propose_shape.py` | a `graph.graphml` | a draft `shape.yaml` plus the evidence behind each guess. Run once per new graph, then edit by hand |
| `bootstrap.py` | `graph.graphml` + `shape.yaml` | a draft `expectations.yaml`: entries, terminals, every enumerated path, and mined candidate rules |
| `validate.py` | all three files | `paths.json`, `validation.json`, and a pass/fail line per layer. Exit 1 on any failure |
| `diff_baseline.py` | a new `graph.graphml` + `shape.yaml` + the committed `expectations.yaml` | `change_report.md`, and with `--update` an `expectations.yaml.new` to promote |
| `mine_rules.py` | a `paths.json` | candidate rules, for re-mining outside bootstrap |

## What validate.py checks

Five layers, in order. Each reports whether it ran and what it found — a gate
that only ever prints failures gives you no way to tell "checked and clean"
from "never ran".

```
shape: graphs/sample/shape.yaml
  steps         = nodes labelled ['Task']
  branch points = nodes labelled ['CriteriaNode']
  branch rels   = ['CRITERIA_BRANCH']
  condition     = edge['condition_key'] names a profile field, edge['condition_value'] its value
  steps must carry  ['rationale', 'source_doc']
  branch edges must carry ['condition_key', 'condition_value']

  ok   shape      graph matches shape.yaml
  ok   structure  entries, terminals, reachability, required attributes
  ok   paths      every route is on the approved list
  ok   rules      declared invariants hold on every route
  ok   scenarios  known profiles walk their expected sequence

PASSED — 6 steps, 14 edges, 6 client journeys checked against 6 approved, 9 rules, 2 scenarios
```

0. **shape** — does the graph match what `shape.yaml` claims? Every node
   carries a declared label, every branch rel actually appears, every branch
   node has exactly one child. Runs first, and stops everything if it fails:
   later layers read the graph *through* the shape, so a shape that doesn't
   fit produces confident, meaningless results.
1. **structure** — acyclic, entries and terminals as expected, nothing
   unreachable, every step carrying its required documentation.
2. **paths** — enumerate every route a client could take; flag any route not
   on the approved list, and any approved route that has gone missing.
3. **rules** — check every route against declared invariants (precedence,
   mutual exclusion) rather than the exact path list, so routes that don't
   exist yet are covered too.
4. **scenarios** — do known client profiles walk the exact expected sequence?

Layers 2–4 reason only about steps: branch nodes are first collapsed into
plain step → step edges carrying their condition.

## Adding a graph

### 1. Export it

Scope the query to the flow you want governed, or export everything and let
layer 0 tell you what doesn't belong:

```cypher
CALL apoc.export.graphml.query(
  "MATCH (n)-[r]->(m) RETURN n, r, m", "graph.graphml", {useTypes: true}
)
```

### 2. Write its shape

```
mkdir -p graphs/my-kg && mv graph.graphml graphs/my-kg/
uv run python src/propose_shape.py graphs/my-kg/graph.graphml -o graphs/my-kg/shape.yaml
```

If it exits 0 it determined everything; read it once and commit. If it exits
1, it prints the specific questions it could not answer — answer them in the
file, replacing each `UNRESOLVED`. Nothing will load until you do.

One field needs a second look even at exit 0: `required_step_attrs`. Every
other field answers *what is this graph?* — a question the data can settle.
This one answers *what must a step have to be acceptable?*, which is your rule
about the graph, not a property of it. Derive it from the graph and the check
can never fail: you would be copying the answer key off the thing you are
testing.

So the tool fills it with what every step carries today — a starting point,
not a policy — and refuses to go further. In particular it will not quietly
drop a **near-miss**, an attribute most steps carry and one doesn't:

```
! near-miss 'source_doc': carried by 5 of 6 steps, missing from ['taxable_brokerage'].
  NOT added to required_step_attrs — decide whether that is a documentation
  gap to fix or genuinely optional
```

A near-miss is usually a documentation gap. Intersecting it away silently
would let the one undocumented step define the standard down for the other
five — the opposite of what you want, which is that step flagged.

### 3. Capture the baseline

```
uv run python src/bootstrap.py graphs/my-kg/graph.graphml graphs/my-kg/shape.yaml
```

The draft is **descriptive, not normative**: it approves whatever the graph
does today, bugs included, and catches nothing on day one. Reviewing it *is*
the audit of the existing graph. Read `approved_paths`, keep only the mined
`rules` you actually mean, and hand-write `scenarios` — concrete client
profiles pinned to a required step sequence. Those cannot be derived from
topology, and they are the layer that says what the graph is *for*.

### 4. Freeze it

Commit `shape.yaml` and `expectations.yaml` — and the `graph.graphml` they
were drafted from — wherever you keep things under change control. To pin
exactly which export the baseline mirrors, record the checksum yourself
(`sha256sum graph.graphml`) alongside it.

### 5. Gate every deploy

Run this wherever a graph change could reach a client — a deploy step, or a
scheduled export-and-validate job that also catches out-of-band edits made
directly in Neo4j:

```
uv run python src/validate.py graphs/my-kg/graph.graphml \
    graphs/my-kg/shape.yaml graphs/my-kg/expectations.yaml
```

Exit 1 blocks the deploy.

### 6. When you intend to change the graph

Don't hand-edit `expectations.yaml` to match a new graph — review the delta:

```
uv run python src/diff_baseline.py new-graph.graphml \
    graphs/my-kg/shape.yaml graphs/my-kg/expectations.yaml --update
```

`change_report.md` lists which journeys the change added, which previously
approved ones are gone, any entry/terminal changes, and whether the added
journeys break a baseline rule or reroute a scenario. `--update` writes
`expectations.yaml.new` — deliberately a separate path, so the tool that
diffs against your baseline can never overwrite it.

- Intended → promote the `.new` file over the baseline and keep the report
  with your approval as the sign-off record.
- Not intended → fix the graph, re-export, re-run.

Exit codes: `0` no change, `1` changes to review, `2` the diff could not run
at all (cycle, path explosion, shape mismatch).

## expectations.yaml

- `expected_entries` / `expected_terminals` — the exact entry points and the
  allowed set of dead ends.
- `approved_paths` — every structural route the graph is allowed to contain.
- `rules` — precedence and mutual-exclusion invariants, applied to every
  enumerated route including ones introduced by future changes.
- `scenarios` — concrete client profiles and the step sequence each must
  produce. Always hand-written.

Note that `required_step_attrs` lives in `shape.yaml`, not here: it describes
what a well-formed step *is* in this graph, alongside the labels that define
one.

## Tests

```
uv run pytest
```

Tests run against real graphml files in `tests/fixtures/` — including two
APOC-dialect exports — rather than graphs fabricated in Python, except where
a test is deliberately constructing a pathological shape to prove a specific
failure is caught.

None of this depends on git, GitHub, or Neo4j being reachable at validation
time. Baselines are plain files and `change_report.md` is the change record.
