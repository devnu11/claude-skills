"""s111: only a green CI run is done; our failure blocks, a broken main does not."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from importlib import resources

import pytest
from agile_team import boundary as bd
from agile_team import ci, handover, system
from agile_team import ci_triage as tri
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.ci import Bucket, Card, CardState, Check, CiResult, CiVerdict, CiWatch
from agile_team.ci import CheckKind as K
from agile_team.ci_triage import Job, Seen, Step
from agile_team.dashboard import snapshot
from agile_team.gates import StoryState, StoryStatus
from agile_team.handover import Trigger as T
from agile_team.po_tools import NO_CI_HOLD, Tools
from agile_team.upstream import GhPrs, NoPrs, PrMode, UpstreamError

from .fake_system import FakeSystem
from .test_boundary_runner import NEW, Env, entry
from .test_snapshot import FIXTURE_TEXT

LINK = "https://github.com/o/r/actions/runs/1/job/77"
MAIN_LINK = "https://github.com/o/r/actions/runs/2/job/88"
OTHER = "0th3r000000000000000000000000000000000000"
SET_UP = Step("Set up job", "success")
RUN_FAIL = Step("Run tests", "failure")
LABEL = "ci / unit"


def chk(bucket: Bucket, **kw) -> Check:
    return Check("unit", bucket, "ci", LINK, **kw)


FAIL, PASS, PENDING = chk(Bucket.FAIL), chk(Bucket.PASS), chk(Bucket.PENDING)


def job(head: str = NEW, steps: tuple = (SET_UP, RUN_FAIL), job_id: str = "77") -> Job:
    return Job(job_id, head, "unit", steps)


# ----- ci_triage: pure ----------------------------------------------------------


def test_constants_are_pinned() -> None:
    assert tri.RUNNER_STEPS == ("Set up job", "Complete job")
    assert tri.FAILED_STEPS == ("failure", "cancelled", "timed_out")
    assert ci.Bucket is tri.Bucket and ci.FAILING is tri.FAILING and ci.PASSING is tri.PASSING


@pytest.mark.parametrize(
    ("seen", "want"),
    [
        (Seen(Bucket.PASS, job()), K.GREEN),
        (Seen(Bucket.PASS, job(OTHER)), K.STALE),
        (Seen(Bucket.PASS, None), K.GREEN),
        (Seen(Bucket.SKIPPING, None), K.SKIPPED),
        (Seen(Bucket.PENDING, None), K.PENDING),
        (Seen(Bucket.FAIL, job()), K.OURS),
        (Seen(Bucket.FAIL, job(OTHER)), K.STALE),
        (Seen(Bucket.FAIL, job(steps=())), K.INFRA),
        (Seen(Bucket.CANCEL, job(steps=())), K.INFRA),
        (Seen(Bucket.CANCEL, job(steps=(SET_UP,))), K.INFRA),
        (Seen(Bucket.CANCEL, job(steps=(SET_UP, Step("Run", "cancelled")))), K.OURS),
        (Seen(Bucket.FAIL, None), K.OURS),
    ],
)
def test_kind_of(seen: Seen, want: K) -> None:
    assert tri.kind_of(seen, NEW) is want


def test_failing_step_is_the_first_failed_one() -> None:
    steps = (SET_UP, Step("a", "success"), Step("b", "timed_out"), Step("c", "failure"))
    assert tri.failing_step(job(steps=steps)) == "b"
    assert tri.failing_step(job(steps=(Step("x", "cancelled"),))) == "x"
    assert tri.failing_step(job(steps=(SET_UP,))) == ""
    assert tri.failing_step(None) == ""


def test_ran_ignores_skipped_empty_and_runner_steps() -> None:
    idle = (Step("Set up job", "success"), Step("a", ""), Step("b", "skipped"))
    assert tri.ran(job(steps=idle)) is False
    assert tri.ran(job(steps=(*idle, Step("Complete job", "failure")))) is False
    assert tri.ran(job(steps=(*idle, Step("c", "success")))) is True
    assert tri.ran(job(steps=())) is False


def test_job_from_reads_github_json() -> None:
    raw = {"id": 77, "head_sha": NEW, "name": "unit", "steps": [{"name": "a", "conclusion": None}]}
    got = tri.job_from(raw)
    assert got.id == "77" and got.head == NEW and got.name == "unit"
    assert got.steps == (Step("a", ""),)
    assert tri.job_from({"id": 1, "head_sha": "h"}).steps == ()


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ({"status": "in_progress"}, Bucket.PENDING),
        ({"status": "completed", "conclusion": "success"}, Bucket.PASS),
        ({"status": "completed", "conclusion": "neutral"}, Bucket.SKIPPING),
        ({"status": "completed", "conclusion": "skipped"}, Bucket.SKIPPING),
        ({"status": "completed", "conclusion": "cancelled"}, Bucket.CANCEL),
        ({"status": "completed", "conclusion": "failure"}, Bucket.FAIL),
        ({"status": "completed", "conclusion": "timed_out"}, Bucket.FAIL),
    ],
)
def test_bucket_of_run(raw: dict, want: Bucket) -> None:
    assert tri.bucket_of_run(raw) is want


def test_rerun_key_names_head_and_label() -> None:
    assert tri.rerun_key(NEW, LABEL) == f"{NEW} {LABEL}"


# ----- ci: verdicts, texts, cards ---------------------------------------------------


@pytest.mark.parametrize(
    ("kinds", "want"),
    [
        ([K.GREEN, K.OURS], CiVerdict.RED),
        ([K.INFRA, K.MAIN, K.PENDING], CiVerdict.INFRA),
        ([K.MAIN, K.PENDING, K.GREEN], CiVerdict.MAIN),
        ([K.PENDING, K.GREEN], CiVerdict.PENDING),
        ([K.STALE, K.GREEN], CiVerdict.PENDING),
        ([K.RERUN, K.GREEN], CiVerdict.PENDING),
        ([K.GREEN, K.SKIPPED], CiVerdict.GREEN),
        ([K.SKIPPED], CiVerdict.NONE),
    ],
)
def test_verdict_of_kinds(kinds: list[K], want: CiVerdict) -> None:
    assert ci.verdict_of([Check("c", Bucket.PASS, kind=k) for k in kinds]) is want


def test_untriaged_checks_keep_their_bucket_meaning() -> None:
    assert ci.verdict_of([Check("c", Bucket.FAIL)]) is CiVerdict.RED
    assert ci.verdict_of([Check("c", Bucket.CANCEL)]) is CiVerdict.RED
    assert ci.kind_or_bucket(Check("c", Bucket.FAIL)) is K.OURS
    assert ci.kind_or_bucket(Check("c", Bucket.FAIL, kind="main")) is K.MAIN


def test_overall_orders_infra_and_main_between_red_and_pending() -> None:
    V = CiVerdict

    def r(v: V) -> CiResult:
        return CiResult(1, "u", "h", v)

    assert ci.overall([r(V.MAIN), r(V.GREEN), r(V.INFRA)]) is V.INFRA
    assert ci.overall([r(V.PENDING), r(V.MAIN)]) is V.MAIN
    assert ci.overall([r(V.INFRA), r(V.RED)]) is V.RED


def test_check_round_trips_with_kind_step_and_head() -> None:
    c = Check("u", Bucket.FAIL, "ci", LINK, ["x"], kind=K.OURS, step="Run", head=NEW)
    again = CiResult(**json.loads(json.dumps(asdict(CiResult(1, "u", "h", CiVerdict.RED, [c])))))
    assert again.checks[0] == c and again.checks[0].kind is K.OURS


def test_check_lines_show_the_detail() -> None:
    def text(**kw) -> str:
        return ci.check_lines([CiResult(1, "u", "h", CiVerdict.RED, [chk(Bucket.FAIL, **kw)])])

    assert f"- {LABEL}: fail at step Run tests {LINK}" in text(kind=K.OURS, step="Run tests")
    assert "(no step ran)" in text(kind=K.INFRA)
    assert "(ran on another commit)" in text(kind=K.STALE)
    assert f"- {LABEL}: fail {LINK}" in text()


def test_ours_text_names_label_and_step() -> None:
    checks = [chk(Bucket.FAIL, kind=K.OURS, step="Run tests"), chk(Bucket.FAIL, kind=K.OURS)]
    checks += [Check("g", Bucket.PASS, kind=K.GREEN)]
    text = ci.ours_text([CiResult(1, "u", "h", CiVerdict.RED, checks)])
    assert text == f"{LABEL}, step Run tests; {LABEL}, step {ci.NO_STEP_NAMED}"


def test_mark_main_turns_matching_ours_checks_only() -> None:
    a = chk(Bucket.FAIL, kind=K.OURS, step="Run tests")
    b = Check("lint", Bucket.FAIL, kind=K.OURS, step="Run tests")
    c = chk(Bucket.FAIL, kind=K.OURS, step="")
    got = ci.mark_main([a, b, c], frozenset({("unit", "Run tests"), ("x", "")}))
    assert [g.kind for g in got] == [K.MAIN, K.OURS, K.OURS]


def test_rerun_due_lists_infra_checks_without_a_used_key() -> None:
    e = entry(1, ci=CiResult(1, "u", NEW, CiVerdict.INFRA, [chk(Bucket.FAIL, kind=K.INFRA)]))
    assert ci.rerun_due([e]) == [(e, e.ci.checks[0])]
    e.reran = [tri.rerun_key(NEW, LABEL)]
    assert ci.rerun_due([e]) == []
    e.reran = [tri.rerun_key(OTHER, LABEL)]
    assert len(ci.rerun_due([e])) == 1


def res(*checks: Check) -> CiResult:
    return CiResult(5, "https://h/5", NEW, CiVerdict.RED, list(checks))


@pytest.mark.parametrize(
    ("check", "state", "text"),
    [
        (
            chk(Bucket.FAIL, kind=K.OURS, step="Run tests"),
            CardState.FAILED,
            "CI failed: ci / unit, Run tests",
        ),
        (chk(Bucket.FAIL, kind=K.OURS), CardState.FAILED, "CI failed: ci / unit, step not named"),
        (chk(Bucket.FAIL, kind=K.INFRA), CardState.FAILED, "CI failed: ci / unit, no step ran"),
        (chk(Bucket.FAIL, kind=K.MAIN), CardState.MAIN, "CI blocked by main: ci / unit"),
        (chk(Bucket.FAIL, kind=K.RERUN), CardState.RERUN, "re-running ci / unit"),
        (chk(Bucket.PENDING, kind=K.PENDING), CardState.RUNNING, "CI running"),
        (chk(Bucket.PASS, kind=K.STALE), CardState.RUNNING, "CI running"),
        (chk(Bucket.PASS, kind=K.GREEN), CardState.GREEN, "CI green"),
    ],
)
def test_card_rows(check: Check, state: CardState, text: str) -> None:
    assert ci.card_of(res(check)) == Card(state, text)


def test_card_precedence_and_empty() -> None:
    ours, main = chk(Bucket.FAIL, kind=K.OURS, step="s"), chk(Bucket.FAIL, kind=K.MAIN)
    rerun, green = chk(Bucket.FAIL, kind=K.RERUN), chk(Bucket.PASS, kind=K.GREEN)
    assert ci.card_of(res(green, rerun, main, ours)).state is CardState.FAILED
    assert ci.card_of(res(green, rerun, main)).state is CardState.MAIN
    assert ci.card_of(res(green, rerun)).state is CardState.RERUN
    assert ci.card_of(res()) == ci.NO_CARD == Card(CardState.NONE, "no CI result")
    assert ci.card_of(res(chk(Bucket.SKIPPING))) == ci.NO_CARD
    assert Card(CardState.MAIN, "t").row() == {"state": "main", "text": "t"}


# ----- upstream: gh -----------------------------------------------------------------


class Exec:
    def __init__(self, results: dict[tuple, tuple[int, str]]):
        self.results, self.calls = results, []

    def __call__(self, argv: list[str], limit_s: float = 0.0) -> tuple[int, str]:
        self.calls.append(argv)
        return self.results.get(tuple(argv), (0, ""))


FIELDS = "name,state,bucket,link,workflow"
REQ = ("gh", "pr", "checks", "14", "--required", "--json", FIELDS)
ALL = ("gh", "pr", "checks", "14", "--json", FIELDS)
JOB_API = ("gh", "api", "repos/{owner}/{repo}/actions/jobs/77")
MAIN_API = ("gh", "api", "repos/{owner}/{repo}/commits/main/check-runs?per_page=100")
ROWS = json.dumps([{"name": "u", "bucket": "fail", "link": LINK, "workflow": "ci"}])


def test_checks_ask_for_required_ones_first() -> None:
    ex = Exec({REQ: (8, ROWS)})
    assert GhPrs(ex).checks(14) == [Check("u", Bucket.FAIL, "ci", LINK)]
    assert ex.calls == [list(REQ)]


def test_checks_fall_back_to_all_when_none_is_required() -> None:
    ex = Exec({REQ: (1, "No required checks reported on the 'b' branch"), ALL: (0, ROWS)})
    assert len(GhPrs(ex).checks(14)) == 1
    assert ex.calls == [list(REQ), list(ALL)]


def test_job_parses_the_jobs_json() -> None:
    body = {"id": 77, "head_sha": NEW, "name": "unit", "steps": [{"name": "a", "conclusion": None}]}
    ex = Exec({JOB_API: (0, json.dumps(body))})
    assert GhPrs(ex).job(LINK) == Job("77", NEW, "unit", (Step("a", ""),))
    assert ex.calls == [list(JOB_API)]


def test_job_without_an_id_makes_no_call() -> None:
    ex = Exec({})
    assert GhPrs(ex).job("https://example.com/x") is None
    assert ex.calls == []


def test_job_error_raises() -> None:
    with pytest.raises(UpstreamError):
        GhPrs(Exec({JOB_API: (1, "HTTP 404")})).job(LINK)


def test_main_checks_map_check_runs() -> None:
    runs = [
        {"name": "a", "status": "completed", "conclusion": "success", "details_url": LINK},
        {"name": "b", "status": "completed", "conclusion": "failure", "details_url": MAIN_LINK},
        {"name": "c", "status": "completed", "conclusion": "cancelled"},
        {"name": "d", "status": "completed", "conclusion": "skipped", "details_url": None},
        {"name": "e", "status": "in_progress", "conclusion": None, "details_url": "x"},
    ]
    got = GhPrs(Exec({MAIN_API: (0, json.dumps({"check_runs": runs}))})).main_checks("main")
    assert [(c.name, c.bucket, c.link) for c in got] == [
        ("a", Bucket.PASS, LINK),
        ("b", Bucket.FAIL, MAIN_LINK),
        ("c", Bucket.CANCEL, ""),
        ("d", Bucket.SKIPPING, ""),
        ("e", Bucket.PENDING, "x"),
    ]


def test_rerun_argv_and_errors() -> None:
    ex = Exec({})
    GhPrs(ex).rerun(LINK)
    assert ex.calls == [["gh", "run", "rerun", "--job", "77"]]
    with pytest.raises(UpstreamError):
        GhPrs(Exec({("gh", "run", "rerun", "--job", "77"): (1, "no")})).rerun(LINK)
    with pytest.raises(UpstreamError):
        GhPrs(Exec({})).rerun("https://example.com/x")


def test_no_prs_raises_for_the_new_calls() -> None:
    p = NoPrs()
    for call in (lambda: p.job(LINK), lambda: p.main_checks("main"), lambda: p.rerun(LINK)):
        with pytest.raises(UpstreamError):
            call()


# ----- CiWatch.rerun ----------------------------------------------------------------


@dataclass
class LinkPrs:
    """checks() answers per call; rerun records and may fail."""

    reads: list[list[Check]]
    calls: list[tuple] = field(default_factory=list)
    fail: bool = False

    def checks(self, number: int) -> list[Check]:
        self.calls.append(("checks", number))
        return self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]

    def rerun(self, link: str) -> None:
        self.calls.append(("rerun", link))
        if self.fail:
            raise UpstreamError("no")


def test_rerun_looks_until_the_link_changes(fake: FakeSystem) -> None:
    new = Check("unit", Bucket.PENDING, "ci", LINK + "9")
    prs = LinkPrs([[FAIL], [FAIL], [new]])
    CiWatch(prs, 60).rerun(14, FAIL)  # type: ignore[arg-type]
    assert prs.calls[0] == ("rerun", LINK)
    assert [c for c in prs.calls if c[0] == "checks"] == [("checks", 14)] * 3
    assert set(fake.slept) == {ci.CI_POLL_S}


def test_rerun_gives_up_after_the_looks(fake: FakeSystem) -> None:
    prs = LinkPrs([[FAIL]])
    CiWatch(prs, 60).rerun(14, FAIL)  # type: ignore[arg-type]
    assert sum(1 for c in prs.calls if c[0] == "checks") == ci.CI_LOOKS


def test_rerun_failure_raises(fake: FakeSystem) -> None:
    with pytest.raises(UpstreamError):
        CiWatch(LinkPrs([[FAIL]], fail=True), 60).rerun(14, FAIL)  # type: ignore[arg-type]


# ----- the boundary: classes, holds, tools --------------------------------------------


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def at_ci(env: Env, checks: list[Check], jobs: dict[str, Job] | None = None, **kw) -> bd.Boundary:
    env.prs.check_list = checks
    env.prs.jobs = {LINK: job()} if jobs is None else jobs
    env.prs.failed_log = lambda link: ""
    built = entry(1, pr=5, mode=PrMode.READY, url="https://h/5")
    env.rt.state.upstream.stack = [env.as_built(built)]
    return env.open(Edge.END, stage=Stage.CI, **kw)


def last(env: Env) -> dict:
    return env.events()[-1].data


def stack_entry(env: Env) -> bd.StackEntry:
    return env.rt.state.upstream.stack[0]


def add_story(env: Env, sid: str) -> None:
    env.rt.state.stories[sid] = StoryState(sid, "Bug", "design", status=StoryStatus.ACTIVE)


def main_broken(env: Env, step: str = "Run tests") -> bd.Boundary:
    b = at_ci(
        env, [FAIL], {LINK: job(), MAIN_LINK: job("m41n", (SET_UP, Step(step, "failure")), "88")}
    )
    env.prs.main_list = [Check("unit", Bucket.FAIL, "", MAIN_LINK)]
    env.drive()
    return b


def test_our_failure_holds_and_continue_is_refused(env: Env) -> None:
    b = at_ci(env, [FAIL])
    env.drive()
    assert b.hold is BoundaryHold.CI_FAILED and last(env)["ci"] == "red"
    seen = len(env.events())
    out = call(Tools(env.rt).continue_boundary({"note": "flaky"}))
    want = ci.CI_OURS_REFUSAL.format(sprint=1, failures=f"{LABEL}, step Run tests")
    assert out["status"] == "refused" and out["reason"] == want
    assert "Run tests" in out["reason"] and LABEL in out["reason"]
    assert b.hold is BoundaryHold.CI_FAILED and b.stage is Stage.CI
    assert len(env.events()) == seen


def test_the_refusal_says_to_request_or_route_a_fix() -> None:
    text = ci.CI_OURS_REFUSAL
    assert "request_story" in text and "record_ci_bug" in text and "flaky" in text


def test_a_green_rerun_on_the_pushed_head_is_done(env: Env) -> None:
    attempt2 = Check("unit", Bucket.PASS, "ci", LINK.replace("/1/", "/1/attempts/2/"))
    at_ci(
        env, [attempt2], {attempt2.link: Job("78", NEW, "unit", (SET_UP, Step("Run", "success")))}
    )
    [report] = env.drive()
    up = env.rt.state.upstream
    assert env.rt.state.boundary is None and last(env)["ci"] == "green"
    assert ci.READY_PHRASE in up.report
    assert handover.triggers(report) == [T.CI_GREEN]
    assert stack_entry(env).ci.verdict is CiVerdict.GREEN


def test_a_run_on_another_commit_is_ignored(env: Env) -> None:
    b = at_ci(env, [PASS], {LINK: job(OTHER, (SET_UP, Step("Run", "success")))})
    env.prs.wait_checks = lambda n, s: False
    env.drive()
    up = env.rt.state.upstream
    assert b.hold is BoundaryHold.CI_PENDING and last(env)["ci"] == "pending"
    assert ci.CI_STALE in last(env)["reason"]
    assert stack_entry(env).ci.checks[0].kind is K.STALE
    assert ci.READY_PHRASE not in up.report and "done" not in env.outcomes()


def test_main_broken_holds_with_the_target(env: Env) -> None:
    b = main_broken(env)
    assert b.hold is BoundaryHold.MAIN_BROKEN and env.rt.state.boundary is b
    assert last(env)["ci"] == "main" and last(env)["target"] == "main"
    assert stack_entry(env).ci.checks[0].kind is K.MAIN
    assert ("main_checks", "main") in env.prs.calls
    assert ci.card_of(stack_entry(env).ci).state is CardState.MAIN


def test_recording_the_bug_ends_blocked_by_main_and_the_next_sprint_starts(env: Env) -> None:
    main_broken(env)
    add_story(env, "s2")
    out = call(Tools(env.rt).record_ci_bug({"story": "s2"}))
    up = env.rt.state.upstream
    assert out == {"status": "recorded", "story": "s2"}
    assert env.rt.state.boundary is None and up.ci_bug == "s2"
    assert up.report.startswith("Sprint 1 ended, CI blocked by main")
    assert ci.READY_PHRASE not in up.report and last(env)["ci"] == "main"
    assert stack_entry(env).pr == 5 and stack_entry(env).ci.verdict is CiVerdict.MAIN
    started = call(Tools(env.rt).start_sprint({"goal": "g", "stories": ["s2"]}))
    assert started.get("status") != "refused" and up.ci_bug == ""


def test_the_same_job_on_another_step_is_still_ours(env: Env) -> None:
    b = main_broken(env, step="Lint")
    assert b.hold is BoundaryHold.CI_FAILED


def test_main_is_read_once_for_a_stack_of_two_prs(env: Env) -> None:
    at_ci(
        env, [FAIL], {LINK: job(), MAIN_LINK: job("m41n", (SET_UP, Step("Lint", "failure")), "88")}
    )
    env.prs.main_list = [Check("unit", Bucket.FAIL, "", MAIN_LINK)]
    env.rt.state.upstream.stack = [
        entry(1, pr=5, mode=PrMode.READY, url="https://h/5"),
        entry(2, pr=6, mode=PrMode.READY, url="https://h/6"),
    ]
    env.drive()
    assert [c for c in env.prs.calls if c[0] == "main_checks"] == [("main_checks", "main")]


def test_main_is_not_read_when_nothing_is_ours(env: Env) -> None:
    at_ci(env, [PASS], {LINK: job(steps=(SET_UP, Step("Run", "success")))})
    env.drive()
    assert not [c for c in env.prs.calls if c[0] == "main_checks"]


def infra_job(head: str = NEW) -> dict[str, Job]:
    return {LINK: job(head, ())}


def test_a_job_with_no_steps_is_rerun_once(env: Env) -> None:
    b = at_ci(env, [FAIL], infra_job())
    env.br.step()
    key = tri.rerun_key(NEW, LABEL)
    assert env.prs.calls.count(("rerun", LINK)) == 1
    assert stack_entry(env).reran == [key]
    assert b.hold is None and b.stage is Stage.CI and env.rt.state.boundary is b
    assert last(env)["outcome"] == "rerun" and last(env)["jobs"] == [LABEL]
    assert ci.card_of(stack_entry(env).ci).text == f"re-running {LABEL}"
    env.br.step()
    assert env.prs.calls.count(("rerun", LINK)) == 1
    assert b.hold is BoundaryHold.CI_INFRA and last(env)["ci"] == "infra"


def test_after_the_rerun_a_green_read_finishes(env: Env) -> None:
    b = at_ci(env, [FAIL], infra_job())
    env.drive()
    assert b.hold is BoundaryHold.CI_INFRA
    new = Check("unit", Bucket.PASS, "ci", LINK + "2")
    env.prs.check_list = [new]
    env.prs.jobs = {new.link: Job("78", NEW, "unit", (SET_UP, Step("Run", "success")))}
    call(Tools(env.rt).continue_boundary({"note": "re-ran"}))
    env.drive()
    assert env.rt.state.boundary is None and last(env)["ci"] == "green"


def test_a_new_head_gets_its_own_rerun(env: Env) -> None:
    at_ci(env, [FAIL], infra_job())
    env.br.step()
    stack_entry(env).head = OTHER
    env.prs.jobs = infra_job(OTHER)
    env.br.step()
    assert env.prs.calls.count(("rerun", LINK)) == 2
    assert stack_entry(env).reran == [tri.rerun_key(NEW, LABEL), tri.rerun_key(OTHER, LABEL)]


def test_rerun_failure_holds_as_error(env: Env) -> None:
    b = at_ci(env, [FAIL], infra_job())

    def boom(link: str) -> None:
        raise UpstreamError("gh broke")

    env.prs.rerun = boom  # type: ignore[method-assign]
    env.drive()
    assert b.hold is BoundaryHold.ERROR
    assert stack_entry(env).reran == [tri.rerun_key(NEW, LABEL)]


def test_continue_at_pending_rereads_and_stays_held(env: Env) -> None:
    b = at_ci(env, [PENDING], {LINK: job(steps=())})
    env.prs.wait_checks = lambda n, s: False
    env.drive()
    assert b.hold is BoundaryHold.CI_PENDING
    call(Tools(env.rt).continue_boundary({"note": "green on GitHub"}))
    env.drive()
    assert b.hold is BoundaryHold.CI_PENDING and ci.READY_PHRASE not in env.rt.state.upstream.report


def hold_failed(env: Env) -> None:
    at_ci(env, [FAIL])
    env.drive()


def hold_infra(env: Env) -> None:
    at_ci(env, [FAIL], infra_job())
    stack_entry(env).reran = [tri.rerun_key(NEW, LABEL)]
    env.drive()


@pytest.mark.parametrize(
    ("setup", "verdict"),
    [(hold_failed, "red"), (hold_infra, "infra"), (main_broken, "main")],
)
def test_record_ci_bug_never_finishes_green(env: Env, setup, verdict: str) -> None:
    setup(env)
    add_story(env, "s2")
    assert call(Tools(env.rt).record_ci_bug({"story": "s2"}))["status"] == "recorded"
    assert last(env)["ci"] == verdict
    assert ci.READY_PHRASE not in env.rt.state.upstream.report
    assert env.rt.state.upstream.ci_bug == "s2" and env.rt.state.boundary is None


def test_record_ci_bug_is_refused_at_ci_pending(env: Env) -> None:
    at_ci(env, [PENDING], {})
    env.prs.wait_checks = lambda n, s: False
    env.drive()
    add_story(env, "s2")
    out = call(Tools(env.rt).record_ci_bug({"story": "s2"}))
    assert out["reason"] == NO_CI_HOLD
    assert "ci_infra" in NO_CI_HOLD and "main_broken" in NO_CI_HOLD


def test_the_bug_holds_are_the_three_ci_holds() -> None:
    assert {
        BoundaryHold.CI_FAILED,
        BoundaryHold.CI_INFRA,
        BoundaryHold.MAIN_BROKEN,
    } == bd.CI_BUG_HOLDS


# ----- legacy state ---------------------------------------------------------------------


def test_a_legacy_entry_without_kinds_or_reran_loads() -> None:
    from agile_team import state

    st = state.RunState()
    st.upstream.stack = [entry(1, pr=5)]
    data = json.loads(st.to_json())
    data["upstream"]["stack"][0].pop("reran", None)
    old = {
        "pr": 5,
        "url": "u",
        "head": "h",
        "verdict": "red",
        "checks": [{"name": "u", "bucket": "fail", "workflow": "ci", "link": "", "lines": []}],
    }
    data["upstream"]["stack"][0]["ci"] = old
    loaded = state.RunState.from_json(json.dumps(data)).upstream.stack[0]
    assert loaded.reran == [] and loaded.ci.checks[0].kind is None
    assert ci.verdict_of(loaded.ci.checks) is CiVerdict.RED


# ----- hand-overs and hints ---------------------------------------------------------------


def brep(hold: str, **fields) -> dict:
    base = {"edge": "end", "sprint": 2, "stage": "ci", "hold": hold}
    return {"role": "runner", "status": "boundary", "boundary": {**base, **fields}}


@pytest.mark.parametrize(
    ("hold", "trigger", "words"),
    [
        ("ci_failed", T.CI_FAILED, ["continue_boundary is refused", "request_story", "NOT ready"]),
        ("ci_infra", T.CI_INFRA, ["never ran a step", "NOT ready", "record_ci_bug"]),
        (
            "main_broken",
            T.MAIN_BROKEN,
            ["main is broken", "main", "CI blocked by main", "NOT done"],
        ),
    ],
)
def test_ci_class_hand_over_lines(hold: str, trigger: T, words: list[str]) -> None:
    report = brep(hold, ci="x", prs="#14 u", checks="- ci / unit: fail", target="main")
    assert handover.triggers(report) == [trigger]
    [line] = handover.report_lines(report, None)
    assert "- ci / unit: fail" in line and "#14 u" in line and ci.READY_PHRASE not in line
    assert all(w in line for w in words)
    assert "{" not in line


def test_stall_hints_name_the_new_holds() -> None:
    assert "record_ci_bug" in bd.stall_hint(BoundaryHold.MAIN_BROKEN)
    assert "record_ci_bug" in bd.stall_hint(BoundaryHold.CI_INFRA)
    assert bd.stall_hint(BoundaryHold.CI_INFRA) != bd.stall_hint(BoundaryHold.MAIN_BROKEN)


# ----- the board --------------------------------------------------------------------------


def test_snapshot_stack_rows_carry_the_card() -> None:
    green = CiResult(5, "u", NEW, CiVerdict.GREEN, [chk(Bucket.PASS, kind=K.GREEN)])
    assert snapshot._stack_entry(entry(1, ci=green))["ci"] == {"state": "green", "text": "CI green"}
    assert snapshot._stack_entry(entry(1))["ci"] is None


def page() -> str:
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_index_renders_the_ci_pill() -> None:
    text = page()
    assert "const CI_TONE" in text
    for state, tone in [
        ("green", "good"),
        ("failed", "critical"),
        ("main", "warning"),
        ("rerun", "accent"),
    ]:
        assert f'{state}: "{tone}"' in text
    assert "pill(e.ci.text" in text and "CI_TONE[e.ci.state]" in text


def test_fixture_stack_has_ci_cards() -> None:
    stack = json.loads(FIXTURE_TEXT)["upstream"]["stack"]
    assert stack[0]["ci"] == {"state": "green", "text": "CI green"}
    assert stack[1]["ci"] == {
        "state": "main",
        "text": "CI blocked by main: ci / test (macos-latest)",
    }
