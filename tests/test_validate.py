import networkx as nx
import pytest

import validate
from schema import GraphSchema


def test_check_rules_precedence_violation():
    rules = [{"type": "precedence", "before": "b", "after": "a"}]
    failures = validate.check_rules([["a", "b", "c"]], rules)
    assert len(failures) == 1
    assert "precedence rule violated" in failures[0]
    assert "'b'" in failures[0] and "'a'" in failures[0]


def test_check_rules_precedence_satisfied():
    rules = [{"type": "precedence", "before": "a", "after": "b"}]
    assert validate.check_rules([["a", "b", "c"]], rules) == []


def test_check_rules_mutual_exclusion_violation():
    rules = [{"type": "mutual_exclusion", "steps": ["a", "b"]}]
    failures = validate.check_rules([["a", "b", "c"]], rules)
    assert len(failures) == 1
    assert "mutual exclusion rule violated" in failures[0]


def test_check_rules_mutual_exclusion_satisfied():
    rules = [{"type": "mutual_exclusion", "steps": ["a", "d"]}]
    assert validate.check_rules([["a", "b", "c"]], rules) == []


def test_check_rules_unknown_type():
    failures = validate.check_rules([["a"]], [{"type": "weird"}])
    assert failures == ["unknown rule type: 'weird'"]


def test_check_paths_flags_unapproved_journey():
    failures = validate.check_paths(actual=[["a", "b"], ["a", "c"]], approved=[["a", "b"]])
    assert failures == ["unapproved client journey: ['a', 'c']"]


def test_check_paths_flags_vanished_journey():
    failures = validate.check_paths(actual=[["a", "b"]], approved=[["a", "b"], ["a", "c"]])
    assert failures == ["approved journey no longer possible: ['a', 'c']"]


def test_check_paths_exact_match_has_no_failures():
    paths = [["a", "b"], ["a", "c"]]
    assert validate.check_paths(actual=paths, approved=paths) == []


def test_enumerate_paths_raises_past_max_paths(monkeypatch):
    monkeypatch.setattr(validate, "MAX_PATHS", 2)
    graph = nx.DiGraph()
    for branch in ("a", "b", "c"):
        graph.add_edge("entry", branch)
        graph.add_edge(branch, "terminal")

    with pytest.raises(ValueError, match="more than 2 distinct client journeys"):
        validate.enumerate_paths(graph, ["entry"], ["terminal"])


def _explicit_schema(condition_key_attr="condition_key", condition_value_attr="condition_value"):
    """A schema built by hand rather than inferred, for tests that exercise
    walk()'s branch-selection logic in isolation from schema inference
    itself (which is tested separately, below)."""
    return GraphSchema(
        branching_rels=frozenset({None}),
        branch_nodes=frozenset(),
        required_branch_attrs=(condition_key_attr, condition_value_attr),
        condition_key_attr=condition_key_attr,
        condition_value_attr=condition_value_attr,
    )


def test_walk_raises_on_ambiguous_branch():
    graph = nx.DiGraph()
    graph.add_edge("x", "y1", condition_key="k1", condition_value="v1")
    graph.add_edge("x", "y2", condition_key="k2", condition_value="v2")
    profile = {"k1": "v1", "k2": "v2"}

    with pytest.raises(ValueError, match="ambiguous branch at 'x'"):
        validate.walk(graph, "x", profile, _explicit_schema())


def test_walk_follows_the_matching_edge():
    graph = nx.DiGraph()
    graph.add_edge("x", "y", condition_key="k", condition_value="match")
    graph.add_edge("x", "z", condition_key="k", condition_value="other")

    assert validate.walk(graph, "x", {"k": "match"}, _explicit_schema()) == ["x", "y"]


def test_check_scenarios_flags_missing_start_node():
    graph = nx.DiGraph()
    graph.add_node("real_start")
    scenarios = [
        {"name": "bad start", "start": "missing", "profile": {}, "expected_path": ["missing"]}
    ]

    failures = validate.check_scenarios(graph, scenarios)
    assert len(failures) == 1
    assert "not in graph" in failures[0]


