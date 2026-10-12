"""Boolean parameters."""


def show_table(rows, compact: bool):  # expect: boolean-parameter fail
    """Typed bool."""
    return rows, compact


def show_list(rows, *, verbose=False):  # expect: boolean-parameter fail
    """Keyword-only booleans count too."""
    return rows, verbose


def show_tree(rows, deep: bool | None = None):  # expect: boolean-parameter fail
    """A union with bool."""
    return rows, deep
