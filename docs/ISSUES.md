# Known issues

Findings from a repo review on 2026-08-11. Ordered by severity within each
section. None of these are fixed yet — this is the punch list.

## Critical

### 1. Working tree is not committed — repo is broken on a fresh clone

`src/schema.py`, `tests/test_schema.py`, `tests/test_apoc_compat.py`, and the
two APOC-shaped fixtures (`tests/fixtures/sample_graph_apoc*.graphml`) are
untracked. Every module (`validate.py`, `bootstrap.py`, `diff_baseline.py`)
does `from schema import ...`, so `git clone` + `uv sync` + run fails
immediately with `ModuleNotFoundError`. There are also several modified/
deleted tracked files (`src/snapshot.py`, `src/verify_baseline.py` deleted;
`README.md`, `pyproject.toml`, `src/validate.py`, `src/bootstrap.py`,
`src/diff_baseline.py`, `src/expectations.yaml`, `tests/conftest.py`,
`tests/test_validate.py`, `docs/reference.html` modified) sitting
uncommitted. `git status --short` in the repo root shows the full list.

**Fix:** commit (or explicitly stage/review) everything currently untracked
and modified before treating `main` as usable.

### 2. Branch-type classification requires no evidence of an actual fork (`src/schema.py`)

`infer_schema()` marks a relationship type as `branching` the moment *any
single edge* of that type carries a property beyond `rel`/`id` (lines
~70–76). It never checks whether that rel type is actually used to fork —
i.e. whether any node has ≥2 outgoing edges of that type. Contrast this with
`condition_key_attr`/`condition_value_attr` a few lines down (~106–123),
which correctly *does* require a real fork (`sibling_groups`: nodes with ≥2
branch edges) before drawing any conclusion. The classification step is
looser than the signal it's supposed to detect.

**Confirmed impact** (reproduced against the actual code, see below):

- **If the mis-tagged rel type is reused across the graph** (e.g. a shared
  `NEXT` relationship, and one edge of it picks up an incidental property
  like a timestamp or weight): every node reached only via that type
  cascades into "branch," `collapse_criteria()` can't find a single direct
  child for most of them, and it raises `ValueError` loudly. Confusing, but
  safe — impossible to miss.

- **If the mis-tagged rel type is used on exactly one edge, and that edge
  feeds a pass-through step** (in-degree 1, out-degree 1): `check_structure()`
  returns **zero failures**. `collapse_criteria()` silently deletes that node
  from the graph — no error, no warning. Worse: the deleted node is also
  **exempt from `required_step_attrs`** (branch nodes don't need
  `rationale`/`source_doc`), so a real client-facing step can ship with no
  documentation and no failure is raised, purely because of one incidental
  edge property. Reproduction:

  ```python
  # B has in-degree 1 (via a one-off "SPECIAL" rel carrying an unrelated
  # property) and out-degree 1 (plain "NEXT"). B is missing its required
  # rationale/source_doc.
  g.add_edge("A", "B", rel="SPECIAL", note="internal tracking id")
  g.add_edge("B", "C", rel="NEXT")
  # B intentionally has no rationale/source_doc

  check_structure(g, ["A"], ["C"], required_step_attrs=("rationale","source_doc"))
  # -> [] (zero failures — B's missing docs are never caught)

  collapse_criteria(g)
  # -> nodes: ['A', 'C']  (B is gone entirely)
  ```

  The only place this can ever surface downstream is `check_paths()`
  comparing against `approved_paths` in `validate.py`, and even then the
  message reads like a real, intentional structural change
  (`"approved journey no longer possible: [A,B,C]"` /
  `"unapproved client journey: [A,C]"`). Run through `diff_baseline.py` —
  the actual human sign-off tool — a reviewer sees what looks like "step B
  was removed" and can approve it without ever learning it's a
  misclassification artifact rather than a real change to the live graph.

