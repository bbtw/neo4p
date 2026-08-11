"""
Infer, from the graph's own structure, which relationship types encode a
conditional branch and which nodes exist only to carry that branch's
metadata. No external configuration and no assumption about label or
relationship-type names: the graphml file is the only input.

The inference rests on two structural signals present in any property
graph, independent of domain:

  1. A relationship type is a BRANCH type if at least one edge of that type
     carries a property beyond its own type indicator (the `rel` attribute
     normalize_graph() guarantees is present). A conditional transition
     needs *something* to distinguish one option from another; a plain
     sequential transition typically carries nothing extra. Once a type is
     established as a branch type from any example, every edge of that type
     is held to the same standard — see required_branch_attrs below, which
     is what lets check_structure() flag a same-type sibling edge that is
     missing the condition data the rest of its type carries.

  2. A node is a BRANCH NODE if every edge reaching it is of a branch type,
     and it has at least one incoming edge. Such a node exists only to hold
     a branch's condition; collapse_criteria() (in validate.py) resolves it
     away into a direct edge between the two real steps on either side of
     it. A node reachable by any non-branch edge, or with no incoming edge
     at all (an entry point), is a step.

Within that, which edge property holds the *expected value* a client
profile is checked against, and which one names *which* profile field to
check, is inferred from sibling branch edges leaving the same node: the
property that differs between siblings is the value; the property that
stays constant within one sibling group (but can differ across different
branch points elsewhere in the graph) is the field name. This needs at
least one node with two or more branch edges to have any evidence to work
from — a single, isolated branch edge carries no such signal, so
condition_key_attr/condition_value_attr stay unset until a real branch
point is available to learn from. Scenario checks that need them raise a
clear error rather than guessing when that happens.

None of this is foolproof — it is pattern-matching on typical shapes, not a
schema contract — but it asks nothing of the caller beyond a graphml file.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

# `rel` is normalize_graph()'s own bookkeeping (the relationship type,
# already accounted for separately). `id` is the exporter-assigned
# relationship id every graphml writer attaches to <edge> (networkx surfaces
# it as an ordinary edge attribute on read) — bookkeeping, not a domain
# property, and present on every edge regardless of type, so leaving it in
# would make every relationship type look "propertied".
RESERVED_EDGE_ATTRS = frozenset({"rel", "id"})


@dataclass(frozen=True)
class GraphSchema:
    branching_rels: frozenset
    branch_nodes: frozenset
    required_branch_attrs: tuple
    condition_key_attr: str | None
    condition_value_attr: str | None

    def is_branch(self, node) -> bool:
        return node in self.branch_nodes


def infer_schema(graph) -> GraphSchema:
    # 1. Which relationship types ever carry data beyond `rel`.
    props_by_rel = defaultdict(set)
    for _, _, data in graph.edges(data=True):
        extra = set(data) - RESERVED_EDGE_ATTRS
        if extra:
            props_by_rel[data.get("rel")] |= extra
    branching_rels = frozenset(props_by_rel)

    # 2. What every branch-type edge that carries data has in common — the
    # baseline every edge of that type is expected to meet.
    required_branch_attrs: set = set()
    propertied_edges = [
        data for _, _, data in graph.edges(data=True)
        if data.get("rel") in branching_rels and (set(data) - RESERVED_EDGE_ATTRS)
    ]
    if propertied_edges:
        required_branch_attrs = set.intersection(
            *(set(data) - RESERVED_EDGE_ATTRS for data in propertied_edges)
        )

    # 3. Nodes reachable only through branch-type edges are pass-throughs.
    branch_nodes = frozenset(
        n for n in graph.nodes
        if graph.in_degree(n) > 0
        and all(
            data.get("rel") in branching_rels
            for _, _, data in graph.in_edges(n, data=True)
        )
    )

    # 4. Among the common branch attributes, which one is "the value" (varies
    # between sibling branches from the same node) and which is "the field
    # name" (constant within a sibling group). Needs a real branch point —
    # a node with two or more branch edges — to have any signal at all.
    condition_value_attr = None
    condition_key_attr = None
    if required_branch_attrs:
        groups = defaultdict(list)
        for u, _, data in graph.edges(data=True):
            if data.get("rel") in branching_rels:
                groups[u].append(data)
        sibling_groups = [g for g in groups.values() if len(g) >= 2]

        for key in sorted(required_branch_attrs):
            if any(len({d.get(key) for d in g}) > 1 for g in sibling_groups):
                condition_value_attr = key
                break

        for key in sorted(required_branch_attrs - {condition_value_attr}):
            if sibling_groups and all(
                len({d.get(key) for d in g}) == 1 for g in sibling_groups
            ):
                condition_key_attr = key
                break

    return GraphSchema(
        branching_rels=branching_rels,
        branch_nodes=branch_nodes,
        required_branch_attrs=tuple(sorted(required_branch_attrs)),
        condition_key_attr=condition_key_attr,
        condition_value_attr=condition_value_attr,
    )
