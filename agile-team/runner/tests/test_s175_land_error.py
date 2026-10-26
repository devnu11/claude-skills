"""s175: a landing that raises keeps its error: stage event, crash.log, hold reason."""

import asyncio
from pathlib import Path

import pytest
from agile_team import halt, handover, scheduler, stage_log, stages, system
from agile_team.boundary import StepKind
from agile_team.gates import StoryState
from agile_team.git_ops import Git, GitError
from agile_team.po_tools import Start
from agile_team.router import Work
from agile_team.upstream import GhPrs, UpstreamError

from .test_s99_stages import make_log, runs

NAME = stages.Name
TOLERATED = "git worktree remove --force .team/run/land"
RAISING = "gh api repos/{owner}/{repo}/commits/abc/check-runs"


class Exec:
    """A gh runner answering every call with one scripted result."""

    def __init__(self, code: int, out: str) -> None:
        self.result = (code, out)

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        stages.note(" ".join(argv), self.result[0])
        return self.result


def land_event(repo: Path, exc: Exception, *notes: tuple[str, int]) -> dict:
    log = make_log(repo)
    with pytest.raises(type(exc)), log.open(NAME.STORY_LAND):
        for command, code in notes:
            stages.note(command, code)
        raise exc
    return runs(log)[0].data


# ---------- AC1: the event ----------


def test_the_event_carries_the_exception_message_beside_raised(repo: Path) -> None:
    data = land_event(repo, GitError("push refused"))
    assert (data["raised"], data["error"]) == ("GitError", "push refused")
    keys = list(data)
    assert keys.index("error") == keys.index("raised") + 1


def test_the_error_is_the_first_line_only(repo: Path) -> None:
    assert land_event(repo, GitError("first\nsecond\nthird"))["error"] == "first"


def test_the_error_is_cut_at_500_characters(repo: Path) -> None:
    assert land_event(repo, GitError("x" * 900))["error"] == "x" * 500


def test_an_exception_without_text_gives_an_empty_error(repo: Path) -> None:
    assert land_event(repo, UpstreamError(""))["error"] == ""


def test_a_stage_that_does_not_raise_has_no_error(repo: Path) -> None:
    log = make_log(repo)
    with log.open(NAME.STORY_LAND):
        stages.note("git push", 0)
    assert runs(log)[0].data["error"] is None


def test_detail_and_code_name_the_call_that_raised_not_a_tolerated_one(repo: Path) -> None:
    exc = UpstreamError("{", stages.Invocation(RAISING, 1))
    data = land_event(repo, exc, (TOLERATED, 128))
    assert (data["detail"], data["code"]) == (RAISING, 1)


def test_an_exception_without_a_call_shows_no_earlier_command(repo: Path) -> None:
    data = land_event(repo, GitError("x"), ("git fetch", 0), ("git push", 1))
    assert (data["detail"], data["code"]) == ("", None)


def test_a_failure_in_a_stage_that_ends_well_is_still_the_first_failure(repo: Path) -> None:
    log = make_log(repo)
    with log.open(NAME.GATE_GREEN):
        stages.note("a", 2)
        stages.note("b", 0)
    assert (runs(log)[0].data["detail"], runs(log)[0].data["code"]) == ("a", 2)


# ---------- AC3: the upstream message ----------


@pytest.mark.parametrize("body", ["", "{", "  \n"])
def test_an_empty_or_non_text_body_still_names_the_command_and_code(body: str) -> None:
    prs = GhPrs(Exec(1, body))
    with pytest.raises(UpstreamError) as raised:
        prs.list_checks("abc")
    text = str(raised.value)
    assert RAISING in text and "1" in text.replace(RAISING, "")
    assert "\n" not in text


def test_json_output_is_trimmed_to_one_line() -> None:
    prs = GhPrs(Exec(4, '{\n  "message": "rate limit"\n}\n(HTTP 403)\n'))
    with pytest.raises(UpstreamError) as raised:
        prs.list_checks("abc")
    text = str(raised.value)
    assert "\n" not in text and '{ "message": "rate limit" }' in text and "HTTP 403" in text


