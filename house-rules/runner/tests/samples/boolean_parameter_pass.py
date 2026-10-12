"""No boolean parameters."""

from enum import Enum


class Density(Enum):
    """How much to show."""

    COMPACT = "compact"
    FULL = "full"


def show_table(rows, density: Density = Density.FULL):
    """An enum instead of a flag."""
    return rows, density


class Toggle:
    """A property setter may take a bool."""

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value: bool):
        self._state = value
