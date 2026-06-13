#!/usr/bin/env python3
"""Compatibility wrapper for the kg-import-graph console script."""

from kg_viewer.import_graph import main


if __name__ == "__main__":
    raise SystemExit(main())
