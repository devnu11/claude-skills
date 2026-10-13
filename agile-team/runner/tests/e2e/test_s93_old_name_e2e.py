"""e2e: s93 AC3 grep pin (E13): the old section name stays in its alias and its test."""

from __future__ import annotations

from pathlib import Path

from agile_team.config import OLD_ENVIRONMENT_NAME

ROOT = Path(__file__).resolve().parents[3]
SUFFIXES = {".py", ".md", ".toml", ".html", ".json", ".js", ".css", ".txt", ".yml", ".yaml", ".sh"}
SKIPPED = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "htmlcov",
}
DESIGN = ROOT / "docs" / "design"
ALIAS_TEST = "runner/tests/test_s93_environment_alias.py"
CONFIG = "runner/agile_team/config.py"
ALIAS_LINE = "OLD_ENVIRONMENT_NAME ="


def walked() -> list[Path]:
    """Text files under agile-team/, minus tool caches and design records."""
    return [
        p
        for p in sorted(ROOT.rglob("*"))
        if p.is_file()
        and p.suffix in SUFFIXES
        and not SKIPPED & set(p.relative_to(ROOT).parts)
        and DESIGN not in p.parents
    ]


def allowed(rel: str, line: str) -> bool:
    """True for the alias assignment and any line of the alias test."""
    return rel == ALIAS_TEST or (rel == CONFIG and ALIAS_LINE in line)


def stray_hits() -> list[str]:
    """``path:line_no`` of every disallowed mention of the old word, any case."""
    word = OLD_ENVIRONMENT_NAME.lower()
    found = []
    for path in walked():
        rel = path.relative_to(ROOT).as_posix()
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        found += [
            f"{rel}:{n}"
            for n, line in enumerate(lines, 1)
            if word in line.lower() and not allowed(rel, line)
        ]
    return found


def test_old_word_only_in_alias_line_and_its_test() -> None:
    """AC3: a search of agile-team/ (minus docs/design) finds no stray mention."""
    assert stray_hits() == []


def test_walk_sees_the_docs_and_not_the_design_records() -> None:
    """The pin covers SKILL.md, the protocol and the customer page, and skips docs/design."""
    rels = {p.relative_to(ROOT).as_posix() for p in walked()}
    for doc in ("SKILL.md", "reference/protocol.md", "docs/customer/acceptance-presentations.md"):
        assert doc in rels
    assert not [r for r in rels if r.startswith("docs/design/")]
