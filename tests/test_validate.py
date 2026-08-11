import networkx as nx
import pytest

import validate
from shape import GraphShape

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


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

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


def test_check_rules_mutual_exclusion_message_lists_all_offenders():
    """Three-way exclusion used to report 'both appear'."""
    rules = [{"type": "mutual_exclusion", "steps": ["a", "b", "c"]}]
    failures = validate.check_rules([["a", "b", "c"]], rules)
    assert "both" not in failures[0]
    assert "['a', 'b', 'c']" in failures[0]


def test_check_rules_unknown_type():
    failures = validate.check_rules([["a"]], [{"type": "weird"}])
    assert failures == ["unknown rule type: 'weird'"]


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

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


def test_enumerate_paths_emits_a_single_node_journey():
    """A node that is both entry and terminal is a real zero-step journey.
    It used to be skipped entirely, so it could neither be approved nor
    flagged (ISSUES.md #10)."""
    graph = nx.DiGraph()
    graph.add_node("lone")
    graph.add_edge("entry", "terminal")

    paths = validate.enumerate_paths(graph, ["entry", "lone"], ["terminal", "lone"])

    assert ["lone"] in paths


# --------------------------------------------------------------------------
# walk / scenarios
# --------------------------------------------------------------------------

def test_walk_raises_on_ambiguous_branch():
    graph = nx.DiGraph()
    graph.add_edge("x", "y1", condition_key="k1", condition_value="v1")
    graph.add_edge("x", "y2", condition_key="k2", condition_value="v2")
    profile = {"k1": "v1", "k2": "v2"}

    with pytest.raises(ValueError, match="ambiguous branch at 'x'"):
        validate.walk(graph, "x", profile, SHAPE)


def test_walk_follows_the_matching_edge():
    graph = nx.DiGraph()
    graph.add_edge("x", "y", condition_key="k", condition_value="match")
    graph.add_edge("x", "z", condition_key="k", condition_value="other")

    assert validate.walk(graph, "x", {"k": "match"}, SHAPE) == ["x", "y"]


def test_walk_raises_rather_than_looping_forever_on_a_cycle():
    graph = nx.DiGraph()
    graph.add_edge("x", "y")
    graph.add_edge("y", "x")

    with pytest.raises(ValueError, match="revisited"):
        validate.walk(graph, "x", {}, SHAPE)


def test_check_scenarios_flags_missing_start_node():
    graph = nx.DiGraph()
    graph.add_node("real_start")
    scenarios = [
        {"name": "bad start", "start": "missing", "profile": {}, "expected_path": ["missing"]}
    ]

    failures = validate.check_scenarios(graph, scenarios, SHAPE)
    assert len(failures) == 1
    assert "not in graph" in failures[0]


def test_check_scenarios_refuses_to_run_without_declared_conditions():
    """A shape with no condition attributes cannot steer a branch. Saying so
    beats silently walking whichever edge comes first."""
    shapeless = GraphShape(
        step_labels=frozenset({"Task"}),
        branch_labels=frozenset(),
        branch_rels=frozenset(),
    )
    graph = nx.DiGraph()
    graph.add_edge("a", "b")
    scenarios = [
        {"name": "s", "start": "a", "profile": {"k": "v"}, "expected_path": ["a", "b"]}
    ]

    failures = validate.check_scenarios(graph, scenarios, shapeless)
    assert "declares no condition attributes" in failures[0]


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------

def test_check_structure_does_not_require_rationale_on_branch_nodes():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")
    graph.add_edge("cn", "b", rel="HAS_CHILD")

    assert validate.check_structure(graph, SHAPE, ["a"], ["b"]) == []


def test_check_structure_flags_branch_edge_missing_its_condition():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH")  # missing condition_key/value
    graph.add_edge("cn", "b", rel="HAS_CHILD")

    failures = validate.check_structure(graph, SHAPE, ["a"], ["b"])
    assert any("branch 'a' -> 'cn' missing" in f for f in failures)


def test_check_structure_flags_step_missing_documentation():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", labels="Task")  # no rationale, no source_doc
    graph.add_edge("a", "b", rel="HAS_CHILD")

    failures = validate.check_structure(graph, SHAPE, ["a"], ["b"])
    assert any("step 'b' missing" in f for f in failures)


