"""Counting a function's statements, and recognising case chains, guards and data."""

from __future__ import annotations

import ast

UNCOUNTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Raise, ast.Pass)
LITERALS = (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict)
BLOCK_FIELDS = ("body", "orelse")
TRY_TYPES = (ast.Try, ast.TryStar)


def count_statements(body: list[ast.stmt]) -> int:
    """Statements in ``body``, through nested blocks, leaving out what the rules don't count.

    Not counted: nested functions and classes, ``raise``, ``pass``, guard clauses,
    assignments of pure literals, and ``except`` and ``finally`` blocks.
    """
    return sum(measure_statement(statement) for statement in body)


def measure_statement(statement: ast.stmt) -> int:
    """How many statements ``statement`` counts for, its nested blocks included."""
    if isinstance(statement, UNCOUNTED) or is_guard(statement) or is_data(statement):
        return 0
    own = 0 if isinstance(statement, TRY_TYPES) else 1
    return own + sum(count_statements(block) for block in list_counted_blocks(statement))


def list_counted_blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    """The blocks that count: bodies and ``else`` blocks and ``match`` cases, not handlers."""
    blocks = [getattr(statement, name, []) for name in BLOCK_FIELDS]
    return blocks + [case.body for case in getattr(statement, "cases", [])]


def is_guard(statement: ast.stmt) -> bool:
    """An ``if`` with no ``else`` that only raises or returns: error handling."""
    if not isinstance(statement, ast.If) or statement.orelse:
        return False
    return all(isinstance(inner, ast.Raise | ast.Return) for inner in statement.body)


def is_data(statement: ast.stmt) -> bool:
    """An assignment of a pure literal: a data declaration."""
    if not isinstance(statement, ast.Assign | ast.AnnAssign):
        return False
    return statement.value is not None and is_literal(statement.value)


def is_literal(node: ast.expr) -> bool:
    """A constant, or a list, tuple, set or dict made only of literals."""
    if isinstance(node, ast.Constant):
        return True
    if not isinstance(node, LITERALS):
        return False
    children = [child for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)]
    return all(is_literal(child) for child in children)


def strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """``body`` without a leading docstring."""
    if body and is_docstring(body[0]):
        return body[1:]
    return body


def is_docstring(statement: ast.stmt) -> bool:
    """A bare string expression."""
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Constant):
        return False
    return isinstance(statement.value.value, str)


def is_case_chain(body: list[ast.stmt]) -> bool:
    """The whole body is one ``match`` or one ``if``/``elif``/``else`` chain."""
    statements = strip_docstring(body)
    if len(statements) != 1:
        return False
    only = statements[0]
    return isinstance(only, ast.Match) or (isinstance(only, ast.If) and bool(only.orelse))
