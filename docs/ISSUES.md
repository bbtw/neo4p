# Known issues

Findings from a repo review on 2026-08-11, updated after the shape refactor
the same day. The refactor replaced `schema.infer_schema()` — which guessed a
graph's meaning from its topology on every validation run — with a declared
`shape.yaml` per graph, and demoted inference to `propose_shape.py`, a draft
generator that never runs during validation.

## Fixed

### 2. Branch-type classification required no evidence of an actual fork

**Was:** `infer_schema()` marked a relationship type as `branching` the moment
any single edge of that type carried a property beyond `rel`/`id`, without
ever checking whether that type was used to fork. Two confirmed failure
modes, both reproduced against the real code:

- A shared rel type picking up one incidental property cascaded — every node
  reached only via that type became a "branch", and `collapse_criteria()`
  raised `ValueError`. Confusing but loud.
- A one-off rel type feeding a pass-through step (in-degree 1, out-degree 1)
  produced **zero failures**. The node was silently deleted from the graph
  before path enumeration *and* exempted from `required_step_attrs`, so a
  real client-facing step could ship with no `rationale` and no `source_doc`,
  undetected. Downstream it surfaced only as `"approved journey no longer
  possible"` — indistinguishable from an intentional removal, which a
  reviewer would sign off on.

**Fixed by** deleting inference from the validation path entirely. `shape.yaml`
declares `step_labels` / `branch_labels`, so what a node *is* comes from its
own label, and no edge property can change it. `check_shape()` runs as layer 0
and rejects a graph that contradicts its shape file before any other layer
reads it.

Both repro cases are pinned as regression tests:
`tests/test_shape.py::test_incidental_edge_property_no_longer_reclassifies_a_step`
and `::test_undocumented_passthrough_step_is_caught_not_silently_deleted`.

**Also addressed the secondary hardening note:** `validate.py` prints the
shape it used before printing any result, and reports every layer as
`ok`/`FAIL` rather than printing only failures — so "checked and clean" is
distinguishable from "never ran".

### 3. `diff_baseline.py` documented exit code 2 was unreachable

Both sites used `sys.exit("message")`, which exits 1 — the same code as
"changes found". Now `die()` prints to stderr and exits 2. Covered by
`test_diff_baseline.py::test_cannot_diff_exits_2_not_1`.

### 4. `diff_baseline.py --update` had no overwrite guard

`--update` wrote `expectations.yaml` next to the new graphml unconditionally,
silently clobbering the committed baseline it had just diffed against. It now
writes `expectations.yaml.new` and prints the `mv` to promote it. Covered by
`::test_update_never_overwrites_the_baseline_it_diffed_against`.

### 5. `collapse_criteria()` silently dropped parallel branches to the same child

Two branch edges from one source resolving to the same child collapsed to the
same `(src, child)` key; `add_edge` overwrote, discarding the first branch's
condition. `collapse_branches()` now raises when an existing edge would be
overwritten with different data. Covered by
`test_validate.py::test_collapse_raises_rather_than_silently_dropping_a_parallel_branch`.

### 6. No multigraph guard

`nx.read_graphml()` returns a `MultiDiGraph` for parallel relationships, on
which the module's `DiGraph` assumptions quietly break. `normalize_graph()`
now rejects both multigraphs and undirected graphs with a clear message.

### 7. `bootstrap.py` exit code didn't match its docstring

Orphans, missing attrs and bare branches were printed as warnings while the
script still exited 0, so a CI wrapper reading only the status saw success.
`bootstrap.py` now exits 1 when `check_structure()` finds anything — while
still writing the draft, so you can see what it would have approved. Exit 2 is
reserved for "cannot bootstrap at all".

### 8. `condition_key_attr` could be set while `condition_value_attr` stayed `None`

`data.get(None)` is always `None`, so an edge was "allowed" only when the
profile lookup also returned `None` — a silent, wrong condition. `load_shape()`
now rejects a shape declaring one without the other, and `propose_shape.py`
leaves both blank rather than proposing a half-filled pair.

### 9. Business-id node keys weren't stringified before sorting

An APOC export with `useTypes: true` can yield integer ids; a later `sorted()`
over mixed str/int node keys raised `TypeError`. `normalize_graph()` now calls
`str()` when building `id_map`.

### 10. `enumerate_paths` couldn't approve or flag a single-node journey

A node that is both entry and terminal was skipped entirely, so it could
neither appear in `approved_paths` nor be flagged if one appeared. It is now
emitted as a single-node path `[node]`.

### 11. `propose_shape.py` silently resolved its own ambiguities — FIXED

The first version of `propose_shape.py` committed, in a smaller way, the same
sin as `infer_schema()`: where evidence supported more than one reading it
picked one and printed it as though it were a finding. Three demonstrated
cases:

