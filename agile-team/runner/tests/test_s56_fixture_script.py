"""s56/AC1: the dashboard fixture script holds no code at its top level."""

import ast
from pathlib import Path

import pytest
from agile_team import system
from agile_team.roles import RoleBook

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_dashboard_fixture.py"
DEFINITIONS = (
    ast.Import,
    ast.ImportFrom,
    ast.Assign,
    ast.AnnAssign,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)


def is_docstring(node: ast.stmt) -> bool:
    """A bare string constant statement."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def is_main_guard(node: ast.stmt) -> bool:
    """`if __name__ == "__main__":` exactly."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def allowed(index: int, node: ast.stmt) -> bool:
    """Whether the rule lets this statement sit at the top level."""
    if isinstance(node, DEFINITIONS) or is_main_guard(node):
        return True
    return index == 0 and is_docstring(node)


def stray_statements(tree: ast.Module) -> list[str]:
    """`<line>: <node type>` for each top-level statement the rule forbids."""
    return [
        f"{node.lineno}: {type(node).__name__}"
        for index, node in enumerate(tree.body)
        if not allowed(index, node)
    ]


def script_tree() -> ast.Module:
    """The fixture script's tree, read through the system seam; empty source fails."""
    tree = ast.parse(system.read_text(SCRIPT))
    assert tree.body
    return tree


def test_fixture_script_has_no_top_level_code() -> None:
    assert stray_statements(script_tree()) == []


def test_fixture_script_guard_calls_main() -> None:
    last = script_tree().body[-1]
    assert is_main_guard(last)
    assert len(last.body) == 1
    assert "main(" in ast.unparse(last.body[0])


def test_stray_statements_flags_top_level_code() -> None:
    source = '"""doc"""\nfor x in y: pass\nprint(1)\nwith f: pass\nif x: pass\n'
    found = stray_statements(ast.parse(source))
    assert len(found) == 4
    assert [entry.split(":")[0] for entry in found] == ["2", "3", "4", "5"]


def test_stray_statements_accepts_a_clean_module() -> None:
    source = (
        '"""doc"""\nimport os\nA = 1\nB: int = 2\n'
        "def f(): ...\nclass C: ...\n"
        'if __name__ == "__main__":\n    f()\n'
    )
    assert stray_statements(ast.parse(source)) == []


def test_docstring_only_allowed_first() -> None:
    found = stray_statements(ast.parse('x = 1\n"text"\n'))
    assert len(found) == 1
    assert found[0].startswith("2:")


def test_other_main_guards_are_not_the_guard() -> None:
    assert stray_statements(ast.parse('if __name__ != "__main__":\n    pass\n'))


@pytest.mark.parametrize(
    "text", ["## Checklist", "top level", 'if __name__ == "__main__":', "just_do_it"]
)
def test_code_reviewer_checklist_names_the_rule(text: str) -> None:
    body = RoleBook.for_repo(Path("/none"), {}).resolve("code-reviewer").body
    assert text in body, f"code-reviewer role lacks {text!r}"
