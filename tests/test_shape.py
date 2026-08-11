"""shape.py: loading a declared shape, and catching a graph that contradicts it.

The two regression tests at the bottom are the reason this module exists.
Both are the exact repro cases recorded in docs/ISSUES.md against the old
`schema.infer_schema()`, where a single incidental edge property could
silently reclassify a real client-facing step as a branch point — deleting it
from the graph before path enumeration and exempting it from documentation
checks, with zero failures raised anywhere.
"""

import networkx as nx
import pytest

import validate
from shape import GraphShape, check_shape, load_shape

SHAPE = GraphShape(
    step_labels=frozenset({"Task"}),
    branch_labels=frozenset({"CriteriaNode"}),
    branch_rels=frozenset({"CRITERIA_BRANCH"}),
    condition_key_attr="condition_key",
    condition_value_attr="condition_value",
    required_step_attrs=("rationale", "source_doc"),
    required_branch_attrs=("condition_key", "condition_value"),
)


def _task(**overrides):
    return {"labels": "Task", "rationale": "r", "source_doc": "d", **overrides}


def _criteria(**overrides):
    return {"labels": "CriteriaNode", **overrides}


def _well_formed() -> nx.DiGraph:
    """step -CRITERIA_BRANCH-> branch node -HAS_CHILD-> step."""
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")
    graph.add_edge("cn", "b", rel="HAS_CHILD")
    return graph


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def _write(tmp_path, body: str):
    path = tmp_path / "shape.yaml"
    path.write_text(body)
    return path


MINIMAL = """
step_labels: [Task]
branch_labels: [CriteriaNode]
branch_rels: [CRITERIA_BRANCH]
"""


def test_load_shape_reads_the_sample_shape(sample_shape_path):
    shape = load_shape(sample_shape_path)
    assert shape.step_labels == {"Task"}
    assert shape.branch_labels == {"CriteriaNode"}
    assert shape.branch_rels == {"CRITERIA_BRANCH"}
    assert shape.condition_key_attr == "condition_key"
    assert shape.required_step_attrs == ("rationale", "source_doc")


def test_load_shape_accepts_a_minimal_shape(tmp_path):
    shape = load_shape(_write(tmp_path, MINIMAL))
    assert shape.condition_key_attr is None
    assert shape.required_step_attrs == ()


def test_load_shape_rejects_a_missing_required_key(tmp_path):
    with pytest.raises(ValueError, match="missing required key"):
        load_shape(_write(tmp_path, "step_labels: [Task]\nbranch_labels: []\n"))


def test_load_shape_rejects_an_unknown_key(tmp_path):
    """A typo'd key must be an error, never a silently ignored default."""
    with pytest.raises(ValueError, match="unknown key"):
        load_shape(_write(tmp_path, MINIMAL + "requird_step_attrs: [rationale]\n"))


def test_load_shape_rejects_a_condition_key_without_a_value(tmp_path):
    """A key with no value made every condition compare against None, so no
    edge was ever allowed — silently, and only in scenario walks
    (ISSUES.md #8)."""
    with pytest.raises(ValueError, match="declared together"):
        load_shape(_write(tmp_path, MINIMAL + "condition_key_attr: condition_key\n"))


def test_load_shape_rejects_a_label_listed_as_both_step_and_branch(tmp_path):
    body = "step_labels: [Task]\nbranch_labels: [Task]\nbranch_rels: []\n"
    with pytest.raises(ValueError, match="both step and branch"):
        load_shape(_write(tmp_path, body))


def test_load_shape_rejects_empty_step_labels(tmp_path):
    body = "step_labels: []\nbranch_labels: [CriteriaNode]\nbranch_rels: []\n"
    with pytest.raises(ValueError, match="nothing would be validated"):
        load_shape(_write(tmp_path, body))


def test_load_shape_rejects_a_scalar_where_a_list_belongs(tmp_path):
    body = "step_labels: Task\nbranch_labels: []\nbranch_rels: []\n"
    with pytest.raises(ValueError, match="must be a list"):
        load_shape(_write(tmp_path, body))


# --------------------------------------------------------------------------
# label parsing across export formats
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Task", {"Task"}),
        (":Task", {"Task"}),               # APOC's leading-colon form
        ("Task:Reviewed", {"Task", "Reviewed"}),
        (":Task:Reviewed", {"Task", "Reviewed"}),
        ("", set()),
    ],
)
def test_labels_parse_the_same_across_export_formats(raw, expected):
    assert GraphShape.labels_of({"labels": raw}) == expected


def test_a_node_with_several_labels_is_a_step_if_any_label_is_a_step_label():
    assert SHAPE.is_step_node({"labels": "Task:Reviewed"})