- **Tie-break by sort order.** The condition-attribute search took the first
  attribute (alphabetically) that varied between sibling branches. Add an
  `audit_ts` to your branch edges and it proposed `condition_value_attr:
  audit_ts`, because `audit_ts` sorts before `condition_value`. Scenario walks
  would then compare client profiles against timestamps and silently never
  match.
- **Classification from a sample of one.** A single pass-through node was
  enough to declare its whole label a branch label. A `Disclosure` step — a
  real, documented, client-facing regulatory step that happens to sit between
  two others — was proposed as a branch point, which would collapse it out of
  every path and exempt it from documentation checks.
- **Unscoped exports legitimized rather than flagged.** On the whole-database
  fixture it proposed `step_labels: [Account, Reviewed, Task]` and
  `required_step_attrs: []` — `acct1` isn't part of the flow, but isn't a
  pass-through either, so it was assumed to be a step, and its lack of
  `rationale` emptied the intersection that defines the documentation
  requirement.

**Fixed** by making every field either determined from unambiguous evidence
or `UNRESOLVED` with a stated reason and an explicit question. Branch labels
now require a genuine fork (some node with ≥2 outgoing edges into that label)
plus a sample of ≥2 nodes. Condition attributes require exactly one candidate
on each side. A label sharing no attributes with the dominant step label is
refused rather than assumed. `required_step_attrs` reports near-misses by
name instead of intersecting them away.

`load_shape()` rejects any file still marked `UNRESOLVED`, naming every
outstanding field — so a half-determined shape cannot reach a deploy gate by
being ignored. Exit codes: 0 determined, 1 needs decisions, 2 unreadable.
Covered by `tests/test_propose_shape.py` (13 tests), including all three
cases above and the complement — that an unambiguous graph still resolves
cleanly, so "refuse" cannot degenerate into refusing everything.

**Residual, and irreducible:** the three refusal cases are genuine ambiguities
in the data, not gaps in the implementation. No amount of topological analysis
distinguishes a condition-carrier that never forks from an ordinary
intermediate step, because they are the same shape. The tool asks instead.

### Minor, fixed

- `argparse` added to `validate.py`, `bootstrap.py`, `diff_baseline.py`,
  `propose_shape.py` and `mine_rules.py` — missing args produce a usage
  message, not an `IndexError` traceback.
- `walk(..., schema=None)` is gone; shape is a required argument everywhere.
- `check_rules()`'s mutual-exclusion message no longer says "both appear" for
  a rule listing 3+ steps.
- `.gitignore`'s stale `snapshot.py` comment replaced with the generated-output
  paths (`paths.json`, `validation.json`, `change_report.md`,
  `expectations.yaml.new`).
- `walk()` now raises on revisiting a node instead of looping forever if
  handed a cyclic graph directly.
- `ruff check src tests` is clean.

## Still open

### 1. Working tree is not committed

Everything from this refactor is uncommitted, and the last five commits on
`main` are all titled "react works" — which does not describe this repo's
history. Before treating `main` as usable, review and commit:

- new: `src/shape.py`, `src/propose_shape.py`, `tests/test_shape.py`,
  `graphs/sample/`
- deleted: `src/schema.py`, `tests/test_schema.py`, `src/expectations.yaml`
  (superseded by `graphs/sample/expectations.yaml`)
- modified: `src/validate.py`, `src/bootstrap.py`, `src/diff_baseline.py`,
  `src/mine_rules.py`, `README.md`, `.gitignore`, and the three remaining
  test modules

### No CI workflow, no LICENSE

`ruff` is a dev dependency but nothing runs it automatically — no pre-commit
hook, no CI job — despite this being explicitly a deploy-gate tool. Worth a
minimal GitHub Actions job running `uv sync && uv run ruff check && uv run
pytest`, plus validating every graph under `graphs/` against its own baseline
so the committed examples can't drift.

### Scenario coverage is not measured

Nothing reports which branches no scenario exercises. A baseline can have
`scenarios: []` and still pass every layer, which is correct — layers 1–3 are
structural — but a reviewer has no signal that layer 4 is checking nothing.
Worth printing "N of M branch conditions exercised by scenarios" on each run.

## Not an issue

- Cyclic graphs, unreachable nodes and unapproved journeys are handled
  correctly and are covered by tests.
- `edge_allowed()` correctly avoids `eval()`-ing any condition data — plain
  key/value lookup only, as the docstring promises.
- Feeding in an unscoped whole-database export is not silently filtered: the
  extra material now fails at layer 0 by name (`node(s) match no declared
  label ['CriteriaNode', 'Task']: ['acct1' (labelled ['Account'])]`) rather
  than several layers later as a mysterious dead end.
