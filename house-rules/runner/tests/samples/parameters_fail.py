"""Too many parameters."""


def add_three(first, second, third):  # expect: parameters warn
    """Three parameters warn."""
    return first + second + third


def add_four(first, second, third, fourth):  # expect: parameters fail
    """Four fail."""
    return first + second + third + fourth


def add_many(*values, **options):
    """Two: *args and **kwargs count one each."""
    return values, options


def create_shape(width, height, depth, color):  # expect: parameters fail
    """Not a factory: factories are static or class methods on their class."""
    return Shape(width, height, depth, color)


class Shape:
    """A shape."""

    def __init__(self, width, height, depth, color):
        self.size = (width, height, depth)
        self.color = color

    def create(self, width, height, depth, color):  # expect: parameters fail
        """An instance method is not a factory."""
        return Shape(width, height, depth, color)
