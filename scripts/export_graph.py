#!/usr/bin/env python3
"""Compatibility wrapper for the kg-export-graph console script."""

from kg_viewer.export_graph import main


if __name__ == "__main__":
    raise SystemExit(main())
