"""End-to-end check that the pipeline accepts a graphml file shaped like a
plain apoc.export.graphml.* export, not just a hand-authored fixture.

sample_graph_apoc.graphml encodes the identical graph as
tests/fixtures/sample_graph.graphml, just in APOC's dialect: colon-prefixed
labels, `label` instead of `rel`, exporter-assigned node ids with the
business id carried as an ordinary property. If normalize_graph() is doing
its job, it validates against the same reviewed shape.yaml and the same
committed baseline as the native-format fixture.
"""

import subprocess
import sys
from pathlib import Path

import yaml

SRC = Path(__file__).parent.parent / "src"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script, *args], cwd=SRC, capture_output=True, text=True, check=False
    )


def test_validate_passes_apoc_export_against_the_committed_baseline(
    apoc_graph, sample_shape_path, sample_expectations_path
):
    result = run(
        "validate.py", str(apoc_graph), str(sample_shape_path), str(sample_expectations_path)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED" in result.stdout


def test_apoc_colon_labels_resolve_against_the_same_shape(apoc_graph, sample_shape_path):
    """APOC writes labels as ':Task' / 'Task:Reviewed'. The shape declares
    plain 'Task' and must still match both."""
    result = run("validate.py", str(apoc_graph), str(sample_shape_path), "/dev/null")
    # /dev/null yields an empty baseline, so this fails on missing keys — the
    # point is only that it gets past the shape layer without label errors.
    assert "match no declared label" not in result.stdout + result.stderr


def test_bootstrap_draft_from_apoc_export_matches_the_committed_baseline(
    apoc_graph, sample_shape_path, sample_expectations_path, tmp_path
):
    out = tmp_path / "draft.yaml"
    result = run(
        "bootstrap.py", str(apoc_graph), str(sample_shape_path), "-o", str(out)
    )
    assert result.returncode == 0, result.stdout + result.stderr

    got = yaml.safe_load(out.read_text())
    want = yaml.safe_load(sample_expectations_path.read_text())

    assert sorted(got["expected_entries"]) == sorted(want["expected_entries"])
    assert sorted(got["expected_terminals"]) == sorted(want["expected_terminals"])
    assert sorted(map(tuple, got["approved_paths"])) == sorted(
        map(tuple, want["approved_paths"])
    )
    for rule in want["rules"]:
        assert rule in got["rules"], f"committed rule not mined: {rule}"


def test_diff_baseline_sees_no_change_between_apoc_export_and_baseline(
    apoc_graph, sample_shape_path, sample_expectations_path
):
    result = run(
        "diff_baseline.py",
        str(apoc_graph),
        str(sample_shape_path),
        str(sample_expectations_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No structural changes from baseline." in result.stdout


def test_unscoped_apoc_export_surfaces_as_a_failure_not_a_silent_filter(
    apoc_wholedb_graph, sample_shape_path, sample_expectations_path
):
    """apoc.export.graphml.all dumps the whole database. This pipeline does
    not guess which extra nodes don't belong to the flow — there is no
    reliable, schema-agnostic way to know acct1 isn't part of it. The
    unrelated node must surface as a real failure, not vanish silently.

    Under a declared shape it now fails at the shape layer, immediately and
    by name, rather than several layers later as a mysterious dead end."""
    result = run(
        "validate.py",
        str(apoc_wholedb_graph),
        str(sample_shape_path),
        str(sample_expectations_path),
    )
    assert result.returncode == 1
    assert "match no declared label" in result.stdout
    assert "acct1" in result.stdout
    assert "Account" in result.stdout
