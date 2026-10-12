"""Suppressions with reasons."""


def show_table(rows, compact: bool):  # house-rules: allow boolean-parameter -- matches the CLI flag
    """A reason given."""
    return rows, compact


def show_list(rows, verbose: bool):  # noqa: FBT001 -- framework callback signature
    """A ruff alias with a reason."""
    return rows, verbose


handler = object()  # house-rules: allow global-scope -- registry needs an instance
