"""s175: a landing that raises keeps its error: stage event, crash.log, hold reason."""

import asyncio
from pathlib import Path

import pytest
from agile_team import halt, scheduler, stages, system
from agile_team.boundary import StepKind
from agile_team.gates import StoryState
from agile_team.git_ops import GitError
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
