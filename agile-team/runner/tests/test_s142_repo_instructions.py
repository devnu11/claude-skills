"""s142: every role's system prompt carries the repo's own `.claude/CLAUDE.md` as text."""

from pathlib import Path

import pytest
from agile_team import instructions, system
from agile_team.roles import RoleBook

from .conftest import FakeQuery
from .fake_system import FAKE_HOME
from .test_dispatch import run
from .test_roles import BUILTIN

HEADING = "## Repo instructions"
REPEAT = "(left out: @../docs/a.md is already included above)"


def write(repo: Path, name: str, text: str) -> None:
    system.make_dirs((repo / name).parent)
    system.write_text(repo / name, text)


def prompt_for(repo: Path) -> str:
    book = RoleBook(dict(BUILTIN), {}, {}, repo)
    return book.system_prompt(book.resolve("child"), "SCOPE")


def inlined(repo: Path, text: str) -> str:
    write(repo, ".claude/CLAUDE.md", text)
    return instructions.repo_instructions(repo)


def test_order(repo: Path) -> None:
    write(repo, ".claude/CLAUDE.md", "INSTR")
    write(repo, ".team/CLAUDE.md", "CHARTER")
    prompt = prompt_for(repo)
    marks = ["SHARED", "CHILD", HEADING, "INSTR", "## Repo charter", "CHARTER", "## Your file"]
    order = [prompt.index(m) for m in marks]
    assert order == sorted(order)


def test_missing_file_adds_nothing(repo: Path) -> None:
    assert instructions.repo_instructions(repo) == ""
    assert "Repo instructions" not in prompt_for(repo)


def test_whitespace_file_adds_nothing(repo: Path) -> None:
    write(repo, ".claude/CLAUDE.md", "  \n\n")
    assert "Repo instructions" not in prompt_for(repo)


def test_inside_import_inlined_once(repo: Path) -> None:
    write(repo, "docs/a.md", "A-TEXT")
    write(repo, ".claude/CLAUDE.md", "see @../docs/a.md\n@../docs/a.md\n")
    prompt = prompt_for(repo)
    assert prompt.count("A-TEXT") == 1
    assert REPEAT in prompt


def test_imports_resolve_relative_to_the_importing_file(repo: Path) -> None:
    write(repo, ".claude/rules.md", "RULES-TEXT")
    write(repo, "docs/a.md", "A-TEXT @b.md")
    write(repo, "docs/b.md", "B-TEXT")
    out = inlined(repo, "@rules.md\n@../docs/a.md\n")
    assert "RULES-TEXT" in out and "A-TEXT" in out and "B-TEXT" in out


def test_cycle_ends_with_the_repeat_note(repo: Path) -> None:
    write(repo, "docs/a.md", "@../.claude/CLAUDE.md")
    out = inlined(repo, "@../docs/a.md")
    assert "(left out: @../.claude/CLAUDE.md is already included above)" in out


@pytest.mark.parametrize(
    "path", ["~/.claude/CLAUDE.md", "../../outside.md", str(FAKE_HOME / "secret.md")]
)
def test_outside_import_left_out_with_note(repo: Path, path: str) -> None:
    write(repo, "../outside.md", "OUT-TEXT")
    system.make_dirs(FAKE_HOME)
    system.write_text(FAKE_HOME / "secret.md", "OUT-TEXT")
    out = inlined(repo, f"x @{path} y")
    assert out == f"x (left out: @{path} points outside the repo) y"


@pytest.mark.parametrize(
    "text", ["ping @someone", "see @../docs/a.md.", "mail a@b.com", "@../docs"]
)
def test_not_a_file_stays_verbatim(repo: Path, text: str) -> None:
    write(repo, "docs/a.md", "A-TEXT")
    assert inlined(repo, text) == text


@pytest.mark.parametrize("text", ["use ` @../docs/a.md` here", "```\n@../docs/a.md\n```"])
def test_code_is_not_imported(repo: Path, text: str) -> None:
    write(repo, "docs/a.md", "A-TEXT")
    out = inlined(repo, text)
    assert "A-TEXT" not in out
    assert out == text


def test_home_instructions_are_never_read(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(FAKE_HOME, ".claude/CLAUDE.md", "HOME-RULE")

    def boom(*args: object) -> None:
        raise AssertionError("home touched")

    monkeypatch.setattr(system, "home", boom)
    monkeypatch.setattr(system, "expand_user", boom)
    write(repo, ".claude/CLAUDE.md", "plain")
    assert "HOME-RULE" not in prompt_for(repo)
    write(repo, ".claude/CLAUDE.md", "@~/.claude/CLAUDE.md")
    assert "HOME-RULE" not in prompt_for(repo)


def test_no_settings_are_loaded(make_runtime, repo: Path) -> None:
    write(repo, ".claude/settings.json", '{"hooks": {"Stop": [{"command": "HOOK-CMD"}]}}')
    write(repo, ".claude/CLAUDE.md", "INSTR")
    q = FakeQuery()
    rt = make_runtime(q)
    run(rt, "architect")
    opts = q.calls[0]["options"]
    assert opts.setting_sources == []
    assert "INSTR" in opts.system_prompt and "HOOK-CMD" not in opts.system_prompt
