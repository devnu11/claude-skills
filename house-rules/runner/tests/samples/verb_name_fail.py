"""Names that are not verbs."""


def boundary_data(runtime):  # expect: verb-name fail
    """A noun."""
    return runtime


def area(shape):  # expect: verb-name fail
    """A noun: belongs on the shape as a property."""
    return shape.width * shape.height


class Shape:
    """A shape."""

    @property
    def get_area(self):  # expect: verb-name fail
        """A property named with a verb."""
        return 1