**Proposed fix**, tested against both repro cases and against
`tests/fixtures/sample_graph.graphml`'s real branch type (all three come out
correct): in `infer_schema()`, before adding a rel type to `branching_rels`,
require that at least one source node has ≥2 outgoing edges of that type —
i.e. it actually forks somewhere, not just "carries an extra property
somewhere." This also cleans up `required_branch_attrs` and
`condition_key_attr`/`condition_value_attr` for free, since both are derived
from `branching_rels`.

```python
outdeg_by_rel = defaultdict(lambda: defaultdict(int))
for u, _, data in graph.edges(data=True):
    outdeg_by_rel[data.get("rel")][u] += 1
branching_rels = frozenset(
    r for r in candidate_rels  # candidate_rels = current props_by_rel keys
    if any(c >= 2 for c in outdeg_by_rel[r].values())
)
```

**Secondary hardening**, independent of the fix above: have `validate.py`
print the inferred schema (`branching_rels`, `branch_nodes`,
`required_branch_attrs`, `condition_key_attr`/`condition_value_attr`) every
run, so a reviewer can eyeball it. It's pattern-matching on graph shape, not
a schema contract, so even a correct heuristic is worth a sanity check on
every run, not just when something looks wrong.

**Also add:** a regression test in `tests/test_schema.py` covering both repro
cases above (shared-type cascade, single-edge pass-through) so this can't
regress silently.

## Bugs

### 3. `diff_baseline.py` documented exit code 2 is unreachable

The module docstring says "exit code ... 2 = cannot diff (e.g. cycle or path
explosion)," but both places that should exit 2 use `sys.exit("message")`
(lines ~134, ~143), which prints to stderr and exits with status **1** — the
same code as "changes found." A caller branching on exit code can't tell
"the graph has real changes to review" from "the diff itself couldn't run."

**Fix:** `print(msg, file=sys.stderr); sys.exit(2)` in both spots.

### 4. `diff_baseline.py --update` has no overwrite guard

