"""Shared fixtures.

Tests run against a real graphml, never a graph fabricated in Python: either
one exported live from Neo4j via snapshot.py, or the static file checked in
at tests/fixtures/sample_graph.graphml. src/expectations.yaml is hand-written
to match that fixture exactly, so if you regenerate the fixture, update
src/expectations.yaml to match.
"""

import shutil
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_graph() -> Path:
    """Copy the checked-in sample graphml into the layout validate.py,
    bootstrap.py, and diff_baseline.py expect, and return its path."""
    outdir = SRC / "snapshots" / "sample"
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "graph.graphml"
    shutil.copy(FIXTURES / "sample_graph.graphml", path)
    return path