# --------------------------------------------------------------------------
# check_shape
# --------------------------------------------------------------------------

def test_check_shape_passes_on_a_well_formed_graph():
    assert check_shape(_well_formed(), SHAPE) == []


def test_check_shape_passes_on_the_sample_graph(sample_graph, sample_shape_path):
    graph = validate.normalize_graph(nx.read_graphml(sample_graph))
    assert check_shape(graph, load_shape(sample_shape_path)) == []


def test_check_shape_flags_a_node_with_no_labels():
    graph = _well_formed()
    graph.add_node("mystery", rationale="r", source_doc="d")
    graph.add_edge("b", "mystery", rel="HAS_CHILD")

    failures = check_shape(graph, SHAPE)
    assert any("no labels attribute" in f for f in failures)


def test_check_shape_flags_a_node_with_an_undeclared_label():
    """This is what an unscoped whole-database export looks like: extra
    material the shape says nothing about. It must be loud, not ignored."""
    graph = _well_formed()
    graph.add_node("acct1", labels="Account")
    graph.add_edge("b", "acct1", rel="OWNS")

    failures = check_shape(graph, SHAPE)
    assert any("match no declared label" in f for f in failures)


def test_check_shape_flags_a_declared_branch_rel_that_appears_nowhere():
    """A typo in branch_rels would otherwise mean 'this graph has no
    branches' and quietly switch off every branch check."""
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", **_task())
    graph.add_edge("a", "b", rel="HAS_CHILD")

    failures = check_shape(graph, SHAPE)
    assert any("appear on no edge" in f for f in failures)


def test_check_shape_flags_a_branch_node_reached_by_a_non_branch_edge():
    graph = _well_formed()
    graph.add_node("cn2", **_criteria())
    graph.add_node("c", **_task())
    graph.add_edge("b", "cn2", rel="HAS_CHILD")  # should be CRITERIA_BRANCH
    graph.add_edge("cn2", "c", rel="HAS_CHILD")

    failures = check_shape(graph, SHAPE)
    assert any("reached by non-branch edge" in f for f in failures)


