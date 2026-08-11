"""
Propose a draft shape.yaml for a graph that doesn't have one yet.

Every field this produces is either **determined** — backed by evidence that
admits one reading — or **UNRESOLVED**, left blank with a stated reason and a
list of what it needs to decide. It never breaks a tie, never classifies from
a sample of one, and never picks the first of several candidates.

That rule is the whole design. A tool that half-guesses and leans on expert
review is worse than no tool: the person reading the draft is the person who
needed the draft. So the output is only ever "here is the answer, with the
evidence" or "I cannot tell, here is exactly what is ambiguous" — and a draft
containing the second kind physically will not load (`shape.load_shape()`
rejects any file still marked UNRESOLVED) until a human has decided.

Usage:
    python propose_shape.py graph.graphml [-o shape.yaml]

Exit code 0 = a complete shape was determined; the draft is usable as-is
(read it anyway — "determined from this graph" is not "correct for your
domain"). Exit 1 = the draft has UNRESOLVED fields you must decide. Exit 2 =
could not read the graph at all.

What it can and cannot determine, and why:

  branch_labels        Determined only when a label's nodes are ALL
                       pass-throughs AND at least one parent genuinely forks
                       into two of them. Pass-through alone is not evidence:
                       a real client-facing step that always sits between two
                       others looks identical. Unresolved when it sees the
                       shape but no fork.
  step_labels          Determined for labels whose nodes carry attributes in
                       common with the graph's dominant step label.
                       Unresolved for a label that shares nothing with it —
                       that is what unrelated material from an unscoped
                       whole-database export looks like, and no amount of
                       topology can tell you whether it belongs.
  condition_*_attr     Determined only when exactly ONE attribute varies
                       across sibling branches and exactly ONE stays
                       constant. Two candidates means two candidates.
  required_step_attrs  Never inferred as policy. Reports what every step
                       carries today, and separately reports near-misses —
                       attributes most steps carry and some don't — because
                       a near-miss is usually a documentation gap, and
                       silently intersecting it away turns that gap into
                       the standard.
"""

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import yaml

from shape import BOOKKEEPING_EDGE_ATTRS, BOOKKEEPING_NODE_ATTRS, UNRESOLVED
from validate import normalize_graph

# A label seen on fewer than this many nodes is not a sample to classify from.
MIN_LABEL_SAMPLE = 2


@dataclass
class Finding:
    """One field of the draft: either determined, or explicitly not."""

    value: object
    evidence: str
    resolved: bool = True
    needs: list = field(default_factory=list)

    @classmethod
    def determined(cls, value, evidence: str) -> "Finding":
        return cls(value=value, evidence=evidence)

    @classmethod
    def unresolved(cls, evidence: str, needs: list | None = None) -> "Finding":
        return cls(value=UNRESOLVED, evidence=evidence, resolved=False, needs=needs or [])


def labels_of(data: dict) -> set[str]:
    raw = data.get("labels") or data.get("label") or ""
    return {part for part in str(raw).split(":") if part}


