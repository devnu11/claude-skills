"""Exempt from the parameter limit."""

from abc import abstractmethod
from typing import override


class Shape:
    """A shape with factories."""

    def __init__(self, width, height, depth, color):
        self.size = (width, height, depth)
        self.color = color

    def __exit__(self, kind, error, trace):
        return None

    @staticmethod
    def create_shape(width, height, depth, color):
        """A factory by name: create_<class>."""
        return Shape(width, height, depth, color)

    @classmethod
    def from_dict(cls, data, width, height, depth):
        """An abstract factory that picks an implementation."""
        match data.get("kind"):
            case "box":
                return cls(width, height, depth, "box")
            case _:
                return cls(width, height, 0, data["color"])

    def scale(self, factor, origin):
        """Two parameters after self."""
        return factor, origin


class Base:
    """A base class."""

    @abstractmethod
    def place(self, x, y, z, layer):
        """Fixed elsewhere."""
        return x, y, z, layer


class Child(Base):
    """Overrides keep the base signature."""

    @override
    def place(self, x, y, z, layer):
        return x, y, z, layer