def _task(**overrides):
    return {"labels": "Task", "rationale": "r", "source_doc": "d", **overrides}


def _criteria(**overrides):
    return {"labels": "CriteriaNode", **overrides}


def test_check_structure_does_not_require_rationale_on_criteria_nodes():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")
    graph.add_edge("cn", "b", rel="HAS_CHILD")

    failures = validate.check_structure(
        graph, ["a"], ["b"], required_step_attrs=("rationale", "source_doc")
    )
    assert failures == []


def test_check_structure_requires_condition_on_criteria_branch_only():
    """CRITERIA_BRANCH is established as a branch type by cn2's edge, which
    does carry a condition; that lets the malformed 'a' -> 'cn' edge (same
    type, no condition) be recognized as missing what its type requires."""
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("cn2", **_criteria())
    graph.add_node("b", **_task())
    graph.add_node("c", **_task())
    graph.add_edge("a", "cn2", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")
    graph.add_edge("cn2", "c", rel="HAS_CHILD")
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH")  # missing condition_key/value
    graph.add_edge("cn", "b", rel="HAS_CHILD")

    failures = validate.check_structure(graph, ["a"], ["b", "c"])
    assert any("branch 'a' -> 'cn' missing" in f for f in failures)


def test_collapse_criteria_resolves_task_criteria_task_chain():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")
    graph.add_edge("cn", "b", rel="HAS_CHILD")

    collapsed = validate.collapse_criteria(graph)

    assert set(collapsed.nodes) == {"a", "b"}
    assert collapsed["a"]["b"]["condition_key"] == "k"
    assert collapsed["a"]["b"]["condition_value"] == "v"


def test_collapse_criteria_keeps_direct_task_to_task_edge():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", **_task())
    graph.add_edge("a", "b", rel="HAS_CHILD")

    collapsed = validate.collapse_criteria(graph)

    assert list(collapsed.edges) == [("a", "b")]


def test_collapse_criteria_raises_on_criteria_node_without_exactly_one_child():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")

    with pytest.raises(ValueError, match="must have exactly one direct child"):
        validate.collapse_criteria(graph)


# --------------------------------------------------------------------------
# normalize_graph: reconciling export-format differences only. Domain
# classification (step vs. branch, which rel is conditional) is not its job
# any more — see the schema.py tests below for that.
# --------------------------------------------------------------------------

def _apoc_graph() -> nx.DiGraph:
    """A two-task graph shaped like a scoped apoc.export.graphml output:
    relationship type under `label` rather than `rel`, exporter-assigned
    node ids with the business id carried through as an ordinary `id`
    property, and a bookkeeping edge `id` (every graphml edge has one)."""
    graph = nx.DiGraph()
    graph.add_node("n0", id="a", rationale="r", source_doc="d")
    graph.add_node("n1", id="b", rationale="r", source_doc="d")
    graph.add_edge("n0", "n1", label="HAS_CHILD", id="e0")
    return graph


def test_normalize_graph_backfills_rel_from_label():
    normalized = validate.normalize_graph(_apoc_graph())
    assert normalized["a"]["b"]["rel"] == "HAS_CHILD"


def test_normalize_graph_does_not_leave_the_source_key_behind():
    normalized = validate.normalize_graph(_apoc_graph())
    assert "label" not in normalized["a"]["b"]


def test_normalize_graph_relabels_nodes_to_business_id():
    normalized = validate.normalize_graph(_apoc_graph())
    assert set(normalized.nodes) == {"a", "b"}


def test_normalize_graph_is_a_no_op_on_snapshot_pys_own_format():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", **_task())
    graph.add_edge("a", "b", rel="HAS_CHILD")

    normalized = validate.normalize_graph(graph)

    assert set(normalized.nodes) == {"a", "b"}
    assert normalized["a"]["b"]["rel"] == "HAS_CHILD"


def test_normalize_graph_raises_on_colliding_business_ids():
    graph = nx.DiGraph()
    graph.add_node("n0", id="dup", rationale="r", source_doc="d")
    graph.add_node("n1", id="dup", rationale="r", source_doc="d")

    with pytest.raises(ValueError, match="duplicate business ids"):
        validate.normalize_graph(graph)
