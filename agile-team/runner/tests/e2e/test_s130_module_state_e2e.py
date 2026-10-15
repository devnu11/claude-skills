"""s130 (AC2): no e2e test writes module-level mutable state (ADR-0067)."""

from __future__ import annotations

from ..clock_scan import Tree
from ..state_scan import py_sources, state_hits


def test_no_e2e_test_writes_module_state() -> None:
    """AC2: the scan of the e2e tree finds no write to module-level state."""
    hits = state_hits(py_sources(Tree.E2E))
    assert hits == [], "\n".join(hits)


def test_the_e2e_tree_is_scanned() -> None:
    """The scan covers e2e files only, and includes the e2e tests."""
    keys = list(py_sources(Tree.E2E))
    assert keys and all(k.startswith("e2e/") for k in keys)
    assert any(k.endswith("_e2e.py") and "/test_" in k for k in keys)
