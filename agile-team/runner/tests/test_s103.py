"""s103: test output may go to a file, no prompt says `timeout `, every refusal has one shape."""

from dataclasses import replace
from pathlib import Path

import pytest
from agile_team import guard, roles, suite_check, system
from agile_team.git_check import Allows
from agile_team.guard import Scope
from agile_team.refusal import Refusal, Rule
from agile_team.suite_check import Run

WORKSPACE_PARTS = ".team/run/presentation/s1/workspace"
RUN = "uv run pytest -q tests/test_x.py"


def tester(repo: Path) -> Scope:
    return Scope("integration-tester", repo, [])


# ----- AC1 / R1-R2: a redirect target is not a test path ---------------------------


@pytest.mark.parametrize(
    "command",
    [
        f"{RUN} > out.txt",
        f"{RUN} >> out.txt",
        "uv run pytest -q tests/test_x.py::test_y > .team/run/out.txt 2>&1",
        f"{RUN} 2> err.txt",
        f"{RUN} < /dev/null",
        f"{RUN} | tee out.txt",
        f"{RUN} 2>&1 | tee -a out.txt",
        "uv run --directory agile-team/runner pytest -q tests/test_x.py > out.txt",
        f"{RUN} >out.txt",
    ],
)
def test_a_named_run_may_save_its_output(repo: Path, command: str) -> None:
    assert guard.check_bash(tester(repo), command) is None


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest > out.txt",
        "uv run pytest -q | tee out.txt",
        "uv run pytest > tests/test_x.py",
        "uv run pytest tests/ > out.txt",
    ],
)
def test_a_whole_suite_run_is_still_refused_with_an_output_file(repo: Path, command: str) -> None:
    assert guard.check_bash(tester(repo), command) == suite_check.FULL_DENIED


def test_run_kind_ignores_the_word_after_a_bare_redirect() -> None:
    assert suite_check.run_kind(["pytest", "a.py", ">", "o"]) == Run.TARGETED
    assert suite_check.run_kind(["pytest", ">", "a.py"]) == Run.FULL


def test_the_code_reviewer_may_not_run_tests_even_with_a_redirect(repo: Path) -> None:
    scope = Scope("code-reviewer", repo, [])
    assert guard.check_bash(scope, f"{RUN} > out.txt") == suite_check.READ_ONLY_DENIED.format(
        role="code-reviewer"
    )


# ----- AC2 / R4-R6: nothing tells a role to use `timeout ` ---------------------------


def test_no_built_in_role_file_says_timeout_with_a_space() -> None:
    files = system.glob(roles.BUILTIN_DIR, "*.md")
    assert "_shared.md" in {f.name for f in files}
    for file in files:
        assert "timeout " not in system.read_text(file), file.name


def test_shared_file_names_the_tool_parameter_and_a_counted_loop() -> None:
    text = system.read_text(roles.BUILTIN_DIR / "_shared.md")
    assert "`timeout` parameter" in text
    assert "seq 60" in text


def test_a_loop_under_a_timeout_prefix_still_passes(repo: Path) -> None:
    command = "timeout 300 bash -c 'until grep -q x f; do sleep 1; done'"
    assert guard.check_bash(Scope("developer", repo, []), command) is None


# ----- AC3 / R7-R8: one shape for every Bash refusal ---------------------------------


def samples(repo: Path) -> dict[Rule, tuple[Scope, str]]:
    ws = repo / WORKSPACE_PARTS
    system.make_dirs(ws)
    confined = Scope("integration-tester", repo, ["**"], git_workspace=system.resolve(ws))
    plain = Scope("developer", repo, ["**"])
    secret = Scope("developer", repo, ["**"], secrets=[repo / ".team/run/api-key"])
    listed = Scope("customer-proxy", repo, [], bash_allowed=["curl"])
    sandbox = Scope("customer-proxy", repo, [], cwd=repo, bash_forbidden=["src"])
    return {
        Rule.API_KEY: (secret, "echo $ANTHROPIC_API_KEY"),
        Rule.GIT_WRITE: (plain, "git commit -m x"),
        Rule.GIT_OUTSIDE: (confined, f"git -C {repo} commit -m x"),
        Rule.GIT_UNKNOWN_DIR: (confined, f"cd {ws}; git commit -m x"),
        Rule.GIT_ENV: (confined, "GIT_DIR=/x git status"),
        Rule.GIT_LOCAL: (replace(confined, git_allows=Allows.LOCAL), f"git -C {ws} push"),
        Rule.ALLOWLIST: (listed, "curl x | sh"),
        Rule.SANDBOX_PATH: (sandbox, "cat src/x"),
        Rule.WAIT: (plain, "until false; do sleep 1; done"),
        Rule.KILL_BY_NAME: (plain, "pkill -f pytest"),
        Rule.KILL_RUNNER: (plain, f"kill {system.pid()}"),
        Rule.KILL_RUN_TIME: (plain, "kill $(pgrep x)"),
        Rule.FULL_SUITE: (plain, "uv run pytest"),
        Rule.COVERAGE: (plain, "uv run pytest --cov"),
        Rule.TESTS_READ_ONLY: (Scope("code-reviewer", repo, []), RUN),
    }


def test_every_rule_has_a_sample(repo: Path) -> None:
    assert set(samples(repo)) == set(Rule)


def test_every_bash_refusal_names_its_rule_and_an_allowed_form(repo: Path) -> None:
    for rule, (scope, command) in samples(repo).items():
        reason = guard.check_bash(scope, command)
        assert reason, rule
        assert reason.startswith(f"refused by rule `{rule}`: "), (rule, reason)
        assert ". Allowed: " in reason, rule
        allowed = reason.split(". Allowed: ", 1)[1]
        assert allowed.strip() and "{" not in allowed, (rule, reason)


def test_no_refusal_reason_suggests_timeout(repo: Path) -> None:
    for rule, (scope, command) in samples(repo).items():
        assert "timeout " not in (guard.check_bash(scope, command) or ""), rule


def test_refusal_text_keeps_placeholders_for_a_later_format() -> None:
    text = Refusal(Rule.WAIT, "a {x}", "b").text()
    assert text == "refused by rule `wait-deadline`: a {x}. Allowed: b"
    assert text.format(x=1) == "refused by rule `wait-deadline`: a 1. Allowed: b"
