"""Per-test time limits (s72): 1 s for unit tests, the e2e limit for the real world.

Both numbers live in ``[tool.pytest.ini_options]``; this module only picks one per test.
"""

from __future__ import annotations

from typing import Any

import pytest

from . import os_guard

E2E_LIMIT_INI = "e2e_timeout"

# Which ini key holds each world's limit (L3). "timeout" is pytest-timeout's own key.
LIMIT_INI: dict[os_guard.World, str] = {
    os_guard.World.FAKE: "timeout",
    os_guard.World.REAL: E2E_LIMIT_INI,
}


def limit_of(item: Any) -> float:
    """The time limit in seconds for ``item``'s world, read from the ini."""
    return float(item.config.getini(LIMIT_INI[os_guard.world_of(item)]))


def mark(items: list[pytest.Item]) -> None:
    """Give every item a ``timeout`` marker with its world's limit (L4)."""
    for item in items:
        item.add_marker(pytest.mark.timeout(limit_of(item)))
