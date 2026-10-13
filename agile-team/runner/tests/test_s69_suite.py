"""s69: suite_check rules, guard wiring, results store, gate runs, config, role texts."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

import pytest
from agile_team import config as config_mod
from agile_team import gates, guard, system
from agile_team.config import Targeted, Toolchain
from agile_team.guard import Scope
from agile_team.results import (
    BRIEF_RESULTS,
    RESULT_LINES,
    RESULTS_HEAD,
    Ran,
    Results,
    result_tail,
    section,
)
from agile_team.roles import RoleBook
from agile_team.suite_check import (
    COVERAGE_DENIED,
    FULL_DENIED,
    SUITE_RULES,
    Run,
    is_target,
    run_kind,
    suite_denial,
)

from .conftest import FakeRunner

UV = "uv run --directory agile-team/runner "


def kind(command: str) -> Run | None:
    return run_kind(shlex.split(command))


# ----- suite_check -------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q tests/test_x.py",
        "pytest tests/test_x.py::test_y",
        UV + "pytest -q tests/test_x.py",
        "pytest -q tests/test_a.py tests/test_b.py::t",
        "pytest tests/test_a.py tests/test_b.py::t",
        "pytest --tb short tests/test_x.py",
        "pytest --maxfail 1 -x tests/test_x.py",
        "PYTHONPATH=. pytest tests/test_x.py",
    ],
)
def test_named_tests_are_targeted(command: str) -> None:
    assert kind(command) is Run.TARGETED
    assert suite_denial("developer-cli", shlex.split(command)) is None


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        "pytest -q",
        "pytest tests/",
        "pytest tests/e2e",
        "pytest tests/*.py",
        "pytest -k test_x.py",
        "pytest --ignore tests/test_x.py",
        "pytest -m slow tests",
        "python -m pytest -q",
        "python3 -m pytest",
        "uv run pytest -x",
        "timeout 600 uv run pytest",
        "/usr/bin/pytest -q",
        "pytest tests/test_x.py tests/",
        "pytest tests/test_x.py .",
        "pytest tests/test_x.py -- tests/e2e",
        "pytest --foo 1 tests/test_x.py",
        "PYTHONPATH=. pytest -q",
        "FOO=1 uv run pytest",
        "A=1 B=2 python -m pytest",
        "exec pytest",
        "command pytest -q",
        "xargs pytest",
    ],
)
def test_unnamed_runs_are_full(command: str) -> None:
    assert kind(command) is Run.FULL


@pytest.mark.parametrize(
    "command",
    [
        "pytest --cov",
        "pytest --cov=agile_team tests/test_x.py",
        "uv run pytest --cov-report=term",
        "coverage run -m pytest tests/test_x.py",
        "COVERAGE_FILE=x pytest --cov",
    ],
)
def test_coverage_runs(command: str) -> None:
    assert kind(command) is Run.COVERAGE


@pytest.mark.parametrize(
    "command",
    [
        "grep -n pytest x.py",
        "rg -- --cov",
        "echo pytest",
        "ls tests",
        "coverage report",
        "",
        "FOO=1 echo pytest",
        "FOO=1",
    ],
)
def test_other_commands_start_no_run(command: str) -> None:
    assert kind(command) is None


def test_shell_dash_c_is_expanded() -> None:
    assert run_kind(["bash", "-c", "pytest -q"]) is Run.FULL
    assert run_kind(["sh", "-c", "pytest tests/test_x.py"]) is Run.TARGETED
    assert run_kind(["zsh", "-c", "echo hi"]) is None


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("tests/test_x.py", True),
        ("tests/test_x.py::test_y", True),
        ("tests/", False),
        ("tests/e2e", False),
        ("tests/*.py", False),
        ("tests/t[1].py", False),
        ("-k", False),
        ("-x.py", False),
        ("foo", False),
    ],
)
def test_is_target(word: str, expected: bool) -> None:
    assert is_target(word) is expected


@pytest.mark.parametrize(
    "role", ["developer-cli", "unit-tester", "integration-tester", "code-reviewer", "architect"]
)
def test_full_and_coverage_denied_to_all_but_devops(role: str) -> None:
    assert suite_denial(role, ["pytest"]) == FULL_DENIED
    assert suite_denial(role, ["pytest", "--cov"]) == COVERAGE_DENIED


def test_devops_may_run_full_and_coverage() -> None:
    assert suite_denial("devops", ["pytest"]) is None
    assert suite_denial("devops", ["pytest", "--cov"]) is None


def test_targeted_denied_to_readers_only() -> None:
    words = ["pytest", "tests/test_x.py"]
    for role in ("code-reviewer", "quality-czar"):
        assert suite_denial(role, words).count(f"{role} reads tests") == 1
    for role in ("developer-cli", "unit-tester", "devops"):
        assert suite_denial(role, words) is None


def test_reasons_name_the_runner_tools() -> None:
    for text in (FULL_DENIED, COVERAGE_DENIED):
        assert "run_tests" in text and "run_new_tests" in text
        assert "## Runner results" in text
    assert [r.run for r in SUITE_RULES] == [Run.FULL, Run.COVERAGE, Run.TARGETED]


def test_guard_denies_in_a_pipeline(scratch: Path) -> None:
    s = Scope("developer-cli", scratch, ["src/**"])
    assert guard.check_bash(s, "cd x && uv run pytest -q 2>&1 | tail -5") == FULL_DENIED
    assert guard.check_bash(s, "cd x && uv run pytest -q tests/test_x.py 2>&1 | tail -5") is None
    assert guard.check_bash(s, "uv run pytest -q  # everything") == FULL_DENIED


def test_guard_hook_denies_with_the_reason(scratch: Path) -> None:
    hook = guard.pre_tool_hook(Scope("developer-cli", scratch, ["src/**"]))
    out = asyncio.run(hook({"tool_name": "Bash", "tool_input": {"command": "pytest"}}, None, None))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert FULL_DENIED in out["hookSpecificOutput"]["permissionDecisionReason"]


# ----- results -----------------------------------------------------------


def ran(name: str = "coverage", code: int = 0, tail: str = "TOTAL 99%", **kw: str) -> Ran:
    return Ran(name, code, tail, kw.get("at", "1234567890"), kw.get("where", "implement gate"))


def test_keep_and_latest_round_trip(scratch: Path) -> None:
    store = Results(scratch)
    store.keep("s1", ran())
    assert store.latest("s1", "coverage") == ran()
    assert system.is_file(scratch / "results" / "s1" / "coverage.json")


def test_keep_replaces_the_same_command(scratch: Path) -> None:
    store = Results(scratch)
    store.keep("s1", ran(tail="old"))
    store.keep("s1", ran(tail="new"))
    assert store.latest("s1", "coverage").tail == "new"


def test_latest_missing_or_corrupt_is_none(scratch: Path) -> None:
    store = Results(scratch)
    assert store.latest("s1", "test") is None
    store.keep("s1", ran("test"))
    system.write_text(scratch / "results" / "s1" / "test.json", "{not json")
    assert store.latest("s1", "test") is None


def test_shown_follows_the_table_and_skips_missing(scratch: Path) -> None:
    store = Results(scratch)
    for name in ("static", "coverage"):
        store.keep("s1", ran(name))
    assert [r.name for r in store.shown("s1", "quality")] == ["coverage", "static"]
    assert store.shown("s1", "design") == []
    assert BRIEF_RESULTS["implement"] == ("test", "coverage")
    assert BRIEF_RESULTS["review"] == ("coverage",)


def test_section_format() -> None:
    assert section([]) == ""
    text = section([ran(), ran("lint", 1, "bad", where="before quality")])
    assert text.startswith(RESULTS_HEAD)
    assert "### coverage: exit 0 (implement gate, at 1234567)" in text
    assert "### lint: exit 1 (before quality, at 1234567)" in text
    assert "```text\nTOTAL 99%\n```" in text
    assert "1234567890" not in text


def test_result_tail_keeps_last_sixty_lines() -> None:
    text = "\n".join(str(i) for i in range(100))
    lines = result_tail(text).splitlines()
    assert RESULT_LINES == 60 and len(lines) == 60 and lines[0] == "40" and lines[-1] == "99"
    assert result_tail("a\nb") == "a\nb"


# ----- gates carry their run ---------------------------------------------


def made(results=None) -> gates.Checks:
    return gates.Checks({"test": "T", "coverage": "C"}, 95.0, FakeRunner(results))


def test_tests_red_carries_the_run() -> None:
    red = made({"T": (1, "FAILED")}).tests_red()
    assert red.verdict is gates.Verdict.PASS and red.ran == Ran("test", 1, "FAILED")
    green = made({"T": (0, "ok")}).tests_red()
    assert green.verdict is gates.Verdict.BOUNCE and green.ran == Ran("test", 0, "ok")
    slow = made({"T": (124, "slow")}).tests_red()
    assert slow.ran == Ran("test", 124, "slow")


def test_reworked_carries_the_run() -> None:
    out = made({"T": (0, "ok")}).tests_reworked(None)
    assert out.ran == Ran("test", 0, "ok")


@pytest.mark.parametrize(
    ("result", "code"),
    [((0, "TOTAL 99%"), 0), ((0, "TOTAL 50%"), 0), ((1, "1 failed\nTOTAL 80%"), 1)],
)
def test_coverage_gate_carries_the_run(result: tuple[int, str], code: int) -> None:
    out = made({"C": result}).tests_green_and_covered()
    assert out.ran == Ran("coverage", code, result[1])


def test_other_gates_leave_ran_empty() -> None:
    assert made({"T": (0, "ok")}).green().ran is None
    assert gates.Outcome(gates.Verdict.PASS).ran is None


# ----- config ------------------------------------------------------------


def test_targeted_for_picks_the_longest_root() -> None:
    a, b, every = (
        Targeted("a", "A {tests}"),
        Targeted("a/b", "B {tests}"),
        Targeted("", "E {tests}"),
    )
    tc = Toolchain(targeted=[every, a, b])
    assert tc.targeted_for("a/b/t.py") is b
    assert tc.targeted_for("a/t.py") is a
    assert tc.targeted_for("z/t.py") is every
    assert Toolchain(targeted=[a]).targeted_for("z/t.py") is None
    assert a.holds("a/x.py") and not a.holds("ab/x.py") and every.holds("any")
    assert a.relative("a/tests/t.py") == "tests/t.py" and every.relative("t.py") == "t.py"


def raw(rows: list[dict]) -> dict:
    from .conftest import PY_CONFIG

    return {**PY_CONFIG, "toolchain": {**PY_CONFIG["toolchain"], "targeted": rows}}


def test_targeted_rows_load(scratch: Path) -> None:
    cfg = config_mod.from_raw(
        scratch, raw([{"root": "r", "command": "x {tests}"}, {"command": "y {tests}"}])
    )
    assert cfg.toolchain.targeted == [Targeted("r", "x {tests}"), Targeted("", "y {tests}")]
    assert config_mod.from_raw(scratch, raw([])).toolchain.targeted == []


def test_targeted_row_without_tests_placeholder_is_an_error(scratch: Path) -> None:
    bad = config_mod.from_raw(scratch, raw([{"root": "r", "command": "pytest"}]))
    assert "toolchain.targeted commands must hold {tests}" in config_mod.broken(
        config_mod.TOOLCHAIN_RULES, bad.toolchain
    )
    ok = config_mod.from_raw(scratch, raw([{"root": "r", "command": "pytest {tests}"}]))
    assert config_mod.broken(config_mod.TOOLCHAIN_RULES, ok.toolchain) == []


# ----- role files --------------------------------------------------------


def test_role_texts(scratch: Path) -> None:
    book = RoleBook.for_repo(scratch, {})
    czar = book.resolve("quality-czar")
    assert czar.tools == ["Read", "Grep", "Glob"] and "Run nothing" in czar.body
    assert "run_tests" in book.resolve("developer").body
    assert "re-check red" in book.resolve("unit-tester").body
    assert "do not run them" in book.resolve("code-reviewer").body
    assert "Never run the full suite" in book.shared_body()
