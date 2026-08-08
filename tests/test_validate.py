import networkx as nx
import pytest

import validate


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


def test_walk_raises_on_ambiguous_branch():
    graph = nx.DiGraph()
    graph.add_edge("x", "y1", condition_key="k1", condition_value="v1")
    graph.add_edge("x", "y2", condition_key="k2", condition_value="v2")
    profile = {"k1": "v1", "k2": "v2"}

    with pytest.raises(ValueError, match="ambiguous branch at 'x'"):
        validate.walk(graph, "x", profile)


def test_walk_follows_the_matching_edge():
    graph = nx.DiGraph()
    graph.add_edge("x", "y", condition_key="k", condition_value="match")
    graph.add_edge("x", "z", condition_key="k", condition_value="other")

    assert validate.walk(graph, "x", {"k": "match"}) == ["x", "y"]


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

    failures = validate.check_structure(graph, ["a"], ["b"])
    assert failures == []


def test_check_structure_requires_condition_on_criteria_branch_only():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH")  # missing condition_key/value
    graph.add_edge("cn", "b", rel="HAS_CHILD")

    failures = validate.check_structure(graph, ["a"], ["b"])
    assert len(failures) == 1
    assert "branch 'a' -> 'cn' missing" in failures[0]


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

    with pytest.raises(ValueError, match="must have exactly one HAS_CHILD"):
        validate.collapse_criteria(graph)
