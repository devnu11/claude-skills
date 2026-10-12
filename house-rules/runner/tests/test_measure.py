"""Statement counting."""

import ast

from house_rules.measure import count_statements, is_case_chain, is_data, is_guard, strip_docstring


def parse_body(text: str) -> list[ast.stmt]:
    return ast.parse(text).body


def test_nested_blocks_count() -> None:
    assert (
        count_statements(
            parse_body("for a in b:\n    if a:\n        c()\n    else:\n        d()\n")
        )
        == 4
    )


def test_try_counts_body_and_else_not_handlers() -> None:
    text = "try:\n    a()\nexcept E:\n    b()\n    c()\nelse:\n    d()\nfinally:\n    e()\n"
    assert count_statements(parse_body(text)) == 2


def test_uncounted_statements() -> None:
    text = "def f():\n    x()\nclass C:\n    pass\nraise E\npass\nX = {'a': [1, 2]}\n"
    assert count_statements(parse_body(text)) == 0


def test_match_cases_count() -> None:
    assert (
        count_statements(
            parse_body("match x:\n    case 1:\n        a()\n    case _:\n        b()\n")
        )
        == 3
    )


def test_guard_needs_no_else_and_only_raise_or_return() -> None:
    guard, with_else, with_call = parse_body(
        "if a:\n    return\nif a:\n    return\nelse:\n    b()\nif a:\n    b()\n    return\n"
    )
    assert is_guard(guard) and not is_guard(with_else) and not is_guard(with_call)


def test_data_needs_a_pure_literal() -> None:
    literal, computed, bare = parse_body("X: int = 1\nY = [f()]\nZ: int\n")
    assert is_data(literal) and not is_data(computed) and not is_data(bare)


def test_strip_docstring_only_strips_a_string() -> None:
    body = parse_body("'doc'\nx = 1\n")
    assert len(strip_docstring(body)) == 1
    assert len(strip_docstring(parse_body("1\n"))) == 1


def test_case_chain_needs_one_branching_statement() -> None:
    assert is_case_chain(parse_body("'doc'\nif a:\n    b()\nelse:\n    c()\n"))
    assert not is_case_chain(parse_body("if a:\n    b()\n"))
    assert not is_case_chain(parse_body("a()\nb()\n"))
