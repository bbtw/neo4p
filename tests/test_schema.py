"""infer_schema(): structural inference of steps/branches/conditions, with
no hardcoded label or relationship-type names.

The last test in this file builds a graph in a completely different domain
(warehouse routing, not financial planning) with label/rel-type/attribute
names that share nothing with the original Task/CriteriaNode/HAS_CHILD/
CRITERIA_BRANCH vocabulary, and runs it through the same validate.py
functions the financial-planning fixtures use, to prove none of that
vocabulary is actually hardcoded anywhere in the pipeline.
"""

import networkx as nx

import validate
from schema import infer_schema


def test_branching_rel_needs_at_least_one_propertied_edge():
    graph = nx.DiGraph()
    graph.add_edge("a", "b", rel="NEXT")
    graph.add_edge("a", "c", rel="MAYBE", odds="60%")

    schema = infer_schema(graph)

    assert schema.branching_rels == {"MAYBE"}


def test_no_branching_rel_when_nothing_carries_extra_properties():
    graph = nx.DiGraph()
    graph.add_edge("a", "b", rel="NEXT")
    graph.add_edge("b", "c", rel="NEXT")

    schema = infer_schema(graph)

    assert schema.branching_rels == frozenset()
    assert schema.branch_nodes == frozenset()


def test_branch_node_needs_in_degree_and_all_incoming_edges_branching():
    graph = nx.DiGraph()
    graph.add_edge("a", "cn", rel="MAYBE", k="x", v="1")
    graph.add_edge("cn", "b", rel="NEXT")
    # entry point 'a' has in-degree zero: never a branch node even though it
    # only ever appears as the source of a branching edge.
    graph.add_edge("d", "cn", rel="NEXT")  # cn also reachable directly now

    schema = infer_schema(graph)

    assert not schema.is_branch("a")
    assert not schema.is_branch("cn")  # mixed incoming: no longer a pure branch


def test_required_branch_attrs_is_the_intersection_across_propertied_edges():
    graph = nx.DiGraph()
    graph.add_edge("a", "x", rel="MAYBE", k="fund_status", v="funded", extra="only_here")
    graph.add_edge("a", "y", rel="MAYBE", k="fund_status", v="empty")

    schema = infer_schema(graph)

    assert schema.required_branch_attrs == ("k", "v")


def test_condition_attrs_need_a_real_sibling_branch_point():
    """A single, isolated branch edge carries no signal distinguishing the
    'field name' property from the 'expected value' property."""
    graph = nx.DiGraph()
    graph.add_edge("a", "b", rel="MAYBE", k="fund_status", v="funded")

    schema = infer_schema(graph)

    assert schema.condition_key_attr is None
    assert schema.condition_value_attr is None


def test_condition_attrs_inferred_from_sibling_branches():
    graph = nx.DiGraph()
    # same source, same field name, different expected values: a real branch.
    graph.add_edge("a", "x", rel="MAYBE", k="fund_status", v="funded")
    graph.add_edge("a", "y", rel="MAYBE", k="fund_status", v="empty")

    schema = infer_schema(graph)

    assert schema.condition_key_attr == "k"
    assert schema.condition_value_attr == "v"


# --------------------------------------------------------------------------
# Domain-agnostic proof: a warehouse-routing graph with no relation to the
# financial-planning vocabulary, run through validate.py's real functions.
# --------------------------------------------------------------------------

def _stop(**overrides):
    return {"owner": "ops", "sop_doc": "wh-procedures-v9", **overrides}


def test_pipeline_works_on_a_completely_different_domain_vocabulary():
    """Warehouse routing: STOP nodes, GATE nodes (the branch-point
    equivalent), ROUTE (direct) and DECISION (conditional) relationships,
    with the condition stored as check_field/expected on the DECISION edge.
    None of these names exist anywhere in validate.py or schema.py."""
    graph = nx.DiGraph()
    graph.add_node("intake", **_stop())
    graph.add_node("ship", **_stop())
    graph.add_node("hold", **_stop())
    graph.add_node("fragile_gate", owner="ops")  # a GATE: no sop_doc, exempt
    graph.add_node("ship_gate", owner="ops")  # a GATE: no sop_doc, exempt

    graph.add_edge(
        "intake", "fragile_gate", rel="DECISION",
        check_field="fragile", expected="yes",
    )
    graph.add_edge(
        "intake", "ship_gate", rel="DECISION",
        check_field="fragile", expected="no",
    )
    graph.add_edge("fragile_gate", "hold", rel="ROUTE")
    graph.add_edge("ship_gate", "ship", rel="ROUTE")

    schema = infer_schema(graph)
    assert schema.is_branch("fragile_gate")
    assert not schema.is_branch("intake")
    assert schema.condition_key_attr == "check_field"
    assert schema.condition_value_attr == "expected"

    failures = validate.check_structure(
        graph, ["intake"], ["ship", "hold"], required_step_attrs=("owner", "sop_doc")
    )
    assert failures == []

    collapsed = validate.collapse_criteria(graph)
    assert set(collapsed.nodes) == {"intake", "ship", "hold"}
    assert collapsed["intake"]["hold"]["check_field"] == "fragile"

    paths = validate.enumerate_paths(collapsed, ["intake"], ["ship", "hold"])
    assert paths == [["intake", "hold"], ["intake", "ship"]]

    scenario_failures = validate.check_scenarios(
        collapsed,
        [
            {
                "name": "fragile item",
                "start": "intake",
                "profile": {"fragile": "yes"},
                "expected_path": ["intake", "hold"],
            }
        ],
        schema,
    )
    assert scenario_failures == []
