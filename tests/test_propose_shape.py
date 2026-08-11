"""propose_shape.py either determines a field or refuses to.

The contract under test: no field is ever the result of a tie-break, a
sample of one, or a "first plausible candidate wins" search. Every test here
is a graph whose evidence admits more than one reading, asserting that the
tool says so instead of picking.

The complement matters just as much — `test_determines_a_complete_shape...`
pins that an unambiguous graph still resolves cleanly, so "refuse" cannot
degenerate into refusing everything.
"""

import subprocess
import sys
from pathlib import Path

import networkx as nx
import pytest
import yaml

import propose_shape
from shape import UNRESOLVED, load_shape
from validate import normalize_graph

SRC = Path(__file__).parent.parent / "src"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "propose_shape.py", *args],
        cwd=SRC,
        capture_output=True,
        text=True,
        check=False,
    )


def _task(**kw):
    return {"labels": "Task", "rationale": "r", "source_doc": "d", **kw}


def _propose(graph):
    return propose_shape.propose(normalize_graph(graph))


def _branching_graph(**extra_edge_attrs) -> nx.DiGraph:
    """A genuine fork: start branches through two criteria nodes."""
    graph = nx.DiGraph()
    for node in ("start", "roth", "taxable"):
        graph.add_node(node, **_task())
    for node in ("cn_a", "cn_b"):
        graph.add_node(node, labels="CriteriaNode")
    graph.add_edge(
        "start", "cn_a", rel="CRITERIA_BRANCH",
        condition_key="vehicle", condition_value="roth", **extra_edge_attrs,
    )
    graph.add_edge(
        "start", "cn_b", rel="CRITERIA_BRANCH",
        condition_key="vehicle", condition_value="taxable",
        **{k: v + "_b" for k, v in extra_edge_attrs.items()},
    )
    graph.add_edge("cn_a", "roth", rel="HAS_CHILD")
    graph.add_edge("cn_b", "taxable", rel="HAS_CHILD")
    return graph


# --------------------------------------------------------------------------
# the positive case: unambiguous evidence still resolves
# --------------------------------------------------------------------------

def test_determines_a_complete_shape_from_an_unambiguous_graph():
    draft, _, questions = _propose(_branching_graph())

    assert questions == []
    assert UNRESOLVED not in str(draft)
    assert draft["step_labels"] == ["Task"]
    assert draft["branch_labels"] == ["CriteriaNode"]
    assert draft["branch_rels"] == ["CRITERIA_BRANCH"]
    assert draft["condition_key_attr"] == "condition_key"
    assert draft["condition_value_attr"] == "condition_value"


def test_the_committed_sample_shape_is_what_the_tool_determines(
    sample_graph, sample_shape_path
):
    """The hand-reviewed shape and the tool's determination must agree — if
    they drift, one of them is wrong."""
    draft, _, questions = _propose(nx.read_graphml(sample_graph))
    committed = load_shape(sample_shape_path)

    assert questions == []
    assert set(draft["step_labels"]) == committed.step_labels
    assert set(draft["branch_labels"]) == committed.branch_labels
    assert set(draft["branch_rels"]) == committed.branch_rels
    assert draft["condition_key_attr"] == committed.condition_key_attr
    assert draft["condition_value_attr"] == committed.condition_value_attr


def test_exit_code_0_when_a_complete_shape_is_determined(sample_graph):
    assert run(str(sample_graph)).returncode == 0


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------

def test_two_varying_attributes_refuses_rather_than_taking_the_first():
    """An audit timestamp on every branch edge varies between siblings just
    like the real condition does. The old code took whichever sorted first —
    'audit_ts' — and silently produced a shape whose scenario walks compared
    client profiles against timestamps."""
    draft, evidence, questions = _propose(_branching_graph(audit_ts="2026-01-02"))

    assert draft["condition_value_attr"] == UNRESOLVED
    assert any("audit_ts" in q and "condition_value" in q for q in questions)
    assert any("2 attributes differ" in line for line in evidence)
    # the unambiguous half is still determined
    assert draft["condition_key_attr"] == "condition_key"


def test_a_passthrough_label_with_no_fork_refuses():
    """A real client-facing step that always sits between two others is
    shaped exactly like a condition-carrier. Without a fork there is no
    evidence to tell them apart."""
    graph = nx.DiGraph()
    for node in ("intake", "advice", "sign"):
        graph.add_node(node, **_task())
    graph.add_node(
        "risk_disclosure", labels="Disclosure",
        rationale="reg requirement", source_doc="finra_2111",
    )
    graph.add_edge("intake", "risk_disclosure", rel="NEXT")
    graph.add_edge("risk_disclosure", "advice", rel="NEXT")
    graph.add_edge("advice", "sign", rel="NEXT")

    draft, _, questions = _propose(graph)

    assert UNRESOLVED in draft["branch_labels"]
    assert any("Disclosure" in q for q in questions)


