"""End-to-end checks that bootstrap.py's draft faithfully mirrors the graph.

Fidelity is testable; whether the graph's current behavior is *right* is the
human review and cannot be tested here.
"""

import subprocess
import sys
from pathlib import Path

import networkx as nx
import pytest
import yaml

SRC = Path(__file__).parent.parent / "src"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script, *args], cwd=SRC, capture_output=True, text=True, check=False
    )


@pytest.fixture
def draft(sample_graph, sample_shape_path, tmp_path) -> Path:
    out = tmp_path / "draft.yaml"
    result = run("bootstrap.py", str(sample_graph), str(sample_shape_path), "-o", str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_draft_matches_the_committed_baseline(draft, sample_expectations_path):
    """The committed baseline was reviewed by hand; a fresh draft must
    independently arrive at the same entries, terminals, paths and rules."""
    got = yaml.safe_load(draft.read_text())
    want = yaml.safe_load(sample_expectations_path.read_text())

    assert sorted(got["expected_entries"]) == sorted(want["expected_entries"])
    assert sorted(got["expected_terminals"]) == sorted(want["expected_terminals"])
    assert sorted(map(tuple, got["approved_paths"])) == sorted(
        map(tuple, want["approved_paths"])
    )
    for rule in want["rules"]:
        assert rule in got["rules"], f"committed rule not mined: {rule}"


def test_draft_carries_no_scenarios(draft):
    """Scenarios cannot be derived from topology; the draft must leave them
    empty rather than invent any."""
    assert yaml.safe_load(draft.read_text())["scenarios"] == []


def test_validate_passes_against_own_draft(sample_graph, sample_shape_path, draft):
    """By construction: a graph always validates against its own baseline."""
    result = run("validate.py", str(sample_graph), str(sample_shape_path), str(draft))
    assert result.returncode == 0, result.stdout + result.stderr


def test_mutated_graph_fails_against_frozen_draft(
    sample_graph, sample_shape_path, draft, tmp_path
):
    """The point of freezing the draft: a new route must fail validation."""
    graph = nx.read_graphml(sample_graph)
    graph.add_edge("emergency_fund", "taxable_brokerage", rel="HAS_CHILD")
    mutated = tmp_path / "mutated.graphml"
    nx.write_graphml(graph, mutated)

    result = run("validate.py", str(mutated), str(sample_shape_path), str(draft))
    assert result.returncode == 1
    assert "unapproved client journey" in result.stdout


def test_refuses_to_overwrite(sample_graph, sample_shape_path, draft):
    result = run("bootstrap.py", str(sample_graph), str(sample_shape_path), "-o", str(draft))
    assert result.returncode == 2
    assert "refusing to overwrite" in result.stderr


def test_aborts_on_cycle(sample_shape_path, tmp_path):
    graph = nx.DiGraph()
    graph.add_node("a", labels="Task", rationale="r", source_doc="s")
    graph.add_node("b", labels="Task", rationale="r", source_doc="s")
    graph.add_edge("a", "b", rel="CRITERIA_BRANCH")
    graph.add_edge("b", "a", rel="CRITERIA_BRANCH")
    cyclic = tmp_path / "cyclic.graphml"
    nx.write_graphml(graph, cyclic)

    result = run(
        "bootstrap.py", str(cyclic), str(sample_shape_path), "-o", str(tmp_path / "out.yaml")
    )
    assert result.returncode == 2
    assert "cannot bootstrap" in result.stderr
    assert not (tmp_path / "out.yaml").exists()


def test_exits_nonzero_when_the_graph_has_structural_problems(
    sample_shape_path, tmp_path
):
    """A CI wrapper reading only the exit status must not see 'draft written'
    as 'graph is clean' (ISSUES.md #7). The draft is still written, so you
    can see what it would have approved."""
    graph = nx.DiGraph()
    graph.add_node("a", labels="Task", rationale="r", source_doc="s")
    graph.add_node("cn", labels="CriteriaNode")
    graph.add_node("b", labels="Task")  # missing rationale / source_doc
    graph.add_edge("a", "cn", rel="CRITERIA_BRANCH", condition_key="k", condition_value="v")
    graph.add_edge("cn", "b", rel="HAS_CHILD")
    path = tmp_path / "graph.graphml"
    nx.write_graphml(graph, path)

    out = tmp_path / "out.yaml"
    result = run("bootstrap.py", str(path), str(sample_shape_path), "-o", str(out))

    assert result.returncode == 1
    assert "structural problem" in result.stdout
    assert "step 'b' missing" in result.stdout
    assert out.exists(), "the draft is still written so you can inspect it"


def test_aborts_when_the_graph_does_not_match_the_shape(sample_shape_path, tmp_path):
    graph = nx.DiGraph()
    graph.add_node("a", labels="Widget", rationale="r", source_doc="s")
    graph.add_node("b", labels="Widget", rationale="r", source_doc="s")
    graph.add_edge("a", "b", rel="HAS_CHILD")
    path = tmp_path / "graph.graphml"
    nx.write_graphml(graph, path)

    result = run(
        "bootstrap.py", str(path), str(sample_shape_path), "-o", str(tmp_path / "o.yaml")
    )
    assert result.returncode == 2
    assert "does not match shape.yaml" in result.stderr
