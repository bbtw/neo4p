# neo4p

Pulls a Neo4j planning graph — the graph that decides which financial-planning
tasks get suggested to a client — snapshots it to GraphML, and validates it
before it's allowed to influence what a real customer sees.

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

## Why a graph, and not just a rules engine like Drools

A fair challenge, and one that comes up often: the individual decisions here
— is a task complete, is the 401(k) match fully captured, does this client's
profile satisfy some condition — are genuinely rules. An edge's
`condition_key`/`condition_value`, or a criteria node checking something
like "employer match maxed," is the same shape as a Drools production rule:
a condition evaluated against client facts, deciding what happens next.
That's not in dispute.

What a rules engine doesn't give you is the layer above that: not "is this
one criterion true for this one client," but "given every criterion that
could ever be true, what is the complete set of task sequences a client
could ever be walked through, and does that set match what was approved?"
That's a question about how many independently-correct rules *compose*, not
about whether any one of them is correct — and it's a reachability question,
not a rule-firing question. A rule engine doesn't expose that by inspecting
its own rule base; the only way to answer it is to simulate every
combination of facts a client could present and see what fires, which tells
you about the cases you thought to test, not a proof over all of them.

Because a client can satisfy a graph's edges many different ways depending
on where they are and what's true about them, there is rarely one linear
script through it — there can be many valid traversals through the same
graph, some overlapping, some diverging entirely at a fork. The graph turns
"what are all of those traversals" into a millisecond walk
(`enumerate_paths`) instead of a testing exercise: the full set is
enumerable, diffable between graph versions, and provable against invariants
(`check_rules`), because the sequence itself is data, not an emergent
byproduct of which rules happened to fire in which order.

This isn't rules versus graph — the two compose. A criterion's own
evaluation, including one as involved as "is the match maxed," can
legitimately be computed anywhere, Drools included, and handed to the graph
as a fact. The graph doesn't replace that logic; it answers a different
question on top of it — what can the composition of every correct decision
ever produce, and can that set be proven to match what was signed off on.

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

`validate.py` writes `paths.json` (every client journey) and `validation.json`
(pass/fail report) into the snapshot directory, and exits 1 on failure, so it
is safe to run in CI.

## expectations.yaml

The file every validation run checks the graph against. Kept in version
control next to the code, so a graph change that breaks an expected
recommendation fails the build instead of reaching a client.

- `expected_entries` / `expected_terminals` — the only steps allowed to have
  no predecessor / no successor. A new one showing up means a route changed
  without anyone intending it to.
- `approved_paths` — every client journey the graph is allowed to produce.
  Regenerated from `paths.json` when a change is intentional; the diff on
  this list *is* the record of which journeys a given change added or
  removed.
- `scenarios` — concrete client profiles with the step sequence they must
  produce, for spot-checking behavior the other checks can't see.

## The validators

`validate.py` runs three independent layers. Each catches a different class
of problem; none of them subsumes the others.

**1. Structural — `check_structure()`**
Is the graph shaped the way you think it is?
- acyclic (a recommendation flow can never loop)
- entry points match `expected_entries` — nothing silently added or removed
- every node is reachable from an entry point — no orphaned step
- every dead end is a declared terminal, not an accident
- every node carries `rationale` + `source_doc` — nothing is recommended
  without a stated justification and where it came from
- every edge carries `condition_key` + `condition_value` — nothing branches
  on an unstated rule

Cheap and exhaustive. Says nothing about whether the graph's *behavior* is
correct — only its shape and metadata.

**2. Path enumeration — `enumerate_paths()` / `check_paths()`**
Every simple entry-to-terminal route the graph can currently produce,
diffed against `approved_paths`. Flags any journey a client could now take
that nobody approved, and any previously-approved journey that's no longer
possible.

This is exhaustive and exact — when it passes, "every journey this graph can
produce" and "every journey someone signed off on" are provably the same
set. It's also the layer that doesn't scale: the number of simple paths
through a DAG grows combinatorially with its fork/merge structure, not with
its node count. Past `MAX_PATHS` (5000) journeys, `validate.py` refuses to
enumerate rather than hang or silently truncate. See the next section for
what to do about that.

**3. Scenario — `check_scenarios()`**
Does a handful of named, concrete client profiles produce the expected step
sequence? Not exhaustive — only the listed profiles are checked. It exists
because a graph can pass layers 1 and 2 (correctly shaped, contains only
approved paths) and still be wrong: it routes an actual real-world profile
down the wrong *one* of those approved paths. This is the layer that catches
that.

## Signing off on a graph with combinatorial paths

This section is for whoever is asked to approve a graph or a graph change —
typically a compliance or risk reviewer outside the engineering team.

The instinctive request — "review every possible client journey" — is not
something a person can actually do past a few dozen paths, and it gets worse
fast: every additional sequential fork roughly doubles the journey count, so
ten forks alone produce over a thousand journeys. At real graph sizes
(hundreds of nodes, hundreds of edges) the honest number of distinct
journeys is easily in the thousands. `MAX_PATHS` exists specifically so
nobody is ever asked, even accidentally, to review past that point by hand —
the script fails loudly instead of quietly succeeding on an unreviewable
graph.

That means "read every path and sign off on each one" cannot be the review
process — asking for it produces the opposite of oversight, because nobody
actually reads 5,000 sequences, and the sign-off becomes a formality instead
of a real check. The review has to be scoped down to something a person can
hold in their head and genuinely mean their approval of. Three tiers do
that:

**1. You approve rules, not paths.**
The thing worth a reviewer's judgment is not "is journey #4,812
acceptable" but the invariant behind it — *a client must never be told to
increase investing before their emergency fund is confirmed funded*, *debt
payoff and credit-limit-increase suggestions must never appear on the same
journey*, *any journey touching a tax-advantaged withdrawal must be preceded
by a tax-bracket check*. These are ordinary suitability-style statements —
the kind of judgment a compliance reviewer already makes — and there are a
few hundred of them for this graph, not a few thousand paths. That's a
number a person can actually review.

**2. The rules are enforced automatically, every time.**
Once a rule is written down, it gets checked against every graph change in
CI, forever, the same way `check_structure` and `check_paths` already run —
without depending on anyone's attention on any given day. This is what
makes the process *reliable*, not just honest at the moment of signing.

**3. You only see raw paths when something is both new and high-risk.**
`paths.json` and `approved_paths` give an exact diff on every change: which
journeys are newly possible, which previously-approved ones vanished.
Filtered to journeys touching a flagged high-risk step (money movement, tax
elections, debt restructuring), that diff is realistically a handful of
sequences per change — small enough to actually read, not skim.

**What sign-off should mean, concretely:**
- the rule set, as written, is correct and complete for the risk you're
  accountable for
- the new or high-risk journeys surfaced in this change's diff are
  acceptable

A reviewer is not attesting to having read every one of the graph's
thousands of possible journeys — nobody can, and a process that implies
otherwise isn't oversight, it's a rubber stamp with extra steps.

Every node in the graph carries `rationale` and `source_doc` (enforced by
layer 1). Treat that as the audit trail: any flagged step should trace back
to why it exists and which policy document put it there.