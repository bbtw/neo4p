"""diff_baseline.py: the sign-off report for graph changes against the baseline."""

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
def baseline(sample_graph, sample_shape_path, tmp_path) -> Path:
    out = tmp_path / "baseline.yaml"
    result = run("bootstrap.py", str(sample_graph), str(sample_shape_path), "-o", str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    return out


@pytest.fixture
def mutated(sample_graph, tmp_path) -> Path:
    """Sample graph with one route added and the estate_review branch retired."""
    graph = nx.read_graphml(sample_graph)
    graph.add_edge("emergency_fund", "taxable_brokerage", rel="HAS_CHILD")
    graph.remove_node("roth_ira__estate")
    graph.remove_node("estate_review")
    out = tmp_path / "mutated" / "graph.graphml"
    out.parent.mkdir()
    nx.write_graphml(graph, out)
    return out


def test_unchanged_graph_exits_zero(baseline, sample_graph, sample_shape_path):
    result = run("diff_baseline.py", str(sample_graph), str(sample_shape_path), str(baseline))
    assert result.returncode == 0
    assert "No structural changes from baseline" in result.stdout


def test_report_shows_exact_delta(baseline, mutated, sample_shape_path):
    result = run("diff_baseline.py", str(mutated), str(sample_shape_path), str(baseline))
    assert result.returncode == 1
    assert "1 added, 2 removed" in result.stdout
    assert "emergency_fund -> taxable_brokerage" in result.stdout
    assert "terminal removed: estate_review" in result.stdout
    assert (mutated.parent / "change_report.md").exists()


def test_update_writes_a_draft_and_carries_rules_and_scenarios(
    baseline, mutated, sample_shape_path
):
    result = run(
        "diff_baseline.py", str(mutated), str(sample_shape_path), str(baseline), "--update"
    )
    assert result.returncode == 1

    draft = mutated.parent / "expectations.yaml.new"
    updated = yaml.safe_load(draft.read_text())
    base = yaml.safe_load(baseline.read_text())
    assert updated["rules"] == base["rules"]
    assert updated["scenarios"] == base["scenarios"]
    assert ["emergency_fund", "taxable_brokerage"] in updated["approved_paths"]
    assert "estate_review" not in updated["expected_terminals"]

    # the promoted file must validate cleanly against the new graph
    check = run("validate.py", str(mutated), str(sample_shape_path), str(draft))
    assert check.returncode == 0, check.stdout


def test_update_never_overwrites_the_baseline_it_diffed_against(
    baseline, mutated, sample_shape_path
):
    """--update used to write expectations.yaml unconditionally, clobbering
    the committed baseline before anyone read the report (ISSUES.md #4)."""
    before = baseline.read_text()
    sibling = mutated.parent / "expectations.yaml"
    sibling.write_text(before)

    run("diff_baseline.py", str(mutated), str(sample_shape_path), str(sibling), "--update")

    assert sibling.read_text() == before, "the baseline must be left untouched"
    assert (mutated.parent / "expectations.yaml.new").exists()


def test_baseline_rule_violation_is_reported(
    baseline, sample_graph, sample_shape_path, tmp_path
):
    """A change that contradicts a mined baseline rule shows up as a violation."""
    graph = nx.read_graphml(sample_graph)
    # roth_ira always precedes taxable_brokerage in the baseline; invert the
    # ordering (drop roth's invest branch, then route taxable into roth)
    graph.remove_node("roth_ira__invest")
    graph.add_edge("taxable_brokerage", "roth_ira", rel="HAS_CHILD")
    out = tmp_path / "graph.graphml"
    nx.write_graphml(graph, out)

    result = run("diff_baseline.py", str(out), str(sample_shape_path), str(baseline))
    assert result.returncode == 1
    assert "VIOLATION" in result.stdout


def test_cannot_diff_exits_2_not_1(baseline, sample_shape_path, tmp_path):
    """'the diff could not run' must be distinguishable from 'the diff ran and
    found changes' by exit code alone (ISSUES.md #3)."""
    graph = nx.DiGraph()
    graph.add_node("a", labels="Task", rationale="r", source_doc="s")
    graph.add_node("b", labels="Task", rationale="r", source_doc="s")
    graph.add_edge("a", "b", rel="CRITERIA_BRANCH")
    graph.add_edge("b", "a", rel="CRITERIA_BRANCH")
    cyclic = tmp_path / "cyclic.graphml"
    nx.write_graphml(graph, cyclic)

    result = run("diff_baseline.py", str(cyclic), str(sample_shape_path), str(baseline))
    assert result.returncode == 2
    assert "cannot diff" in result.stderr
