"""s81: CI results of the boundary's PRs: data, verdicts, the wait, gh calls, hand-overs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import pytest
from agile_team import ci, handover
from agile_team import config as cfg
from agile_team import upstream as up
from agile_team.boundary import StackEntry
from agile_team.ci import Bucket, Check, CiResult, CiVerdict, CiWatch
from agile_team.handover import Trigger as T
from agile_team.upstream import GhPrs, NoPrs, PrMode, UpstreamError

from .fake_system import FAKE_REPO, Done, FakeSystem, Hang

G, R, P, N = CiVerdict.GREEN, CiVerdict.RED, CiVerdict.PENDING, CiVerdict.NONE
JOB = "https://github.com/o/r/actions/runs/55/job/777"


def chk(bucket: str, name: str = "t", **kw) -> Check:
    return Check(name, Bucket(bucket), **kw)


def res(verdict: CiVerdict, pr: int = 14, checks: list[Check] | None = None) -> CiResult:
    return CiResult(pr, f"https://h/pull/{pr}", "abc", verdict, checks or [])


# ----- ci.py: pure ----------------------------------------------------------


def test_constants_are_pinned() -> None:
    assert (ci.CI_POLL_S, ci.CI_LOOKS, ci.MAX_LINES, ci.TAIL_LINES) == (10.0, 12, 20, 10)
    assert ci.READY_PHRASE == "ready to merge"


@pytest.mark.parametrize("raw", ["pass", "fail", "pending", "skipping", "cancel"])
def test_known_buckets(raw: str) -> None:
    assert ci.bucket_of(raw) is Bucket(raw)


def test_unknown_bucket_is_fail() -> None:
    assert ci.bucket_of("weird") is Bucket.FAIL


def test_checks_of_parses_a_json_list() -> None:
    rows = [
        {"name": "lint", "state": "SUCCESS", "bucket": "pass", "link": "l", "workflow": "ci"},
        {"name": "t", "bucket": "mystery"},
    ]
    got = ci.checks_of(json.dumps(rows))
    assert got[0] == Check("lint", Bucket.PASS, "ci", "l")
    assert got[1].bucket is Bucket.FAIL and got[1].name == "t"


def test_checks_of_no_checks_text_is_empty() -> None:
    assert ci.checks_of("no checks reported on the 'x' branch\n") == []


def test_checks_of_non_json_raises() -> None:
    with pytest.raises(UpstreamError):
        ci.checks_of("<html>oops</html>")


@pytest.mark.parametrize(
    ("buckets", "want"),
    [
        ([], N),
        (["skipping", "skipping"], N),
        (["pass", "skipping"], G),
        (["pass", "pending"], P),
        (["fail", "pending"], R),
        (["cancel", "pass"], R),
    ],
)
def test_verdict_of(buckets: list[str], want: CiVerdict) -> None:
    assert ci.verdict_of([chk(b) for b in buckets]) is want


@pytest.mark.parametrize(
    ("verdicts", "want"),
    [
        ([], N),
        ([G, N], N),
        ([G, P], P),
        ([G, R, P], R),
        ([G, G], G),
    ],
)
def test_overall(verdicts: list[CiVerdict], want: CiVerdict) -> None:
    assert ci.overall([res(v) for v in verdicts]) is want


def test_job_of() -> None:
    assert ci.job_of(JOB) == "777"
    assert ci.job_of("https://example.com/other") is None
    assert ci.job_of("") is None


def test_failing_lines_strip_prefix_and_keep_order_without_repeats() -> None:
    log = (
        "job\tRun tests\t2026-01-01T10:00:00.123Z collecting\n"
        "job\tRun tests\t2026-01-01T10:00:01.123Z FAILED tests/x.py::test_y - boom\n"
        "job\tRun tests\t2026-01-01T10:00:02.123Z ERROR tests/z.py::test_q\n"
        "job\tRun tests\t2026-01-01T10:00:03.123Z --- FAIL: TestGo (0.0s)\n"
        "job\tRun tests\t2026-01-01T10:00:04.123Z 3 failed, 4 passed\n"
        "job\tRun tests\t2026-01-01T10:00:05.123Z FAILED tests/x.py::test_y - boom\n"
    )
    assert ci.failing_lines(log) == [
        "FAILED tests/x.py::test_y - boom",
        "ERROR tests/z.py::test_q",
        "--- FAIL: TestGo (0.0s)",
        "3 failed, 4 passed",
    ]


def test_failing_lines_are_capped() -> None:
    log = "\n".join(f"j\ts\t2026-01-01T00:00:00Z FAILED t{i}.py::x" for i in range(30))
    assert len(ci.failing_lines(log)) == 20


def test_failing_lines_fall_back_to_the_tail() -> None:
    log = "\n".join(f"line {i}\n" for i in range(15))
    got = ci.failing_lines(log)
    assert got == [f"line {i}" for i in range(5, 15)]


def test_failing_lines_of_empty_log() -> None:
    assert ci.failing_lines("") == []


def test_green_report_needs_all_green() -> None:
    text = ci.green_report(3, [res(G, 14), res(G, 15)])
    assert ci.READY_PHRASE in text and "3" in text
    for bad in ([], [res(G), res(P)], [res(R)], [res(N)]):
        with pytest.raises(ValueError):
            ci.green_report(3, bad)


def test_prs_text() -> None:
    assert ci.prs_text([res(G, 14), res(G, 15)]) == "#14 https://h/pull/14; #15 https://h/pull/15"


def test_check_lines_list_only_non_passing_with_indented_lines() -> None:
    bad = chk("fail", "unit", workflow="CI", link=JOB, lines=["FAILED a", "FAILED b"])
    solo = chk("pending", "deploy", link="u")
    text = ci.check_lines([res(R, checks=[chk("pass", "lint"), chk("skipping", "s"), bad, solo])])
    assert "lint" not in text
    assert f"- CI / unit: fail {JOB}" in text
    assert "    FAILED a" in text and "    FAILED b" in text
    assert "- deploy: pending u" in text
    assert text.index("FAILED b") < text.index("deploy")


def test_result_round_trips_through_asdict() -> None:
    r = res(R, checks=[chk("fail", "u", workflow="CI", link=JOB, lines=["x"])])
    assert CiResult(**asdict(r)) == r
    again = CiResult(**json.loads(json.dumps(asdict(r))))
    assert again.verdict is R and again.checks[0].bucket is Bucket.FAIL


# ----- CiWatch --------------------------------------------------------------


@dataclass
class ScriptedPrs:
    """checks() answers from a script per call; wait_checks from a list of bools."""

    reads: list[list[Check]]
    waits: list[bool] = field(default_factory=list)
    logs: dict[str, str] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    def wait_checks(self, number: int, limit_s: float) -> bool:
        self.calls.append(("wait", number, limit_s))
        return self.waits.pop(0) if self.waits else True

    def checks(self, number: int) -> list[Check]:
        self.calls.append(("checks", number))
        return self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]

    def failed_log(self, link: str) -> str:
        self.calls.append(("log", link))
        return self.logs.get(link, "")


def entry(pr: int = 14) -> StackEntry:
    return StackEntry(1, "b", "s", "e", head="abc", pr=pr, url=f"https://h/pull/{pr}")


def watch(prs: ScriptedPrs, limit: float = 1800) -> CiWatch:
    return CiWatch(prs, limit)  # type: ignore[arg-type]


def test_green_on_first_look(fake: FakeSystem) -> None:
    prs = ScriptedPrs([[chk("pass")]])
    [r] = watch(prs).results([entry()])
    assert r.verdict is G and r.pr == 14 and r.head == "abc" and r.url == "https://h/pull/14"
    assert [c[0] for c in prs.calls] == ["wait", "checks"]
    assert prs.calls[0][2] == 1800
    assert fake.slept == []


def test_checks_not_queued_yet_are_looked_for_again(fake: FakeSystem) -> None:
    prs = ScriptedPrs([[], [], [chk("pass")]])
    [r] = watch(prs).results([entry()])
    assert r.verdict is G
    assert fake.slept == [ci.CI_POLL_S, ci.CI_POLL_S]


def test_pending_after_the_watch_ended_is_looked_at_again(fake: FakeSystem) -> None:
    prs = ScriptedPrs([[chk("pending")], [chk("pass")]])
    assert watch(prs).results([entry()])[0].verdict is G
    assert fake.slept == [ci.CI_POLL_S]


def test_never_any_checks_is_bounded_and_none(fake: FakeSystem) -> None:
    prs = ScriptedPrs([[]])
    [r] = watch(prs).results([entry()])
    assert r.verdict is N and r.checks == []
    assert sum(1 for c in prs.calls if c[0] == "checks") == ci.CI_LOOKS


def test_timeout_reports_pending_without_looking_again(fake: FakeSystem) -> None:
    prs = ScriptedPrs([[chk("pending", "slow")]], waits=[False])
    [r] = watch(prs, 60).results([entry()])
    assert r.verdict is P and r.checks[0].name == "slow"
    assert [c[0] for c in prs.calls] == ["wait", "checks"]
    assert fake.slept == []


def test_the_watch_limit_is_the_time_left_under_one_deadline(fake: FakeSystem) -> None:
    prs = ScriptedPrs([[chk("pending")], [chk("pending")]], waits=[False, True])
    original = prs.wait_checks

    def spend(number: int, limit_s: float) -> bool:
        ok = original(number, limit_s)
        fake.clock += 100
        return ok

    prs.wait_checks = spend  # type: ignore[method-assign]
    watch(prs, 60).results([entry(14), entry(15)])
    waits = [c for c in prs.calls if c[0] == "wait"]
    assert waits[0][2] == 60
    # the deadline has passed: the second PR is not watched, only read
    assert len(waits) == 1
    assert [c for c in prs.calls if c == ("checks", 15)]


def test_failing_check_gets_its_failing_lines(fake: FakeSystem) -> None:
    log = "j\ts\t2026-01-01T00:00:00Z FAILED tests/x.py::test_y"
    bad = chk("fail", "unit", link=JOB)
    other = chk("fail", "ext", link="https://other/x")
    prs = ScriptedPrs([[bad, other, chk("pass")]], logs={JOB: log})
    [r] = watch(prs).results([entry()])
    assert r.verdict is R
    assert r.checks[0].lines == ["FAILED tests/x.py::test_y"]
    assert r.checks[1].lines == []
    assert [c for c in prs.calls if c[0] == "log"] == [("log", JOB)]


def test_no_entries_gives_no_results(fake: FakeSystem) -> None:
    assert watch(ScriptedPrs([[]])).results([]) == []


# ----- upstream: gh ---------------------------------------------------------


class Exec:
    def __init__(self, results: dict[tuple, tuple[int, str]]):
        self.results, self.calls = results, []

    def __call__(self, argv: list[str], limit_s: float = 0.0) -> tuple[int, str]:
        self.calls.append((argv, limit_s))
        return self.results.get(tuple(argv), (0, ""))


WATCH = ("gh", "pr", "checks", "14", "--watch")
JSON = ("gh", "pr", "checks", "14", "--json", "name,state,bucket,link,workflow")
VIEW = ("gh", "run", "view", "--job", "777", "--log-failed")


def test_wait_checks_argv_and_result() -> None:
    ex = Exec({})
    assert GhPrs(ex).wait_checks(14, 99.0) is True
    assert ex.calls == [(list(WATCH), 99.0)]
    assert GhPrs(Exec({WATCH: (1, "")})).wait_checks(14, 1) is True
    assert GhPrs(Exec({WATCH: (124, "")})).wait_checks(14, 1) is False


def test_checks_parse_despite_a_failing_exit_code() -> None:
    body = json.dumps([{"name": "u", "bucket": "fail", "link": JOB, "workflow": "CI"}])
    got = GhPrs(Exec({JSON: (8, body)})).checks(14)
    assert got == [Check("u", Bucket.FAIL, "CI", JOB)]


def test_checks_none_reported() -> None:
    assert GhPrs(Exec({JSON: (1, "no checks reported on the 'b' branch")})).checks(14) == []


def test_failed_log() -> None:
    ex = Exec({VIEW: (0, "the log")})
    assert GhPrs(ex).failed_log(JOB) == "the log"
    assert ex.calls[0][0] == list(VIEW)
    assert GhPrs(Exec({VIEW: (1, "err")})).failed_log(JOB) == ""


def test_failed_log_without_a_job_makes_no_call() -> None:
    ex = Exec({})
    assert GhPrs(ex).failed_log("https://other") == ""
    assert ex.calls == []


def test_no_prs_raises_for_the_new_calls() -> None:
    p = NoPrs()
    for call in (lambda: p.wait_checks(1, 1.0), lambda: p.checks(1), lambda: p.failed_log("l")):
        with pytest.raises(UpstreamError):
            call()


def test_command_runner_passes_the_limit_and_maps_a_hang(fake: FakeSystem) -> None:
    fake.reply(("gh", "pr", "checks"), Hang())
    run = up.command_runner(FAKE_REPO)
    code, out = run(["gh", "pr", "checks", "14", "--watch"], 5.0)
    assert code == 124 and out == "gh timed out after 5s"
    assert fake.commands[0].timeout == 5.0


def test_command_runner_default_limit(fake: FakeSystem) -> None:
    fake.reply(("gh", "--version"), Done(0, "gh 2"))
    up.command_runner(FAKE_REPO)(["gh", "--version"])
    assert fake.commands[0].timeout == up.GH_TIMEOUT


# ----- config ---------------------------------------------------------------


def test_ci_timeout_default_and_read() -> None:
    assert cfg.DEFAULT_CI_TIMEOUT_S == 1800.0
    assert cfg.Gates().ci_timeout_s == 1800.0


@pytest.mark.parametrize("bad", [0, -1])
def test_ci_timeout_must_be_positive(bad: int) -> None:
    c = cfg.from_raw(FAKE_REPO, {"gates": {"ci_timeout_s": bad}})
    known = cfg.Known({"developer"}, {"package"})
    assert "gates.ci_timeout_s must be positive" in cfg.validate(c, known)


# ----- boundary types -------------------------------------------------------


def test_stage_ci_follows_push() -> None:
    from agile_team import boundary as bd

    assert bd.STAGES[-1] is bd.Stage.CI and bd.STAGES[-2] is bd.Stage.PUSH
    assert bd.Stage.CI in bd.RESTACK_ONLY
    assert bd.BoundaryHold.CI_FAILED == "ci_failed"
    assert bd.BoundaryHold.CI_PENDING == "ci_pending"
    assert bd.UpstreamState().ci_bug == ""
    assert StackEntry(1, "b", "s", "e").ci is None


def test_pushed_and_local_notes_never_say_ready() -> None:
    from agile_team import boundary as bd

    assert ci.READY_PHRASE not in bd.PUSHED_REPORT
    assert ci.READY_PHRASE not in bd.LOCAL_REPORT
    assert bd.LOCAL_REPORT.endswith("No CI result exists.")
    assert bd.PR_KIND[PrMode.READY] == "open" and bd.PR_KIND[PrMode.DRAFT] == "draft"


def test_stall_hint_names_record_ci_bug_only_for_a_failed_ci() -> None:
    from agile_team import boundary as bd

    assert "record_ci_bug" in bd.stall_hint(bd.BoundaryHold.CI_FAILED)
    assert "continue_boundary" in bd.stall_hint(bd.BoundaryHold.SYNC_CONFLICT)
    assert "continue_boundary" in bd.stall_hint(None)
    assert "{story}" in bd.CI_BUG_FIRST


# ----- hand-over rows -------------------------------------------------------


def brep(hold=None, **fields) -> dict:
    base = {"edge": "end", "sprint": 2, "stage": "ci", "hold": hold}
    return {"role": "runner", "status": "boundary", "boundary": {**base, **fields}}


def test_ci_green_row_matches_on_the_ci_field() -> None:
    report = brep(None, ci="green", prs="#14 u")
    assert handover.triggers(report) == [T.CI_GREEN]
    [line] = handover.report_lines(report, None)
    assert "ready to merge" in line and "#14 u" in line


def test_ci_failed_row_names_checks_and_the_tool() -> None:
    report = brep("ci_failed", ci="red", prs="#14 u", checks="- CI / unit: fail x")
    assert handover.triggers(report) == [T.CI_FAILED]
    [line] = handover.report_lines(report, None)
    assert "- CI / unit: fail x" in line and "record_ci_bug(story)" in line
    assert "NOT ready" in line and ci.READY_PHRASE not in line


def test_ci_pending_row_names_the_reason() -> None:
    report = brep("ci_pending", ci="pending", prs="#14 u", checks="- t: pending", reason="slow")
    assert handover.triggers(report) == [T.CI_PENDING]
    [line] = handover.report_lines(report, None)
    assert "slow" in line and "NOT ready" in line and ci.READY_PHRASE not in line


def test_a_done_report_with_ci_none_matches_no_row() -> None:
    assert handover.triggers(brep(None, ci="none", note="no checks")) == []
    assert handover.triggers(brep(None, ci="red", story="s9")) == []
