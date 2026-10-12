"""Long functions."""


def run_nine(values):  # expect: function-length warn
    """Nine counted statements."""
    total = len(values)
    for value in values:
        total += value
    total *= 2
    total -= 1
    first = values[0]
    last = values[-1]
    middle = first + last
    return total + middle


def run_nine_with_handling(values):  # expect: function-length warn
    """The same nine, plus a docstring, a guard, data and an except body."""
    if not values:
        raise ValueError("empty")
    table = {"a": 1, "b": [2, 3]}
    try:
        total = len(values)
        for value in values:
            total += value
        total *= 2
        total -= 1
        first = values[0]
        last = values[-1]
        middle = first + last
    except IndexError:
        total = len(values)
        middle = 0
        first = table
    return total + middle


def run_thirteen(values):  # expect: function-length fail
    """Thirteen counted statements."""
    total = len(values)
    for value in values:
        total += value
    total *= 2
    total -= 1
    total += 3
    total += 4
    total += 5
    total += 6
    first = values[0]
    last = values[-1]
    middle = first + last
    return total + middle
