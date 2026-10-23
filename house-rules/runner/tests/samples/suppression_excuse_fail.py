"""Suppressions must not blame the tests or a design for a name."""


def go(rows):  # house-rules: allow verb-name -- tests use it  # expect: suppression-excuse fail
    """Pattern 3: tests use the name."""
    return rows


def sizes(rows):  # house-rules: allow verb-name -- s163 design name
    """Pattern 2: the design's name."""
    return rows


def mirror(rows):  # house-rules: allow verb-name -- the tests use this name.
    """Pattern 3, with a trailing dot."""
    return rows


def upper(rows):  # house-rules: allow verb-name -- NAME FIXED BY THE DESIGN
    """Upper case."""
    return rows
