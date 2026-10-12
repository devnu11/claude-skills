"""Methods that are not plain queries."""


class Shape:
    """A shape."""

    def __init__(self, width):
        self.width = width
        self.items = []

    def reset_width(self):
        """Assigns to self."""
        self.width = 0
        return self.width

    def pop_item(self):
        """Mutates through a method on an attribute."""
        return self.items.pop()

    def list_items(self):
        """A generator."""
        yield from self.items

    async def load_width(self):
        """Async methods cannot be properties."""
        return self.width

    def print_width(self):
        """Returns nothing."""
        print(self.width)

    def scale_width(self, factor):
        """Takes a parameter."""
        return self.width * factor

    @staticmethod
    def get_unit():
        """Static."""
        return "cm"
