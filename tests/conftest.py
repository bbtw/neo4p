"""Shared fixtures.

Tests run against real graphml files checked in at tests/fixtures/, never a
graph fabricated in Python — except where a test is deliberately constructing
a pathological shape to prove a specific failure is caught (see
test_shape.py's regression cases).

graphs/sample/ is the worked example: a graphml, its reviewed shape.yaml, and
a hand-checked expectations.yaml. If you regenerate the fixture, regenerate
that baseline too.
"""

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_KG = ROOT / "graphs" / "sample"


@pytest.fixture(scope="session")
def sample_shape_path() -> Path:
    """The reviewed shape.yaml for the sample graph."""
    return SAMPLE_KG / "shape.yaml"


@pytest.fixture(scope="session")
def sample_expectations_path() -> Path:
    """The committed baseline for the sample graph."""
    return SAMPLE_KG / "expectations.yaml"


@pytest.fixture
def sample_graph(tmp_path) -> Path:
    """The sample graphml, copied somewhere writable so scripts can drop
    paths.json / validation.json next to it without touching the repo."""
    path = tmp_path / "graph.graphml"
    shutil.copy(FIXTURES / "sample_graph.graphml", path)
    return path


@pytest.fixture
def apoc_graph(tmp_path) -> Path:
    path = tmp_path / "graph.graphml"
    shutil.copy(FIXTURES / "sample_graph_apoc.graphml", path)
    return path


@pytest.fixture
def apoc_wholedb_graph(tmp_path) -> Path:
    path = tmp_path / "graph.graphml"
    shutil.copy(FIXTURES / "sample_graph_apoc_wholedb.graphml", path)
    return path