def test_check_structure_flags_unreachable_nodes():
    """A detached island only counts as unreachable if nothing in it is an
    entry point — so the island here is a small cycle, which no entry leads
    to and which therefore no client could ever arrive at."""
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", **_task())
    graph.add_node("island_x", **_task())
    graph.add_node("island_y", **_task())
    graph.add_edge("a", "b", rel="HAS_CHILD")
    graph.add_edge("island_x", "island_y", rel="HAS_CHILD")
    graph.add_edge("island_y", "island_x", rel="HAS_CHILD")

    failures = validate.check_structure(graph, SHAPE, ["a"], ["b"])
    assert any("unreachable nodes" in f for f in failures)
    assert any("island_x" in f for f in failures)


# --------------------------------------------------------------------------
# collapse_branches
# --------------------------------------------------------------------------

def test_collapse_resolves_step_branch_step_chain():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")
    graph.add_edge("cn", "b", rel="HAS_CHILD")

    collapsed = validate.collapse_branches(graph, SHAPE)

    assert set(collapsed.nodes) == {"a", "b"}
    assert collapsed["a"]["b"]["condition_key"] == "k"
    assert collapsed["a"]["b"]["condition_value"] == "v"


def test_collapse_keeps_direct_step_to_step_edge():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", **_task())
    graph.add_edge("a", "b", rel="HAS_CHILD")

    collapsed = validate.collapse_branches(graph, SHAPE)

    assert list(collapsed.edges) == [("a", "b")]


def test_collapse_raises_on_branch_node_without_exactly_one_child():
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn", **_criteria())
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")

    with pytest.raises(ValueError, match="must have exactly one direct child"):
        validate.collapse_branches(graph, SHAPE)


def test_collapse_raises_rather_than_silently_dropping_a_parallel_branch():
    """Two branches from the same source resolving to the same step used to
    overwrite each other, discarding the first condition (ISSUES.md #5)."""
    graph = nx.DiGraph()
    graph.add_node("a", **_task())
    graph.add_node("cn1", **_criteria())
    graph.add_node("cn2", **_criteria())
    graph.add_node("b", **_task())
    graph.add_edge("a", "cn1", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v1")
    graph.add_edge("a", "cn2", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v2")
    graph.add_edge("cn1", "b", rel="HAS_CHILD")
    graph.add_edge("cn2", "b", rel="HAS_CHILD")

    with pytest.raises(ValueError, match="both resolve to"):
        validate.collapse_branches(graph, SHAPE)


# --------------------------------------------------------------------------
# normalize_graph: export-format reconciliation only. Domain classification
# (step vs. branch, which rel is conditional) is shape.yaml's job now.
# --------------------------------------------------------------------------

def _apoc_graph() -> nx.DiGraph:
    """A two-task graph shaped like a scoped apoc.export.graphml output:
    relationship type under `label` rather than `rel`, exporter-assigned node
    ids with the business id carried through as an ordinary `id` property,
    and a bookkeeping edge `id` (every graphml edge has one)."""
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


def test_normalize_graph_is_a_no_op_on_the_pipelines_own_format():
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


def test_normalize_graph_stringifies_integer_business_ids():
    """An APOC export with useTypes:true can yield integer ids; a later
    sorted() over mixed str/int node keys raised TypeError (ISSUES.md #9)."""
    graph = nx.DiGraph()
    graph.add_node("n0", id=42, rationale="r", source_doc="d")
    graph.add_node("n1", id="b", rationale="r", source_doc="d")
    graph.add_edge("n0", "n1", rel="HAS_CHILD")

    normalized = validate.normalize_graph(graph)

    assert set(normalized.nodes) == {"42", "b"}
    assert sorted(normalized.nodes) == ["42", "b"]


def test_normalize_graph_rejects_parallel_relationships():
    """A MultiDiGraph silently misbehaves under this module's DiGraph
    assumptions, so it is refused outright (ISSUES.md #6)."""
    graph = nx.MultiDiGraph()
    graph.add_node("a", **_task())
    graph.add_node("b", **_task())
    graph.add_edge("a", "b", rel="HAS_CHILD")
    graph.add_edge("a", "b", rel="ALSO_LEADS_TO")

    with pytest.raises(ValueError, match="parallel relationships"):
        validate.normalize_graph(graph)
