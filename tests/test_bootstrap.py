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
        [sys.executable, script, *args], cwd=SRC, capture_output=True, text=True
    )


@pytest.fixture(scope="module")
def sample_graph(tmp_path_factory) -> Path:
    assert run("make_sample_graph.py").returncode == 0
    return SRC / "snapshots" / "sample" / "graph.graphml"


@pytest.fixture(scope="module")
def draft(sample_graph, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bootstrap") / "draft.yaml"
    result = run("bootstrap.py", str(sample_graph), str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_draft_matches_hand_written_expectations(draft):
    """The sample expectations.yaml was authored by hand; the draft must
    independently arrive at the same entries, terminals, paths, and rules."""
    got = yaml.safe_load(draft.read_text())
    want = yaml.safe_load((SRC / "expectations.yaml").read_text())

    assert sorted(got["expected_entries"]) == sorted(want["expected_entries"])
    assert sorted(got["expected_terminals"]) == sorted(want["expected_terminals"])
    assert sorted(map(tuple, got["approved_paths"])) == sorted(
        map(tuple, want["approved_paths"])
    )
    for rule in want["rules"]:
        assert rule in got["rules"], f"hand-written rule not mined: {rule}"


def test_validate_passes_against_own_draft(sample_graph, draft):
    """By construction: a graph always validates against its own baseline."""
    result = run("validate.py", str(sample_graph), str(draft))
    assert result.returncode == 0, result.stdout


def test_mutated_graph_fails_against_frozen_draft(sample_graph, draft, tmp_path):
    """The point of freezing the draft: a new route must fail validation."""
    graph = nx.read_graphml(sample_graph)
    graph.add_edge("emergency_fund", "taxable_brokerage", rel="HAS_CHILD")
    mutated = tmp_path / "mutated.graphml"
    nx.write_graphml(graph, mutated)

    result = run("validate.py", str(mutated), str(draft))
    assert result.returncode == 1
    assert "unapproved client journey" in result.stdout


def test_refuses_to_overwrite(sample_graph, draft):
    result = run("bootstrap.py", str(sample_graph), str(draft))
    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr


def test_aborts_on_cycle(tmp_path):
    graph = nx.DiGraph()
    graph.add_node("a", labels="Task", rationale="r", source_doc="s")
    graph.add_node("b", labels="Task", rationale="r", source_doc="s")
    graph.add_edge("a", "b", rel="HAS_CHILD")
    graph.add_edge("b", "a", rel="HAS_CHILD")
    cyclic = tmp_path / "cyclic.graphml"
    nx.write_graphml(graph, cyclic)

    result = run("bootstrap.py", str(cyclic), str(tmp_path / "out.yaml"))
    assert result.returncode == 1
    assert "cannot bootstrap" in result.stderr
    assert not (tmp_path / "out.yaml").exists()
