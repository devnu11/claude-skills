"""s142 end to end: a real repo's .claude/CLAUDE.md reaches the role system prompt as text."""

from __future__ import annotations

from pathlib import Path

from agile_team.roles import RoleBook


def prompt(repo: Path) -> str:
    book = RoleBook.for_repo(repo, {})
    return book.system_prompt(book.resolve("developer-cli"), "scope")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_section_order_imports_and_outside_note(tmp_path: Path) -> None:
    """AC1/AC4: section before the charter; inside import inlined once; outside left out."""
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    write(home / ".claude/CLAUDE.md", "HOME-RULE")
    write(repo / ".team/CLAUDE.md", "CHARTER")
    write(repo / "docs/a.md", "A-TEXT")
    write(
        repo / ".claude/CLAUDE.md",
        f"INSTR @../docs/a.md\n@../docs/a.md\n@~/.claude/CLAUDE.md\n@{home}/.claude/CLAUDE.md\n",
    )
    text = prompt(repo)
    assert text.index("## Repo instructions") < text.index("INSTR") < text.index("## Repo charter")
    assert text.index("CHARTER") < text.index("## Your file scope")
    assert text.count("A-TEXT") == 1
    assert "(left out: @../docs/a.md is already included above)" in text
    assert "(left out: @~/.claude/CLAUDE.md points outside the repo)" in text
    assert "HOME-RULE" not in text


def test_missing_file_adds_nothing(tmp_path: Path) -> None:
    """AC1: no .claude/CLAUDE.md, no section."""
    write(tmp_path / ".team/CLAUDE.md", "CHARTER")
    assert "Repo instructions" not in prompt(tmp_path)


def test_settings_file_is_not_loaded(tmp_path: Path) -> None:
    """AC2: settings.json content never reaches the prompt."""
    write(tmp_path / ".claude/CLAUDE.md", "INSTR")
    write(tmp_path / ".claude/settings.json", '{"hooks": "HOOK-MARK"}')
    assert "HOOK-MARK" not in prompt(tmp_path)