def test_plain_text_output_is_kept_stripped() -> None:
    with pytest.raises(UpstreamError) as raised:
        GhPrs(Exec(4, "HTTP 403: limit\nsee docs\n")).list_checks("abc")
    assert str(raised.value) == "HTTP 403: limit\nsee docs"


def test_an_error_with_a_full_message_keeps_it() -> None:
    with pytest.raises(UpstreamError, match="nope"):
        GhPrs(Exec(1, "nope")).rerun("https://h/o/r/actions/runs/1/job/22")


# ---------- AC2, AC3: the scheduler ----------


def land_work(make_runtime):
    rt = make_runtime()
    rt.state.sprint = 1
    story = StoryState(id="s1", title="T", step="land", sprint=1)
    rt.state.stories = {"s1": story}
    return (
        rt,
        scheduler.Scheduler(rt, Start("task")),
        Work("developer-cli", story, "b", StepKind.LAND),
    )


def run_failing_land(make_runtime, exc: Exception):
    rt, s, work = land_work(make_runtime)
    work.story.branch = "b"
    reports: list[dict] = []

    class Lander:
        async def land(self, _: object) -> dict:
            raise exc

    s.lander = Lander()
    s.report_back = lambda _, report: reports.append(report)
    asyncio.run(s.run_work(work))
    return rt, reports[0]


def test_a_raising_landing_logs_its_traceback_to_crash_log(make_runtime) -> None:
    rt, report = run_failing_land(make_runtime, UpstreamError("gh api x (exit 1): {"))
    log = system.read_text(rt.config.run_dir / halt.CRASH_LOG)
    assert log.startswith("--- ") and "UpstreamError" in log.splitlines()[0]
    assert "Traceback" in log and "gh api x (exit 1): {" in log
    assert report["status"] == "error"


def test_the_report_reason_carries_the_error_message(make_runtime) -> None:
    _, report = run_failing_land(make_runtime, UpstreamError("gh api x (exit 1): {"))
    assert report["status"] == "error"
    assert report["reason"] == "crashed: UpstreamError: gh api x (exit 1): {"


# ---------- T1: the event masks secrets ----------


def test_show_error_masks_a_secret() -> None:
    assert stage_log.show_error("failed token=abc") == "failed token=***"
    assert stage_log.show_error(None) is None


def test_the_event_error_is_masked(repo: Path) -> None:
    assert land_event(repo, GitError("bad token=abc"))["error"] == "bad token=***"


# ---------- T2: exact GH_FAILED strings ----------


def failure(code: int, out: str) -> str:
    with pytest.raises(UpstreamError) as raised:
        GhPrs(Exec(code, out))._gh("api", "x")
    return str(raised.value)


def test_an_empty_body_reads_no_output() -> None:
    assert failure(1, "") == "gh api x: exit 1: (no output)"


def test_a_long_json_body_is_cut_at_300() -> None:
    body = "{" + "y" * 900
    assert failure(1, body) == "gh api x: exit 1: " + body[:300]


def test_an_http_status_in_the_body_is_named() -> None:
    body = '{\n  "message": "rate"\n}\ngh: rate (HTTP 403)'
    expected = 'gh api x: exit 1, HTTP 403: { "message": "rate" } gh: rate (HTTP 403)'
    assert failure(1, body) == expected


def test_the_error_carries_its_invocation() -> None:
    with pytest.raises(UpstreamError) as raised:
        GhPrs(Exec(4, "{"))._gh("api", "x")
    assert raised.value.invocation == stages.Invocation("gh api x", 4)


# ---------- T3: GitError ----------


def test_git_run_failure_carries_the_git_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "run", lambda _: system.Completed(128, "", " fatal: no \n"))
    with pytest.raises(GitError) as raised:
        Git(Path("r")).run("push", "origin")
    assert str(raised.value) == "git push origin: fatal: no"
    assert raised.value.invocation == stages.Invocation("git push origin", 128)


# ---------- T4: close ----------


class Script:
    """A gh runner answering by its second argument."""

    def __init__(self, answers: dict[str, tuple[int, str]]) -> None:
        self.answers = answers

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        return self.answers[argv[1] + " " + argv[2]]