def _classify_labels(graph) -> tuple[dict, list[str]]:
    """Sort every node label into 'branch', 'step' or 'unresolved', with the
    evidence for each. This is the decision everything else depends on."""
    evidence = []
    nodes_by_label = defaultdict(list)
    unlabelled = []
    for node, data in graph.nodes(data=True):
        found = labels_of(data)
        if not found:
            unlabelled.append(node)
        for label in found:
            nodes_by_label[label].append(node)

    if unlabelled:
        evidence.append(
            f"! {len(unlabelled)} node(s) carry no label at all "
            f"({sorted(unlabelled)[:5]}). No shape file can classify them — "
            "label them in Neo4j and re-export."
        )
    if not nodes_by_label:
        raise ValueError(
            "no node in this graph carries a `labels` attribute — nothing to "
            "propose. Re-export with node labels included."
        )

    verdict = {}

    # -- branch labels: pass-through SHAPE plus a genuine FORK ---------------
    for label, nodes in sorted(nodes_by_label.items()):
        passthrough = [
            n for n in nodes if graph.out_degree(n) == 1 and graph.in_degree(n) >= 1
        ]
        if len(passthrough) != len(nodes):
            continue  # not even the right shape; handled as a step candidate below

        if len(nodes) < MIN_LABEL_SAMPLE:
            verdict[label] = Finding.unresolved(
                f"? {label!r}: the only node carrying it ({nodes[0]!r}) is a "
                "pass-through, but one node is not evidence of a pattern",
                needs=[
                    (
                        f"is {label!r} a branch point (a node that exists only to "
                        "carry a condition), or a real step that happens to sit "
                        "between two others?"
                    )
                ],
            )
            continue

        # Does any parent actually fork into two nodes of this label? That is
        # the difference between a condition-carrier and a step that merely
        # happens to be a pass-through.
        forks = [
            src
            for src in graph.nodes
            if sum(1 for _, dst in graph.out_edges(src) if label in labels_of(graph.nodes[dst])) >= 2
        ]
        if forks:
            verdict[label] = Finding.determined(
                "branch",
                f"  branch  {label!r}: all {len(nodes)} node(s) are pass-throughs, "
                f"and {sorted(forks)[:3]} fork(s) into two or more of them — a "
                "real decision point, not just a node in the middle",
            )
        else:
            verdict[label] = Finding.unresolved(
                f"? {label!r}: all {len(nodes)} node(s) are pass-throughs, but no "
                "node anywhere forks into two of them. A branch point that never "
                "branches and an ordinary intermediate step are indistinguishable "
                "from topology alone",
                needs=[
                    (
                        f"is {label!r} a branch point (collapsed away, exempt from "
                        f"documentation), or a client-facing step? e.g. {nodes[0]!r}"
                    )
                ],
            )

    # -- step labels: must look like the dominant step label -----------------
    step_candidates = {
        label: nodes for label, nodes in nodes_by_label.items() if label not in verdict
    }
    if not step_candidates:
        raise ValueError(
            "every label in this graph looks like a pass-through; there are no "
            "steps for a client to take. Check the export is scoped to a flow."
        )

    dominant = max(step_candidates, key=lambda label: len(step_candidates[label]))
    dominant_attrs = set.intersection(
        *(
            set(graph.nodes[n]) - BOOKKEEPING_NODE_ATTRS
            for n in step_candidates[dominant]
        )
    )
    evidence.append(
        f"  steps are modelled on {dominant!r} ({len(step_candidates[dominant])} "
        f"node(s)), whose nodes all carry {sorted(dominant_attrs)}"
    )

    for label, nodes in sorted(step_candidates.items()):
        if label == dominant:
            verdict[label] = Finding.determined(
                "step", f"  step    {label!r}: {len(nodes)} node(s), the dominant step label"
            )
            continue

        # A label every one of whose nodes ALSO carries a confirmed step label
        # is redundant, not a separate kind of thing.
        redundant = all(dominant in labels_of(graph.nodes[n]) for n in nodes)
        if redundant:
            verdict[label] = Finding.determined(
                "step",
                f"  step    {label!r}: {len(nodes)} node(s), every one of which also "
                f"carries {dominant!r} — a secondary tag on a step, not a new kind",
            )
            continue

        shared = set.intersection(
            *(set(graph.nodes[n]) - BOOKKEEPING_NODE_ATTRS for n in nodes)
        )
        if shared & dominant_attrs:
            verdict[label] = Finding.determined(
                "step",
                f"  step    {label!r}: {len(nodes)} node(s) carrying "
                f"{sorted(shared & dominant_attrs)}, same as {dominant!r}",
            )
        else:
            verdict[label] = Finding.unresolved(
                f"? {label!r}: {len(nodes)} node(s) carrying {sorted(shared)}, which "
                f"shares nothing with {dominant!r}'s {sorted(dominant_attrs)}. This is "
                "what unrelated material from an unscoped whole-database export "
                f"looks like — but it is also what a legitimately different kind of "
                "step looks like, and topology cannot tell them apart",
                needs=[
                    (
                        f"is {label!r} part of this flow at all? If not, scope the "
                        f"export query to exclude it. e.g. {min(nodes)!r}"
                    )
                ],
            )

    for label in sorted(verdict):
        evidence.append(verdict[label].evidence)

    return verdict, evidence


