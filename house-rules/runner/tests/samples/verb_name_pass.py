"""Verb-named functions and noun-named properties."""


def compute_area(shape):
    """A verb."""
    return shape.width * shape.height


def returns_value(nodes):
    """Third person of a listed verb."""
    return bool(nodes)


def normalise_shape(shape):
    """A British spelling of a listed verb."""
    return shape


def to_dict(shape):
    """A conversion prefix."""
    return {"width": shape.width}


def main():
    """The entry point."""


def do_GET():
    """Allowed by name in the test settings."""


class Shape:
    """A shape."""

    @property
    def area(self):
        """A noun."""
        return 1

    @property
    def is_empty(self):
        """A question is fine for a property."""
        return False

    def __repr__(self):
        return "Shape()"
