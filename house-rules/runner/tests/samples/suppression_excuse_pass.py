"""Suppressions that give a real reason, or none."""


def show_table(rows, compact: bool):  # house-rules: allow boolean-parameter -- matches the CLI flag
    """A real reason."""
    return rows, compact


def fetch_all(
    rows,
):  # house-rules: allow verb-name -- name fixed by the tests; it mirrors git's verb
    """An excuse followed by more text is a reason."""
    return rows


def show_list(rows, verbose: bool):  # house-rules: allow boolean-parameter
    """No reason: that is suppression-reason's finding, not an excuse."""
    return rows, verbose
