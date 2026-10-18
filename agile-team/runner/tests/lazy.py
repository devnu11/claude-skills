"""Import a module on first attribute use, so a module that does not exist yet fails per test."""

from __future__ import annotations

import importlib
from typing import Any


class Lazy:
    """A stand-in for ``import name``; the import happens when an attribute is read."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str) -> Any:
        return getattr(importlib.import_module(self._name), attr)
