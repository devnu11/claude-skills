"""Suppressions must give a reason."""


def show_table(rows, compact: bool):  # house-rules: allow boolean-parameter  # expect: suppression-reason fail
    """No reason given."""
    return rows, compact


def show_list(rows, verbose: bool):  # noqa: FBT001
    """A ruff alias without a reason."""
    return rows, verbose
