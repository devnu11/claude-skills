"""Queries that should be properties."""


class Shape:
    """A shape."""

    def __init__(self, width):
        self.width = width

    def get_area(self):  # expect: query-property fail
        """Only reads self and returns a value."""
        return self.width * self.width
