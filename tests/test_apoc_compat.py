"""End-to-end check that the pipeline accepts a graphml file shaped like a
plain apoc.export.graphml.all export (useTypes: true, whole database) and
not just snapshot.py's own Bolt-driven export.

sample_graph_apoc.graphml encodes the identical graph as
tests/fixtures/sample_graph.graphml, just in APOC's dialect (colon labels,
`label` instead of `rel`, exporter-assigned node ids, plus one unrelated
node/edge to simulate a whole-database export). If normalize_graph() is
doing its job, this file should validate against the same hand-written
src/expectations.yaml as the native-format fixture.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).parent.parent / "src"
FIXTURES = Path(__file__).parent / "fixtures"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script, *args], cwd=SRC, capture_output=True, text=True
    )


@pytest.fixture
def apoc_graph(tmp_path) -> Path:
    dest = tmp_path / "graph.graphml"
    shutil.copy(FIXTURES / "sample_graph_apoc.graphml", dest)
    return dest


def test_validate_passes_apoc_export_against_hand_written_expectations(apoc_graph):
    result = run("validate.py", str(apoc_graph), str(SRC / "expectations.yaml"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED" in result.stdout


def test_bootstrap_draft_from_apoc_export_matches_hand_written_expectations(
    apoc_graph, tmp_path
):
    out = tmp_path / "draft.yaml"
    result = run("bootstrap.py", str(apoc_graph), str(out))
    assert result.returncode == 0, result.stdout + result.stderr

    got = yaml.safe_load(out.read_text())
    want = yaml.safe_load((SRC / "expectations.yaml").read_text())

    assert sorted(got["expected_entries"]) == sorted(want["expected_entries"])
    assert sorted(got["expected_terminals"]) == sorted(want["expected_terminals"])
    assert sorted(map(tuple, got["approved_paths"])) == sorted(
        map(tuple, want["approved_paths"])
    )
    for rule in want["rules"]:
        assert rule in got["rules"], f"hand-written rule not mined: {rule}"


def test_diff_baseline_sees_no_change_between_apoc_export_and_baseline(apoc_graph):
    result = run("diff_baseline.py", str(apoc_graph), str(SRC / "expectations.yaml"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No structural changes from baseline." in result.stdout


def test_unscoped_apoc_export_surfaces_as_a_failure_not_a_silent_filter(tmp_path):
    """apoc.export.graphml.all dumps the whole database; this pipeline does
    not guess which extra nodes/relationships don't belong to the flow (there
    is no reliable, schema-agnostic way to know acct1 isn't part of it). The
    unrelated node should show up as a real failure, not vanish silently."""
    dest = tmp_path / "graph.graphml"
    shutil.copy(FIXTURES / "sample_graph_apoc_wholedb.graphml", dest)

    result = run("validate.py", str(dest), str(SRC / "expectations.yaml"))
    assert result.returncode == 1
    assert "unexpected dead ends" in result.stdout
    assert "acct1" in result.stdout
