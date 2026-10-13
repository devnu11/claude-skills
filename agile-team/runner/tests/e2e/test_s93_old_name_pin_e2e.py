"""e2e: s93 AC3 grep pin: the old section name lives only in its alias constant and its test."""

from __future__ import annotations

from pathlib import Path

from agile_team.config import OLD_ENVIRONMENT_NAME

RUNNER = Path(__file__).resolve().parents[2]
SUFFIXES = {".py", ".md", ".toml", ".html", ".json", ".js", ".css", ".txt", ".yml", ".yaml", ".sh"}
SKIPPED = {".venv", "__pycache__", ".pytest_cache", "node_modules", "htmlcov"}
ALIAS_TEST = RUNNER / "tests" / "test_s93_environment_alias.py"
CONFIG = RUNNER / "agile_team" / "config.py"


def runner_files() -> list[Path]:
    """Text files under the runner, minus tool caches and environments."""
    return [
        p
        for p in sorted(RUNNER.rglob("*"))
        if p.is_file() and p.suffix in SUFFIXES and not SKIPPED & set(p.relative_to(RUNNER).parts)
    ]


def hits(path: Path) -> list[str]:
    """Lines of ``path`` that hold the old word, any case."""
    word = OLD_ENVIRONMENT_NAME.lower()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [line for line in lines if word in line.lower()]


def test_old_word_only_in_alias_line_and_its_test() -> None:
    """AC3: a search of the runner finds config.py's alias line and the s93 test, nothing else."""
    found = {p: hits(p) for p in runner_files() if p != ALIAS_TEST}
    found = {p: h for p, h in found.items() if h}
    assert list(found) == [CONFIG]
    assert len(found[CONFIG]) == 1
    assert found[CONFIG][0].startswith("OLD_ENVIRONMENT_NAME")
