"""Import a module on first use, so a test of a module not built yet fails alone (s159)."""

from __future__ import annotations

import importlib
from typing import Any


class Late:
    """Attribute access imports ``agile_team.<name>`` then reads the attribute from it."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, attr: str) -> Any:
        return getattr(importlib.import_module(f"agile_team.{self.name}"), attr)
