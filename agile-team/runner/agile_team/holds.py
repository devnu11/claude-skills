"""The PO's hold on a story (s53): what it is for and why; pure data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HoldKind(StrEnum):
    """What a PO hold is for; the value is the board text."""

    HOLD = "PO hold"
    CANCEL = "cancel requested"


@dataclass
class PoHold:
    """The PO's hold on a story: kind, reason and, for a cancel request, its question id."""

    kind: HoldKind
    reason: str
    question: str | None = None

    def __post_init__(self) -> None:
        self.kind = HoldKind(self.kind)

    @property
    def shown(self) -> str:
        """The kind and reason, for the board."""
        return f"{self.kind}: {self.reason}"
