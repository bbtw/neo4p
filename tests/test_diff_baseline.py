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
        [sys.executable, script, *args], cwd=SRC, capture_output=True, text=True
    )


@pytest.fixture(scope="module")
def baseline(sample_graph, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("diff") / "baseline.yaml"
    assert run(
        "bootstrap.py", str(sample_graph), str(out)
    ).returncode == 0
    return out


@pytest.fixture()
def mutated(sample_graph, tmp_path) -> Path:
    """Sample graph with one route added and the estate_review branch retired."""
    graph = nx.read_graphml(sample_graph)
    graph.add_edge("emergency_fund", "taxable_brokerage", rel="HAS_CHILD")
    graph.remove_node("roth_ira__estate")
    graph.remove_node("estate_review")
    out = tmp_path / "graph.graphml"
    nx.write_graphml(graph, out)
    return out


def test_unchanged_graph_exits_zero(baseline, sample_graph):
    result = run(
        "diff_baseline.py", str(sample_graph), str(baseline)
    )
    assert result.returncode == 0
    assert "No structural changes from baseline" in result.stdout


def test_report_shows_exact_delta(baseline, mutated):
    result = run("diff_baseline.py", str(mutated), str(baseline))
    assert result.returncode == 1
    assert "1 added, 2 removed" in result.stdout
    assert "emergency_fund -> taxable_brokerage" in result.stdout
    assert "terminal removed: estate_review" in result.stdout
    assert (mutated.parent / "change_report.md").exists()


def test_update_carries_rules_and_scenarios(baseline, mutated):
    result = run("diff_baseline.py", str(mutated), str(baseline), "--update")
    assert result.returncode == 1

    updated = yaml.safe_load((mutated.parent / "expectations.yaml").read_text())
    base = yaml.safe_load(baseline.read_text())
    assert updated["rules"] == base["rules"]
    assert updated["scenarios"] == base["scenarios"]
    assert ["emergency_fund", "taxable_brokerage"] in updated["approved_paths"]
    assert "estate_review" not in updated["expected_terminals"]

    # the updated file must validate cleanly against the new graph
    check = run("validate.py", str(mutated), str(mutated.parent / "expectations.yaml"))
    assert check.returncode == 0, check.stdout


def test_baseline_rule_violation_is_reported(baseline, sample_graph, tmp_path):
    """A change that contradicts a mined baseline rule shows up as a violation."""
    graph = nx.read_graphml(sample_graph)
    # roth_ira always precedes taxable_brokerage in the baseline; invert the
    # ordering (drop roth's invest branch, then route taxable into roth)
    graph.remove_node("roth_ira__invest")
    graph.add_edge("taxable_brokerage", "roth_ira", rel="HAS_CHILD")
    out = tmp_path / "graph.graphml"
    nx.write_graphml(graph, out)

    result = run("diff_baseline.py", str(out), str(baseline))
    assert result.returncode == 1
    assert "VIOLATION" in result.stdout