def test_a_single_node_label_is_not_a_sample_to_classify_from():
    graph = _branching_graph()
    graph.add_node("lone", labels="Oddity", rationale="r", source_doc="d")
    graph.add_edge("roth", "lone", rel="HAS_CHILD")
    graph.add_edge("lone", "taxable", rel="HAS_CHILD")

    _, _, questions = _propose(graph)

    assert any("Oddity" in q for q in questions)


def test_an_outlier_label_from_an_unscoped_export_refuses(apoc_wholedb_graph):
    """acct1 is connected to the flow by an OWNS edge, so it cannot be
    dismissed as a detached component — and nothing in the topology says
    whether an Account belongs in a planning flow. That is a question for a
    human, not a default."""
    draft, _, questions = _propose(nx.read_graphml(apoc_wholedb_graph))

    assert UNRESOLVED in str(draft)
    assert any("Account" in q for q in questions)


def test_a_redundant_secondary_label_does_not_refuse(apoc_graph):
    """'Reviewed' sits on a node that also carries 'Task'. That is a tag on a
    step, not a new kind of thing, and must not be treated as ambiguous."""
    draft, _, questions = _propose(nx.read_graphml(apoc_graph))

    assert questions == [], f"should have resolved cleanly, asked: {questions}"
    assert set(draft["step_labels"]) == {"Task", "Reviewed"}


def test_derived_fields_refuse_when_the_labels_they_depend_on_are_undecided():
    """branch_rels and the condition attributes are computed from the label
    classification. Emitting numbers derived from an undecided premise would
    be the same sin in a different place."""
    graph = nx.DiGraph()
    for node in ("intake", "advice", "sign"):
        graph.add_node(node, **_task())
    graph.add_node("gate", labels="Maybe", rationale="r", source_doc="d")
    graph.add_edge("intake", "gate", rel="NEXT")
    graph.add_edge("gate", "advice", rel="NEXT")
    graph.add_edge("advice", "sign", rel="NEXT")

    draft, _, _ = _propose(graph)

    for key in ("branch_rels", "condition_key_attr", "required_step_attrs"):
        assert draft[key] == UNRESOLVED, f"{key} was settled on an undecided premise"


def test_near_miss_attributes_are_reported_not_intersected_away():
    """One step missing source_doc would drop it from the intersection, so a
    documentation gap silently becomes the standard. It must be named."""
    graph = _branching_graph()
    del graph.nodes["taxable"]["source_doc"]

    draft, evidence, _ = _propose(graph)

    assert "source_doc" not in draft["required_step_attrs"]
    assert any("near-miss" in line and "source_doc" in line for line in evidence)
    assert any("taxable" in line for line in evidence if "near-miss" in line)


# --------------------------------------------------------------------------
# a refused draft must be unusable, not merely annotated
# --------------------------------------------------------------------------

def test_exit_code_1_and_a_draft_that_will_not_load(tmp_path):
    graph = _branching_graph(audit_ts="2026-01-02")
    graphml = tmp_path / "graph.graphml"
    nx.write_graphml(graph, graphml)
    out = tmp_path / "shape.yaml"

    result = run(str(graphml), "-o", str(out))

    assert result.returncode == 1
    assert "UNRESOLVED" in result.stdout

    # the draft is valid YAML, and carries the question as a comment...
    parsed = yaml.safe_load(out.read_text())
    assert parsed["condition_value_attr"] == UNRESOLVED
    assert "audit_ts" in out.read_text()

    # ...but cannot be used until a human decides
    with pytest.raises(ValueError, match="still marked UNRESOLVED"):
        load_shape(out)


def test_load_shape_names_every_unresolved_field(tmp_path):
    path = tmp_path / "shape.yaml"
    path.write_text(
        "step_labels: [Task]\n"
        "branch_labels: [UNRESOLVED]\n"
        "branch_rels: UNRESOLVED\n"
        "condition_key_attr: condition_key\n"
        "condition_value_attr: UNRESOLVED\n"
    )

    with pytest.raises(ValueError) as exc:
        load_shape(path)

    message = str(exc.value)
    for field in ("branch_labels", "branch_rels", "condition_value_attr"):
        assert field in message
    assert "condition_key_attr" not in message.split("—")[1].split(".")[0]


def test_load_shape_reports_malformed_yaml_as_a_value_error(tmp_path):
    path = tmp_path / "shape.yaml"
    path.write_text("step_labels: [Task\nbranch_labels: oops\n")

    with pytest.raises(ValueError, match="not valid YAML"):
        load_shape(path)
