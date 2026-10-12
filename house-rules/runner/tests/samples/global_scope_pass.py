"""Only definitions at the top level."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["main"]
LIMIT = 3
NAMES, _PRIVATE = ("a", "b"), 1
Handler: TypeAlias = "Callable[[], int]"
type Pair = tuple[int, int]


def main() -> int:
    """Entry."""
    return 0


if __name__ == "__main__":
    sys.exit(main())
