"""e2e: O2 of the OS seam: nobody imports a name out of ``agile_team.system`` (s71)."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "agile_team"


def sources() -> list[Path]:
    """Every module of the package except the seam itself."""
    return [p for p in sorted(PACKAGE.rglob("*.py")) if p != PACKAGE / "system.py"]


def banned_imports(tree: ast.AST) -> list[int]:
    """Line numbers of ``from agile_team.system import x`` / ``from .system import x``."""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        absolute = node.level == 0 and node.module == "agile_team.system"
        relative = node.level == 1 and node.module == "system"
        if absolute or relative:
            hits.append(node.lineno)
    return hits


def test_package_is_found():
    assert len(sources()) > 20


def test_no_module_imports_a_name_from_system():
    found = {
        f"{p.relative_to(PACKAGE)}:{n}": None
        for p in sources()
        for n in banned_imports(ast.parse(p.read_text()))
    }
    assert not found, f"import the module, not a name: {sorted(found)}"


def test_the_check_catches_a_banned_import():
    for code in ("from agile_team.system import now", "from .system import now"):
        assert banned_imports(ast.parse(code)) == [1]
    for code in ("from agile_team import system", "from . import system"):
        assert banned_imports(ast.parse(code)) == []