def _condition_attrs(graph, branch_rels: set) -> tuple[Finding, Finding]:
    """Which edge attribute names the profile field, and which holds the value
    to match. Determined only when each has exactly one candidate."""
    branch_edges = [
        data for _, _, data in graph.edges(data=True) if data.get("rel") in branch_rels
    ]
    if not branch_edges:
        no_edges = Finding.determined(
            None, "  condition: no branch edges in this graph; none needed"
        )
        return no_edges, no_edges

    common = set.intersection(*(set(d) - BOOKKEEPING_EDGE_ATTRS for d in branch_edges))

    groups = defaultdict(list)
    for src, _, data in graph.edges(data=True):
        if data.get("rel") in branch_rels:
            groups[src].append(data)
    forks = [g for g in groups.values() if len(g) >= 2]

    if not forks:
        unresolved = Finding.unresolved(
            "? condition: no node has two or more branch edges, so there is no "
            "fork to compare siblings across and no way to tell which attribute "
            f"is the condition. Candidates, all equally plausible: {sorted(common)}",
            needs=[
                (
                    "which branch-edge attribute names the client-profile field, "
                    f"and which holds the value to match? Candidates: {sorted(common)}"
                )
            ],
        )
        return unresolved, unresolved

    varying = sorted(a for a in common if any(len({d.get(a) for d in g}) > 1 for g in forks))
    constant = sorted(
        a for a in common if all(len({d.get(a) for d in g}) == 1 for g in forks)
    )

    if len(varying) == 1:
        value = Finding.determined(
            varying[0],
            f"  condition value: {varying[0]!r} — the only attribute that differs "
            f"between sibling branches across all {len(forks)} fork(s)",
        )
    else:
        value = Finding.unresolved(
            f"? condition value: {len(varying)} attributes differ between sibling "
            f"branches — {varying}. Any of them could be the value being matched; "
            "the rest are probably incidental (timestamps, weights, audit fields)",
            needs=[f"which of {varying} holds the value a client profile must equal?"],
        )

    remaining = [a for a in constant if a not in varying]
    if len(remaining) == 1:
        key = Finding.determined(
            remaining[0],
            f"  condition key:   {remaining[0]!r} — the only attribute constant "
            "within each sibling group",
        )
    elif not remaining:
        key = Finding.unresolved(
            "? condition key: no attribute is constant within every sibling group, "
            "so nothing looks like a profile field name",
            needs=["which branch-edge attribute names the client-profile field?"],
        )
    else:
        key = Finding.unresolved(
            f"? condition key: {len(remaining)} attributes are constant within every "
            f"sibling group — {remaining}",
            needs=[f"which of {remaining} names the client-profile field to look up?"],
        )

    return key, value


def _step_attrs(graph, step_nodes: list) -> tuple[list, list[str]]:
    """What every step carries, plus the near-misses — attributes most steps
    carry and some don't. A near-miss is usually a documentation gap; quietly
    intersecting it away would turn that gap into the standard."""
    if not step_nodes:
        return [], []

    attr_sets = [set(graph.nodes[n]) - BOOKKEEPING_NODE_ATTRS for n in step_nodes]
    universal = sorted(set.intersection(*attr_sets))

    counts = defaultdict(int)
    for attrs in attr_sets:
        for attr in attrs:
            counts[attr] += 1

    total = len(step_nodes)
    notes = [
        f"  every step carries {universal}"
        if universal
        else "! no attribute is carried by every step"
    ]
    for attr, count in sorted(counts.items()):
        if count < total:
            missing = sorted(
                n for n in step_nodes if attr not in set(graph.nodes[n])
            )
            notes.append(
                f"! near-miss {attr!r}: carried by {count} of {total} steps, missing "
                f"from {missing[:4]}. NOT added to required_step_attrs — decide "
                "whether that is a documentation gap to fix or genuinely optional"
            )
    return universal, notes