`bootstrap.py` explicitly refuses to overwrite an existing `expectations.yaml`
(`sys.exit(f"refusing to overwrite existing {outpath} — move it first")`).
`diff_baseline.py --update` has no equivalent check — it writes
`expectations.yaml` next to the new graphml unconditionally (line ~168). If
the new graphml is placed beside the committed baseline (a natural layout,
and the one the README's own examples suggest), `--update` silently
overwrites the very baseline file it just diffed against, before the
reviewer has looked at `change_report.md`.

**Fix:** either write to a `.new` / draft path and require an explicit
promote step, or refuse to overwrite and tell the caller to move the file
first, matching `bootstrap.py`'s behavior.

### 5. `collapse_criteria()` silently drops data on parallel branches to the same child

In `collapse_criteria()` (`src/validate.py` ~184–195), if two different
branch edges from the same source, through two different branch nodes,
resolve to the *same* child step, both get collapsed to the same
`(src, child)` key in a plain `DiGraph`. `add_edge` overwrites rather than
raising, so the first branch's condition data is silently lost and only the
second remains.

**Fix:** detect when `(src, children[0])` is already present with different
edge data before overwriting, and raise — same posture as the existing
"must have exactly one direct child" guard just above it.

### 6. No multigraph guard

`nx.read_graphml()` returns a `MultiDiGraph` when the export contains
parallel relationships between the same two nodes (e.g. two different rel
types connecting the same pair — not unusual in a real Neo4j export).
Nothing in `normalize_graph()` or downstream checks for this; APIs called
against a plain `DiGraph` (`graph.edges(data=True)`, `in_edges`, etc.) behave
differently on a `MultiDiGraph`, and edges can be silently merged/dropped
depending on how it's consumed.

**Fix:** assert `not graph.is_multigraph()` (and `graph.is_directed()`) in
`normalize_graph()` and fail with a clear message rather than let it degrade
quietly downstream.

### 7. `bootstrap.py` exit code doesn't match its own docstring / the README

The docstring says "Exit code 0 = draft written, 1 = graph problems prevent
bootstrapping (e.g. a cycle)," and the README says bootstrap.py "aborts on
structural problems." In practice only cycles and `collapse_criteria()`
errors abort (`sys.exit(...)`, lines ~99, ~105). Orphans, missing required
attrs, and bare branches are printed as warnings (`problems`) but the script
still writes the draft and exits 0 — a CI wrapper checking exit status alone
sees success even though real structural problems were flagged in the
output it isn't reading.

**Fix:** either make `bootstrap.py` exit non-zero when `problems` is
non-empty, or fix the docstring/README to describe the actual (warn-only)
behavior so nothing downstream relies on a guarantee that doesn't hold.

### 8. `condition_key_attr` can be set while `condition_value_attr` stays `None`

In `infer_schema()` (`src/schema.py` ~118–123), if all sibling branch edges
share every required attr's value except one (the value attr), it's
possible for the value-attr search to find nothing (leaves
`condition_value_attr = None`) while the key-attr search still finds a
constant-within-siblings attribute and sets `condition_key_attr`. Then in
`edge_allowed()` (`src/validate.py` ~278–289):

```python
return profile.get(data[schema.condition_key_attr]) == data.get(schema.condition_value_attr)
```

`data.get(None)` is always `None`, so the edge is only "allowed" when
`profile.get(...)` happens to also be `None` — a silent, wrong condition
rather than an error.

**Fix:** only set `condition_key_attr` if `condition_value_attr` was also
found; otherwise leave both `None` (which is already handled correctly —
`edge_allowed()` treats an edge with no identified condition attr as
unconditional).

## Design risks worth a comment or guard

### 9. Business-id node keys aren't stringified before sorting

`normalize_graph()` relabels graph nodes to each node's business `id`
property (`src/validate.py` ~92–102). If an APOC export with `useTypes:
true` produces a non-string `id` (e.g. an integer), later `sorted(...)`
calls over mixed node-key types (`sorted(entries)`, `sorted(paths)` in
`validate.py`/`bootstrap.py`) will raise `TypeError: '<' not supported
between instances of ...` the first time a str and non-str id are compared.

**Fix:** `str(business_id)` when building `id_map` in `normalize_graph()`.

### 10. `enumerate_paths` can't approve or flag a single-node journey

`enumerate_paths()` (`src/validate.py` ~204–222) explicitly skips `entry ==
terminal`. A node that is simultaneously an entry and a terminal (a
zero-step journey) can never appear in `approved_paths` and never gets
flagged if one appears unexpectedly — it's invisible to layer 2 entirely,
even though `check_structure`'s entry/terminal checks would still see it.

**Fix:** decide intentionally whether a single-node journey should be
representable in `approved_paths` (e.g. `[node]`), and either enumerate it
or document why not.

## Minor

- No CLI arg parsing anywhere (`bootstrap.py`, `validate.py`,
  `diff_baseline.py`, `mine_rules.py`) — missing/wrong args raise a raw
  `IndexError` traceback instead of a usage message. `argparse` is a small
  addition to each entry point.
- `walk(..., schema: GraphSchema = None)` in `validate.py` — annotation
  should be `GraphSchema | None` to match the codebase's `str | None` style
  used elsewhere (e.g. `schema.py`'s `condition_key_attr: str | None`).
- `check_rules()`'s mutual-exclusion failure message says "both appear"
  (`src/validate.py` ~265) even when a rule lists 3+ mutually exclusive
  steps.
- `.gitignore`'s comment "generated graph snapshots (see snapshot.py)" is
  stale — `src/snapshot.py` shows as deleted in the current working tree.
- Stray `.DS_Store` files under repo root and `src/` (already gitignored,
  just clutter locally).
- No CI workflow configured despite this being explicitly a deploy-gate
  tool, and no LICENSE file. `ruff` is a dev dependency but nothing runs it
  anywhere (no pre-commit hook, no CI job).

## Already fixed / not an issue

- Cyclic graphs, unreachable nodes, and unapproved journeys are all handled
  correctly and are covered by tests.
- `edge_allowed()` correctly avoids `eval()`-ing any condition data — plain
  key/value lookup only, as the docstring promises.
