"""Short functions and case chains."""


def describe_code(code):
    """A long if/elif chain is all this function does."""
    if code == 1:
        return "one"
    elif code == 2:
        return "two"
    elif code == 3:
        return "three"
    elif code == 4:
        return "four"
    elif code == 5:
        return "five"
    elif code == 6:
        return "six"
    elif code == 7:
        return "seven"
    elif code == 8:
        return "eight"
    elif code == 9:
        return "nine"
    else:
        return "many"


def describe_shape(shape):
    """A long match is all this function does."""
    match shape:
        case "a":
            first = 1
            second = 2
            third = 3
            fourth = 4
            fifth = 5
            sixth = 6
            seventh = 7
            eighth = 8
            ninth = 9
            return first + second + third + fourth + fifth + sixth + seventh + eighth + ninth
        case _:
            return 0


def count_eight(values):
    """Exactly eight."""
    total = 0
    for value in values:
        total += value
    total *= 2
    total -= 1
    first = values[0]
    last = values[-1]
    return total + first + last