def propose(graph) -> tuple[dict, list[str], list[str]]:
    """Return (draft, evidence lines, open questions)."""
    verdict, evidence = _classify_labels(graph)

    branch_labels = sorted(k for k, v in verdict.items() if v.resolved and v.value == "branch")
    step_labels = sorted(k for k, v in verdict.items() if v.resolved and v.value == "step")
    undecided = sorted(k for k, v in verdict.items() if not v.resolved)

    questions = [q for label in undecided for q in verdict[label].needs]

    branch_rels = sorted(
        {
            data.get("rel")
            for _, dst, data in graph.edges(data=True)
            if labels_of(graph.nodes[dst]) & set(branch_labels) and data.get("rel")
        }
    )
    all_rels = sorted({d.get("rel") for _, _, d in graph.edges(data=True) if d.get("rel")})

    if undecided:
        # Everything below is derived from the label classification, so an
        # undecided label makes all of it undecided too. Saying so beats
        # emitting numbers computed under an assumption nobody agreed to.
        evidence.append(
            f"! {len(undecided)} label(s) undecided ({undecided}), so branch_rels, "
            "the condition attributes and required_step_attrs cannot be settled "
            "either — they all depend on which nodes are steps"
        )
        draft = {
            "step_labels": step_labels or UNRESOLVED,
            "branch_labels": [*branch_labels, UNRESOLVED],
            "branch_rels": UNRESOLVED,
            "condition_key_attr": UNRESOLVED,
            "condition_value_attr": UNRESOLVED,
            "required_step_attrs": UNRESOLVED,
            "required_branch_attrs": UNRESOLVED,
        }
        return draft, evidence, questions

    evidence.append(f"  rels: {all_rels} present; {branch_rels} lead into branch nodes")

    key, value = _condition_attrs(graph, set(branch_rels))
    evidence += [key.evidence, value.evidence]
    questions += key.needs + value.needs

    step_nodes = [
        n for n, d in graph.nodes(data=True) if not (labels_of(d) & set(branch_labels))
    ]
    required_step_attrs, attr_notes = _step_attrs(graph, step_nodes)
    evidence += attr_notes

    branch_edges = [
        d for _, _, d in graph.edges(data=True) if d.get("rel") in set(branch_rels)
    ]
    required_branch_attrs = (
        sorted(set.intersection(*(set(d) - BOOKKEEPING_EDGE_ATTRS for d in branch_edges)))
        if branch_edges
        else []
    )

    draft = {
        "step_labels": step_labels,
        "branch_labels": branch_labels,
        "branch_rels": branch_rels,
        "condition_key_attr": key.value if key.resolved else UNRESOLVED,
        "condition_value_attr": value.value if value.resolved else UNRESOLVED,
        "required_step_attrs": required_step_attrs,
        "required_branch_attrs": required_branch_attrs,
    }
    return draft, evidence, questions


HEADER = """\
# DRAFT shape.yaml, generated from {graphml} by propose_shape.py.
#
# Every value here was DETERMINED from the graph — this tool leaves a field
# marked UNRESOLVED rather than guess at it, so nothing below is a coin flip.
# That still is not the same as "correct for your domain": the graph can only
# tell you what it looks like, not what it means. Read it once before
# committing.
{questions}"""

QUESTION_BLOCK = """#
# {n} field(s) could NOT be determined and are marked UNRESOLVED. This file
# will not load until you replace them. What needs deciding:
#
{lines}
#
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Propose a draft shape.yaml, or report what it cannot determine.",
    )
    parser.add_argument("graphml", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=None, help="write the draft here")
    args = parser.parse_args()

    if not args.graphml.exists():
        print(f"no such file: {args.graphml}", file=sys.stderr)
        sys.exit(2)
    if args.out and args.out.exists():
        print(f"refusing to overwrite existing {args.out} — move it first", file=sys.stderr)
        sys.exit(2)

    try:
        graph = normalize_graph(nx.read_graphml(args.graphml))
        draft, evidence, questions = propose(graph)
    except ValueError as exc:
        print(f"cannot propose a shape: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"Evidence, field by field ({args.graphml}):\n")
    for line in evidence:
        print(line)

    body = yaml.dump(draft, sort_keys=False, default_flow_style=False)
    question_block = ""
    if questions:
        question_block = QUESTION_BLOCK.format(
            n=sum(1 for v in draft.values() if v == UNRESOLVED or (isinstance(v, list) and UNRESOLVED in v)),
            lines="\n".join(f"#   {i}. {q}" for i, q in enumerate(questions, 1)),
        )

    print("\nProposed shape.yaml:\n")
    print(body)

    if questions:
        print(f"UNRESOLVED — {len(questions)} question(s) the graph cannot answer:\n")
        for i, question in enumerate(questions, 1):
            print(f"  {i}. {question}")
        print(
            "\nThese are genuine ambiguities, not missing effort: the evidence above "
            "\nis consistent with more than one reading, and picking one silently is "
            "\nexactly the failure mode this pipeline exists to avoid."
        )
    else:
        branch_nodes = sorted(
            n
            for n, d in graph.nodes(data=True)
            if labels_of(d) & set(draft["branch_labels"])
        )
        print(
            f"Determined a complete shape. It treats {len(branch_nodes)} node(s) as "
            "branch points\n(collapsed away before path checks, exempt from "
            "documentation checks):"
        )
        for node in branch_nodes:
            print(f"  - {node}")
        if not branch_nodes:
            print("  (none)")

    if args.out:
        args.out.write_text(HEADER.format(graphml=args.graphml, questions=question_block) + body)
        print(f"\nwrote draft to {args.out}")

    sys.exit(1 if questions else 0)


if __name__ == "__main__":
    main()
