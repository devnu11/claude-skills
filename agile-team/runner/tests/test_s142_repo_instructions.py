"""s142: every role's system prompt carries the repo's own `.claude/CLAUDE.md` as text."""

from pathlib import Path

import pytest
from agile_team import cli, instructions, system
from agile_team.roles import RoleBook

from .conftest import FakeQuery
from .fake_system import FAKE_HOME
from .test_dispatch import run
from .test_roles import BUILTIN

HEADING = "## Repo instructions"
BINARY = b"\x89PNG\r\n\x1a\n\xff\xfe"
LOGO_NOTE = "(left out: @../docs/logo.png is not UTF-8 text)"
PROTOCOL = Path(cli.__file__).parents[2] / "reference" / "protocol.md"
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


def write_logo(repo: Path) -> None:
    system.make_dirs(repo / "docs")
    system.write_bytes(repo / "docs/logo.png", BINARY)


def test_binary_import_left_out_with_note(repo: Path) -> None:
    write_logo(repo)
    assert inlined(repo, "a @../docs/logo.png b") == f"a {LOGO_NOTE} b"


def test_other_text_still_loads_beside_a_binary_import(repo: Path) -> None:
    write_logo(repo)
    write(repo, "docs/a.md", "A-TEXT")
    out = inlined(repo, "@../docs/logo.png\n@../docs/a.md\nTAIL")
    assert LOGO_NOTE in out and "A-TEXT" in out and "TAIL" in out


def test_binary_import_is_never_marked_seen(repo: Path) -> None:
    write_logo(repo)
    out = inlined(repo, "@../docs/logo.png\n@../docs/logo.png")
    assert out.count(LOGO_NOTE) == 2
    assert "already included above" not in out


def test_binary_import_inside_an_imported_file(repo: Path) -> None:
    write(repo, "docs/a.md", "A-TEXT @logo.png")
    system.write_bytes(repo / "docs/logo.png", BINARY)
    out = inlined(repo, "@../docs/a.md")
    assert "A-TEXT (left out: @logo.png is not UTF-8 text)" in out


def test_non_ascii_utf8_import_is_inlined_exactly(repo: Path) -> None:
    write(repo, "docs/a.md", "café ✓")
    assert inlined(repo, "@../docs/a.md") == "café ✓"


def test_step_prompt_is_built_with_a_binary_import(make_runtime, repo: Path) -> None:
    write_logo(repo)
    write(repo, ".claude/CLAUDE.md", "INSTR @../docs/logo.png")
    q = FakeQuery()
    run(make_runtime(q), "architect")
    prompt = q.calls[0]["options"].system_prompt
    assert "INSTR" in prompt and LOGO_NOTE in prompt


def test_binary_root_instructions_still_raise(repo: Path) -> None:
    system.make_dirs(repo / ".claude")
    system.write_bytes(repo / ".claude/CLAUDE.md", BINARY)
    with pytest.raises(UnicodeDecodeError):
        instructions.repo_instructions(repo)


def test_protocol_documents_the_utf8_note() -> None:
    text = " ".join(system.read_text(PROTOCOL).split())
    assert "(left out: @<path> is not UTF-8 text)" in text