def test_close_failing_on_an_open_pr_names_the_close_call() -> None:
    prs = GhPrs(Script({"pr close": (1, "{"), "pr view": (0, '{"state": "OPEN"}')}))
    with pytest.raises(UpstreamError) as raised:
        prs.close(7, "n")
    assert raised.value.invocation == stages.Invocation("gh pr close 7 --comment n", 1)
    assert str(raised.value).startswith("gh pr close 7 --comment n: exit 1")


# ---------- T5: output that is not JSON ----------


def test_json_decode_failure_names_the_call_with_exit_zero() -> None:
    with pytest.raises(UpstreamError) as raised:
        GhPrs(Exec(0, "{"))._read_gh_json("pr", "list")
    assert str(raised.value) == "gh pr list: exit 0: {"
    assert raised.value.invocation == stages.Invocation("gh pr list", 0)
    assert isinstance(raised.value.__cause__, ValueError)


# ---------- T8: GhPrs.checks ----------

CHECKS = "gh pr checks 14 --required --json " + "name,state,bucket,link,workflow"


class Sequence:
    """A gh runner answering its scripted results in order, recording argvs."""

    def __init__(self, *results: tuple[int, str]) -> None:
        self.results = list(results)
        self.argvs: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.argvs.append(argv)
        return self.results.pop(0)


def test_checks_decode_failure_names_the_required_call_and_real_code() -> None:
    with pytest.raises(UpstreamError) as raised:
        GhPrs(Sequence((1, "{"))).checks(14)
    assert str(raised.value) == f"{CHECKS}: exit 1: {{"
    assert raised.value.invocation == stages.Invocation(CHECKS, 1)


def test_checks_decode_failure_after_the_fallback_names_the_argv_without_required() -> None:
    run = Sequence((1, "no required checks reported on the 'x' branch"), (8, "{"))
    with pytest.raises(UpstreamError) as raised:
        GhPrs(run).checks(14)
    plain = CHECKS.replace(" --required", "")
    assert str(raised.value) == f"{plain}: exit 8: {{"
    assert raised.value.invocation == stages.Invocation(plain, 8)
    assert "--required" not in run.argvs[1]


def test_checks_decode_failure_names_the_http_status() -> None:
    with pytest.raises(UpstreamError, match="exit 1, HTTP 403"):
        GhPrs(Sequence((1, "{\n(HTTP 403)"))).checks(14)


# ---------- T6: the hold reason ----------


def test_an_error_hold_carries_the_reason() -> None:
    report = {"status": "error", "reason": "crashed: UpstreamError: gh x"}
    assert handover.hold_reason(report) == "error: crashed: UpstreamError: gh x"


def test_an_error_hold_without_a_reason_is_bare() -> None:
    assert handover.hold_reason({"status": "error"}) == "error"
    assert handover.hold_reason({"status": "error", "reason": ""}) == "error"


# ---------- T7: crash.log write failure ----------


def test_a_crash_log_write_error_does_not_hide_the_land_error(
    make_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(scheduler, "log_traceback", fail)
    _, report = run_failing_land(make_runtime, UpstreamError("gh api x: exit 1: {"))
    assert report["reason"] == "crashed: UpstreamError: gh api x: exit 1: {"


# ---------- AC1-AC3 together ----------


def test_a_land_that_hits_the_rate_limit_keeps_its_error_everywhere(make_runtime) -> None:
    rt, s, work = land_work(make_runtime)
    work.story.branch = "b"
    body = '{\n  "message": "API rate limit exceeded"\n}\ngh: rate limit (HTTP 403)'
    reports: list[dict] = []

    class Lander:
        async def land(self, _: object) -> dict:
            with rt.stage_log.open(stages.Name.STORY_LAND):
                stages.note(TOLERATED, 128)
                GhPrs(Exec(1, body)).list_checks("abc")
            return {}

    s.lander = Lander()
    s.report_back = lambda _, report: reports.append(report)
    asyncio.run(s.run_work(work))
    data = runs(rt.stage_log)[0].data
    assert (data["code"], data["raised"]) == (1, "UpstreamError")
    assert data["detail"].startswith(RAISING)
    assert "exit 1, HTTP 403" in data["error"]
    assert "UpstreamError" in system.read_text(rt.config.run_dir / halt.CRASH_LOG)
    assert "exit 1, HTTP 403" in reports[0]["reason"]
    assert "exit 1, HTTP 403" in handover.hold_reason(reports[0])