def test_check_shape_flags_a_branch_edge_that_lands_on_a_step():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", **_task())
    graph.add_edge("a", "b", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")

    failures = check_shape(graph, SHAPE)
    assert any("does not lead to a node with a branch label" in f for f in failures)


def test_check_shape_flags_chained_branch_nodes():
    graph = _well_formed()
    graph.add_node("cn2", **_criteria())
    graph.add_node("c", **_task())
    graph.add_edge("cn", "cn2", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")
    graph.add_edge("cn2", "c", rel="HAS_CHILD")

    failures = check_shape(graph, SHAPE)
    assert any("may not chain" in f for f in failures)


def test_check_shape_flags_a_branch_node_with_two_children():
    graph = _well_formed()
    graph.add_node("c", **_task())
    graph.add_edge("cn", "c", rel="HAS_CHILD")

    failures = check_shape(graph, SHAPE)
    assert any("exactly one outgoing edge" in f for f in failures)


def test_check_shape_flags_a_branch_edge_missing_its_declared_condition():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH")  # no condition attrs
    graph.add_edge("cn", "b", rel="HAS_CHILD")

    failures = check_shape(graph, SHAPE)
    assert any("missing declared condition attribute" in f for f in failures)


# --------------------------------------------------------------------------
# Regression: the two silent misclassifications from docs/ISSUES.md #2.
#
# Under inference, ANY single edge carrying a property beyond `rel`/`id` made
# its whole relationship type a "branch type", with no evidence of a fork.
# Both graphs below are legitimate; neither has a branch point in it. The old
# code turned a real step into one anyway.
# --------------------------------------------------------------------------

def test_incidental_edge_property_no_longer_reclassifies_a_step():
    """Repro 1: one edge of a shared rel type picks up an incidental property
    (a tracking id). Under inference this cascaded — every node reached only
    via that type became a 'branch'. Under a declared shape, an edge property
    cannot change what a node IS."""
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", **_task())
    graph.add_node("c", **_task())
    graph.add_edge("a", "b", rel="HAS_CHILD", note="internal tracking id")
    graph.add_edge("b", "c", rel="HAS_CHILD")

    shape = GraphShape(
        step_labels=frozenset({"Task"}),
        branch_labels=frozenset({"CriteriaNode"}),
        branch_rels=frozenset(),
        required_step_attrs=("rationale", "source_doc"),
    )

    assert check_shape(graph, shape) == []
    collapsed = validate.collapse_branches(graph, shape)
    assert set(collapsed.nodes) == {"a", "b", "c"}, "b must survive collapse"
    assert validate.enumerate_paths(collapsed, ["a"], ["c"]) == [["a", "b", "c"]]


def test_a_second_kg_with_a_completely_different_vocabulary():
    """Warehouse routing, not financial planning: STOP nodes, GATE nodes (the
    branch-point equivalent), ROUTE (direct) and DECISION (conditional)
    relationships, condition stored as check_field/expected. None of these
    names appear anywhere in validate.py or shape.py — the shape file is the
    only place a graph's vocabulary is written down, which is what lets one
    pipeline govern several graphs of different shapes."""
    warehouse = GraphShape(
        step_labels=frozenset({"Stop"}),
        branch_labels=frozenset({"Gate"}),
        branch_rels=frozenset({"DECISION"}),
        condition_key_attr="check_field",
        condition_value_attr="expected",
        required_step_attrs=("owner", "sop_doc"),
        required_branch_attrs=("check_field", "expected"),
    )

    def stop(**kw):
        return {"labels": "Stop", "owner": "ops", "sop_doc": "wh_v1", **kw}

    graph = nx.DiGraph()
    graph.add_node("intake", **stop())
    graph.add_node("ship", **stop())
    graph.add_node("hold", **stop())
    graph.add_node("fragile_gate", labels="Gate", owner="ops")  # no sop_doc: exempt
    graph.add_node("ship_gate", labels="Gate", owner="ops")
    graph.add_edge("intake", "fragile_gate", rel="DECISION", check_field="fragile", expected="yes")
    graph.add_edge("intake", "ship_gate", rel="DECISION", check_field="fragile", expected="no")
    graph.add_edge("fragile_gate", "hold", rel="ROUTE")
    graph.add_edge("ship_gate", "ship", rel="ROUTE")

    assert check_shape(graph, warehouse) == []
    assert validate.check_structure(graph, warehouse, ["intake"], ["ship", "hold"]) == []

    collapsed = validate.collapse_branches(graph, warehouse)
    assert set(collapsed.nodes) == {"intake", "ship", "hold"}
    assert collapsed["intake"]["hold"]["check_field"] == "fragile"

    paths = validate.enumerate_paths(collapsed, ["intake"], ["ship", "hold"])
    assert paths == [["intake", "hold"], ["intake", "ship"]]

    assert validate.check_scenarios(
        collapsed,
        [
            {
                "name": "fragile item",
                "start": "intake",
                "profile": {"fragile": "yes"},
                "expected_path": ["intake", "hold"],
            }
        ],
        warehouse,
    ) == []


def test_the_financial_shape_rejects_the_warehouse_graph():
    """The corollary: applying the wrong KG's shape file fails loudly at the
    shape layer instead of producing confident, meaningless results."""
    graph = nx.DiGraph()
    graph.add_node("intake", labels="Stop", owner="ops", sop_doc="wh_v1")
    graph.add_node("ship", labels="Stop", owner="ops", sop_doc="wh_v1")
    graph.add_edge("intake", "ship", rel="ROUTE")

    failures = check_shape(graph, SHAPE)
    assert any("match no declared label" in f for f in failures)


def test_undocumented_passthrough_step_is_caught_not_silently_deleted():
    """Repro 2, the dangerous one. `b` is a real client-facing step that is
    missing its required documentation, reached by a one-off rel carrying an
    unrelated property. Under inference, check_structure() returned ZERO
    failures (b was classified a branch, and branches are exempt from
    required_step_attrs) and collapse then deleted b from the graph outright.
    A step could ship with no rationale and no source_doc, undetected.

    Under a declared shape, b is labelled Task, so it is a step, so its
    missing documentation is a failure — and it stays in the graph."""
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", labels="Task")  # deliberately undocumented
    graph.add_node("c", **_task())
    graph.add_edge("a", "b", rel="SPECIAL", note="internal tracking id")
    graph.add_edge("b", "c", rel="HAS_CHILD")

    shape = GraphShape(
        step_labels=frozenset({"Task"}),
        branch_labels=frozenset({"CriteriaNode"}),
        branch_rels=frozenset(),
        required_step_attrs=("rationale", "source_doc"),
    )

    failures = validate.check_structure(graph, shape, ["a"], ["c"])
    assert any("step 'b' missing" in f for f in failures), (
        "the undocumented step must be reported, not exempted"
    )
    assert "rationale" in failures[0] and "source_doc" in failures[0]

    collapsed = validate.collapse_branches(graph, shape)
    assert "b" in collapsed.nodes, "the step must not be deleted from the graph"
