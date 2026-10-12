"""s11: test disputes (T1-T9, T13) and rulings at any step (T10, T11)."""

import asyncio
import functools

import pytest
from agile_team import fingerprint, gates, roles, system
from agile_team.config import PIPELINE_STEPS
from agile_team.dispatch import StepRequest
from agile_team.events import Event, EventKind
from agile_team.gates import DisputeStage, OpenDispute, StoryState, StoryStatus, Verdict
from agile_team.insights import disputes_since_review
from agile_team.roles import Dispute, Handoff, HandoffError, handoff_report
from agile_team.state import RunState

from .conftest import FakeQuery, FakeRunner, handoff
from .pipeline_helpers import Script, add_story, build, drive, handover_events, step_roles

STEPS = list(PIPELINE_STEPS)
TEST_ID = "tests/test_x.py::test_a"
LS = "git ls-files -- tests/test_x.py '*/tests/test_x.py'"
FILE = "agile-team/runner/tests/test_x.py"
OLD = "def test_a():\n    assert f(1) == 1\n"
NEW = "def test_a():\n    assert f(1) == 2\n"
BASE = fingerprint.of(FILE, OLD)
UNCHANGED = (
    f"the disputed test file {FILE} has not changed since the dispute was raised: "
    f"{TEST_ID} still matches its baseline {BASE[:12]} (whitespace and comment edits "
    "do not count); fix the test, or confirm it with changes_requested and "
    "next_role architect"
)
UNTRACKED = (
    f"dispute rejected: tests/test_x.py (from {TEST_ID}) is not a tracked file at the "
    "repo root, and no single tracked file ends with that path; hand off the dispute "
    "again with the test's path from the repo root"
)
DISPUTE_JSON = {"test": TEST_ID, "rule": "W6", "reason": "rule says X, test expects Y"}


def story(step: str = "implement", **kw) -> StoryState:
    kw.setdefault("sprint", 1)
    return StoryState("s1", "Add todo", step, **kw)


def open_dispute(**kw) -> OpenDispute:
    kw.setdefault("output", gates.TEST_GREEN.format(test=TEST_ID))
    return OpenDispute(TEST_ID, "W6", "why", FILE, BASE, **kw)


def pipeline(results=None, steps=STEPS, cap=3, files=None) -> gates.Pipeline:
    """A pipeline whose runner is scripted and whose working tree is ``files``."""
    files = {FILE: OLD} if files is None else files
    runner = FakeRunner({LS: (0, FILE + "\n"), **(results or {})})
    checks = gates.Checks({"test": "T", "coverage": "C"}, 95.0, runner, read=files.get)
    return gates.Pipeline(list(steps), cap, checks)


def raised(**kw) -> Handoff:
    d = Dispute(TEST_ID, "W6", "why")
    return Handoff("changes_requested", summary="s", dispute=d, **kw)


# ----- T1/T2: the handoff -----------------------------------------------------


def parse(**dispute_or_extra) -> Handoff:
    return roles.parse_handoff(handoff("changes_requested", **dispute_or_extra))


def test_a_full_dispute_parses() -> None:
    h = parse(summary="s", dispute=DISPUTE_JSON)
    assert h.dispute == Dispute(TEST_ID, "W6", "rule says X, test expects Y")


def test_dispute_defaults_to_none_and_reason_to_empty() -> None:
    assert Handoff("done").dispute is None
    assert Dispute("t", "r").reason == ""


def test_a_missing_reason_falls_back_to_the_summary() -> None:
    h = parse(summary="the summary", dispute={"test": TEST_ID, "rule": "W6"})
    assert h.dispute == Dispute(TEST_ID, "W6", "the summary")


BAD_FORM = "handoff dispute needs a test id and a design rule"


@pytest.mark.parametrize(
    "dispute",
    [
        {"rule": "W6"},
        {"test": TEST_ID},
        {"test": TEST_ID, "rule": ""},
        {"test": "", "rule": "W6"},
        {"test": 3, "rule": "W6"},
        "W6",
        ["a", "b"],
        {"test": TEST_ID, "rule": "W6", "reason": 3},
    ],
)
def test_a_malformed_dispute_is_a_bad_handoff(dispute) -> None:
    with pytest.raises(HandoffError, match=BAD_FORM):
        parse(summary="s", dispute=dispute)


@pytest.mark.parametrize("status", ["done", "blocked", "failed"])
def test_a_dispute_needs_changes_requested(status) -> None:
    text = handoff(status, dispute=DISPUTE_JSON)
    with pytest.raises(HandoffError, match="handoff dispute needs status changes_requested"):
        roles.parse_handoff(text)


def test_the_step_end_report_shape_ignores_the_dispute() -> None:
    plain = Handoff("changes_requested", summary="s")
    assert handoff_report(raised()) == handoff_report(plain)


# ----- gates: types, Checks ---------------------------------------------------


def test_verdict_dispute_value() -> None:
    assert Verdict.DISPUTE == "dispute"


def test_open_dispute_defaults_and_coerces() -> None:
    d = OpenDispute(TEST_ID, "W6", "why")
    assert (d.file, d.baseline, d.stage) == ("", "", DisputeStage.RAISED)
    loaded = OpenDispute(TEST_ID, "W6", "why", FILE, BASE, stage="confirmed")
    assert loaded.stage is DisputeStage.CONFIRMED and loaded.file == FILE
    assert [s.value for s in DisputeStage] == ["raised", "confirmed"]


def test_story_and_outcome_default_to_no_dispute() -> None:
    s = story()
    assert (s.dispute, s.disputes) == (None, 0)
    assert gates.Outcome(Verdict.PASS).dispute is None


def checks_with(files, results=None) -> gates.Checks:
    return gates.Checks({}, 95.0, FakeRunner(results), read=files.get)


def test_a_real_change_settles_the_dispute() -> None:
    out = checks_with({FILE: NEW}).dispute_settled(open_dispute())
    assert (out.verdict, out.reason) == (Verdict.PASS, "disputed test changed")


@pytest.mark.parametrize(
    "text",
    [OLD, "# note\n" + OLD, OLD.replace("    ", "        ") + "\n\n", OLD.replace("==", "  ==  ")],
)
def test_no_change_or_a_cosmetic_change_bounces_with_the_reason(text) -> None:
    out = checks_with({FILE: text}).dispute_settled(open_dispute())
    assert (out.verdict, out.bounce_to, out.reason) == (Verdict.BOUNCE, "tests", UNCHANGED)


def test_a_vanished_file_counts_as_changed() -> None:
    out = checks_with({}).dispute_settled(open_dispute())
    assert (out.verdict, out.reason) == (Verdict.PASS, "disputed test changed")


def test_dispute_settled_when_confirmed_without_reading() -> None:
    reads = []
    checks = gates.Checks({}, 95.0, FakeRunner(), read=lambda p: reads.append(p))
    out = checks.dispute_settled(open_dispute(stage="confirmed"))
    assert (out.verdict, out.reason) == (Verdict.PASS, "dispute confirmed")
    assert reads == []


def test_a_legacy_dispute_passes_without_reading() -> None:
    reads = []
    checks = gates.Checks({}, 95.0, FakeRunner(), read=lambda p: reads.append(p))
    out = checks.dispute_settled(OpenDispute(TEST_ID, "W6", "why"))
    assert (out.verdict, out.reason) == (Verdict.PASS, gates.LEGACY_PASS)
    assert gates.LEGACY_PASS == "dispute raised before content baselines; passed without a check"
    assert reads == []


def test_the_gate_runs_no_command() -> None:
    runner = FakeRunner()
    gates.Checks({}, 95.0, runner, read={FILE: NEW}.get).dispute_settled(open_dispute())
    assert runner.calls == []


def test_the_default_reader_reads_nothing() -> None:
    assert gates.Checks({}, 95.0, FakeRunner()).content_hash(FILE) is None


def test_content_hash_is_the_fingerprint() -> None:
    assert checks_with({FILE: OLD}).content_hash(FILE) == BASE


# ----- F1: resolving the path -------------------------------------------------


def test_pick_tracked_prefers_an_exact_line() -> None:
    assert gates.pick_tracked("tests/a.py", "x/tests/a.py\ntests/a.py\n") == "tests/a.py"


def test_pick_tracked_takes_a_single_suffix_match() -> None:
    assert gates.pick_tracked("tests/a.py", "x/y/tests/a.py\nother.py\n") == "x/y/tests/a.py"


@pytest.mark.parametrize("listing", ["", "other.py\n", "a/tests/a.py\nb/tests/a.py\n"])
def test_pick_tracked_gives_none_for_zero_or_several(listing) -> None:
    assert gates.pick_tracked("tests/a.py", listing) is None


def test_pick_tracked_needs_a_whole_path_component() -> None:
    assert gates.pick_tracked("s/a.py", "x/tests/a.py\n") is None
    assert gates.pick_tracked("s/a.py", "x/s/a.py\n") == "x/s/a.py"


def test_tracked_runs_a_quoted_ls_files() -> None:
    runner = FakeRunner(
        {"git ls-files -- 'tests/my test.py' '*/tests/my test.py'": (0, "a/tests/my test.py\n")}
    )
    assert gates.Checks({}, 95.0, runner).tracked("tests/my test.py") == "a/tests/my test.py"
    assert len(runner.calls) == 1


def test_tracked_is_none_on_a_failed_command() -> None:
    runner = FakeRunner({"git ls-files -- a.py '*/a.py'": (128, "a.py\n")})
    assert gates.Checks({}, 95.0, runner).tracked("a.py") is None


def test_test_file_is_the_id_up_to_the_first_separator() -> None:
    assert gates.test_file("tests/t.py::C::m[a::b]") == "tests/t.py"
    assert gates.test_file("tests/t.py") == "tests/t.py"


def test_read_repo_file(scratch) -> None:
    system.make_dirs(scratch / "d")
    system.write_text(scratch / "d" / "t.py", "x = 1\n")
    assert gates.read_repo_file(scratch, "d/t.py") == "x = 1\n"
    assert gates.read_repo_file(scratch, "d") is None
    assert gates.read_repo_file(scratch, "gone.py") is None


def test_load_dispute_drops_the_legacy_base() -> None:
    d = gates.load_dispute(test="t::a", rule="W6", reason="r", base="abc", stage="confirmed")
    assert (d.file, d.baseline, d.stage) == ("", "", DisputeStage.CONFIRMED)


# ----- AC2: the baseline is the content at the raise ---------------------------


def test_a_change_after_the_raise_passes_the_gate() -> None:
    files = {FILE: OLD}
    s, p = story(), pipeline(files=files)
    p.advance(s, p.evaluate(s, raised()))
    files[FILE] = NEW
    s.step = "tests"
    assert p.evaluate(s, Handoff("done")).verdict is Verdict.PASS


def test_content_already_changed_at_the_raise_is_the_baseline() -> None:
    files = {FILE: NEW}
    s, p = story(), pipeline(files=files)
    p.advance(s, p.evaluate(s, raised()))
    out = p.evaluate(s, Handoff("done"))
    assert out.verdict is Verdict.BOUNCE and NEW != OLD
    assert fingerprint.of(FILE, NEW)[:12] in out.reason


# ----- T3: raising ------------------------------------------------------------


def test_a_dispute_at_implement_moves_to_tests_without_running_gates() -> None:
    p = pipeline()
    out = p.evaluate(story(), raised())
    assert (out.verdict, out.bounce_to) == (Verdict.DISPUTE, "tests")
    assert out.reason == f"{TEST_ID} contradicts W6: why"
    assert out.dispute == open_dispute()
    assert p.checks.run.calls[0] == LS and len(p.checks.run.calls) == 2


def test_the_raised_dispute_stores_the_resolved_file_and_baseline() -> None:
    d = pipeline().evaluate(story(), raised()).dispute
    assert (d.file, d.baseline) == (FILE, fingerprint.of(FILE, OLD))
    assert d.file != "tests/test_x.py"


@pytest.mark.parametrize(
    "results,files",
    [
        ({LS: (0, "")}, {FILE: OLD}),
        ({LS: (0, "a/tests/test_x.py\nb/tests/test_x.py\n")}, {FILE: OLD}),
        ({LS: (1, FILE)}, {FILE: OLD}),
        ({}, {}),
    ],
)
def test_an_unresolvable_dispute_is_rejected_as_a_round(results, files) -> None:
    s, p = story(disputes=2), pipeline(results, files=files)
    out = p.evaluate(s, raised())
    assert (out.verdict, out.bounce_to, out.reason) == (Verdict.BOUNCE, "implement", UNTRACKED)
    assert out.author is gates.Author.ROLE and out.dispute is None
    p.advance(s, out)
    assert (s.step, s.rounds, s.dispute, s.disputes) == ("implement", 1, None, 2)


def test_a_stopped_handoff_beats_the_dispute() -> None:
    h = Handoff("blocked", summary="stuck", dispute=Dispute(TEST_ID, "W6", "why"))
    assert pipeline().evaluate(story(), h).verdict is Verdict.HOLD


def test_a_dispute_elsewhere_is_ignored() -> None:
    out = pipeline().evaluate(story("review"), raised())
    assert (out.verdict, out.bounce_to) == (Verdict.BOUNCE, "implement")
    assert out.dispute is None


def test_a_dispute_with_tests_disabled_is_gated_as_today() -> None:
    p = pipeline({"C": (1, "boom")}, steps=["implement", "review"])
    out = p.evaluate(story(), raised())
    assert out.verdict is Verdict.BOUNCE and "boom" in out.reason
    assert LS not in p.checks.run.calls


# ----- T4: the move and the free-dispute cap ----------------------------------


def test_a_dispute_moves_to_tests_and_stores_it() -> None:
    s, p = story(), pipeline()
    p.advance(s, p.evaluate(s, raised()))
    assert (s.step, s.rounds, s.disputes, s.status) == ("tests", 0, 1, StoryStatus.ACTIVE)
    assert s.dispute == open_dispute()


def test_the_first_cap_disputes_are_free_and_the_next_counts() -> None:
    p, s = pipeline(cap=3), story()
    for expected_rounds in (0, 0, 0, 1):
        s.step = "implement"
        p.advance(s, gates.Outcome(Verdict.DISPUTE, "r", "tests", open_dispute()))
        assert (s.step, s.rounds) == ("tests", expected_rounds)
    assert s.disputes == 4 and s.status is StoryStatus.ACTIVE


def test_a_counted_dispute_can_cap_the_story() -> None:
    s, p = story(rounds=2, disputes=3), pipeline(cap=3)
    p.advance(s, gates.Outcome(Verdict.DISPUTE, "r", "tests", open_dispute()))
    assert (s.rounds, s.status, s.step) == (3, StoryStatus.NEEDS_MANAGER, "tests")


# ----- T6/T7/T8: the tests gate while a dispute is open -----------------------


def test_done_with_a_changed_test_passes_to_implement_and_closes() -> None:
    s, p = story("tests", dispute=open_dispute(), disputes=1), pipeline(files={FILE: NEW})
    out = p.evaluate(s, Handoff("done"))
    assert out.verdict is Verdict.PASS and out.reason == "disputed test changed"
    p.advance(s, out)
    assert (s.step, s.dispute, s.rounds) == ("implement", None, 0)


def test_done_with_an_unchanged_test_bounces_and_counts() -> None:
    s, p = story("tests", dispute=open_dispute()), pipeline()
    out = p.evaluate(s, Handoff("done"))
    assert (out.verdict, out.bounce_to, out.reason) == (Verdict.BOUNCE, "tests", UNCHANGED)
    p.advance(s, out)
    assert (s.step, s.rounds, s.dispute.stage) == ("tests", 1, DisputeStage.RAISED)


def test_tests_red_is_not_called_while_a_dispute_is_open() -> None:
    s, p = story("tests", dispute=open_dispute()), pipeline(files={FILE: NEW})
    p.evaluate(s, Handoff("done"))
    assert "T" not in p.checks.run.calls


def test_tests_red_still_gates_without_a_dispute() -> None:
    p = pipeline({"T": (0, "")})
    assert p.evaluate(story("tests"), Handoff("done")).verdict is Verdict.BOUNCE


def test_done_on_a_confirmed_dispute_passes_without_a_check() -> None:
    s, p = story("tests", dispute=open_dispute(stage="confirmed")), pipeline(files={})
    out = p.evaluate(s, Handoff("done"))
    assert (out.verdict, out.reason) == (Verdict.PASS, "dispute confirmed")
    assert p.checks.run.calls == []
    p.advance(s, out)
    assert (s.step, s.dispute) == ("implement", None)


def test_confirming_goes_to_the_architect_and_counts_a_round() -> None:
    s, p = story("tests", dispute=open_dispute(), disputes=1), pipeline()
    out = p.evaluate(s, Handoff("changes_requested", summary="rule holds", next_role="architect"))
    assert (out.verdict, out.bounce_to) == (Verdict.BOUNCE, "design")
    p.advance(s, out)
    assert (s.step, s.rounds, s.dispute.stage) == ("design", 1, DisputeStage.CONFIRMED)


def test_a_tester_bounce_to_implement_clears_the_dispute() -> None:
    s, p = story("tests", dispute=open_dispute()), pipeline()
    p.advance(s, gates.Outcome(Verdict.BOUNCE, "x", "implement"))
    assert (s.step, s.dispute, s.rounds) == ("implement", None, 1)


def test_a_bounce_that_stays_at_tests_does_not_confirm() -> None:
    s, p = story("tests", dispute=open_dispute()), pipeline()
    p.advance(s, gates.Outcome(Verdict.BOUNCE, "x", "tests"))
    assert s.dispute.stage is DisputeStage.RAISED


def test_passing_a_step_other_than_tests_leaves_the_dispute_alone() -> None:
    s, p = story("design", dispute=open_dispute(stage="confirmed")), pipeline()
    p.advance(s, gates.Outcome(Verdict.PASS))
    assert (s.step, s.dispute.stage) == ("tests", DisputeStage.CONFIRMED)


def test_the_architect_ruling_returns_to_tests_still_confirmed() -> None:
    s, p = story("design", dispute=open_dispute(stage="confirmed")), pipeline()
    out = p.evaluate(s, Handoff("done"))
    p.advance(s, out)
    assert s.step == "tests" and s.dispute.stage is DisputeStage.CONFIRMED


# ----- T8/T10: rulings --------------------------------------------------------


def test_a_ruling_resets_the_dispute_and_its_count() -> None:
    s = story("implement", rounds=3, disputes=4, dispute=open_dispute())
    s.status = StoryStatus.NEEDS_MANAGER
    pipeline().apply_ruling(s, "revise_design")
    assert (s.rounds, s.disputes, s.dispute, s.step) == (0, 0, None, "design")


def test_ruling_refusals() -> None:
    assert gates.ruling_refusal(None) == "a ruling needs a story; run the manager on that story"
    done = story(status=StoryStatus.DONE)
    assert gates.ruling_refusal(done) == "story s1 is done; a ruling cannot move it"


@pytest.mark.parametrize(
    "status", [StoryStatus.ACTIVE, StoryStatus.NEEDS_MANAGER, StoryStatus.BLOCKED]
)
def test_other_statuses_may_be_ruled_on(status) -> None:
    assert gates.ruling_refusal(story(status=status)) is None


# ----- state ------------------------------------------------------------------


def test_an_open_dispute_round_trips_through_state_json() -> None:
    st = RunState(sprint=1)
    st.stories["s1"] = story(dispute=open_dispute(stage="confirmed"), disputes=2)
    st.stories["s2"] = story("design")
    back = RunState.from_json(st.to_json())
    assert back.stories["s1"].dispute == open_dispute(stage="confirmed")
    assert back.stories["s1"].dispute.stage is DisputeStage.CONFIRMED
    assert back.stories["s1"].disputes == 2
    assert back.stories["s2"].dispute is None and back.stories["s2"].disputes == 0


def test_a_dispute_from_before_s30_loads_with_no_baseline() -> None:
    old = (
        '{"stories": {"s1": {"id": "s1", "title": "t", "step": "tests", "dispute": '
        '{"test": "t.py::a", "rule": "W6", "reason": "r", "base": "abc", "stage": "raised"}}}}'
    )
    d = RunState.from_json(old).stories["s1"].dispute
    assert (d.test, d.file, d.baseline, d.stage) == ("t.py::a", "", "", DisputeStage.RAISED)


def test_older_state_files_load_without_a_dispute() -> None:
    old = '{"stories": {"s1": {"id": "s1", "title": "t", "step": "design", "rounds": 1}}}'
    s = RunState.from_json(old).stories["s1"]
    assert (s.dispute, s.disputes, s.rounds) == (None, 0, 1)


# ----- T13: insights ----------------------------------------------------------


def dispute_event(story_id="s1", role="developer", test="t::a", rule="W6", rounds=0) -> Event:
    data = {"test": test, "rule": rule, "rounds": rounds, "disputes": 1}
    return Event(EventKind.TEST_DISPUTE, role, story_id, data)


def test_event_kind_value() -> None:
    assert EventKind.TEST_DISPUTE == "test-dispute"


def test_disputes_since_review_lists_only_events_after_the_manager() -> None:
    manager_end = Event(EventKind.STEP_END, "manager", None, {})
    events = [
        dispute_event(test="old::x"),
        manager_end,
        dispute_event("s2", "developer-cli", "t::b", "W7", 2),
        Event(EventKind.GATE, "developer", "s1", {}),
    ]
    assert disputes_since_review(events) == [
        {"story": "s2", "role": "developer-cli", "test": "t::b", "rule": "W7", "rounds": 2}
    ]


def test_disputes_since_review_without_a_manager_step_lists_all() -> None:
    assert len(disputes_since_review([dispute_event(), dispute_event()])) == 2
    assert disputes_since_review([]) == []


# ----- dispatch: T5, T9, T10, T11 ---------------------------------------------


def run(rt, role, story_id="s1", brief="go"):
    return asyncio.run(rt.run_role(StepRequest(role, brief, story_id)))


def open_story(rt, step="implement", **kw) -> StoryState:
    kw.setdefault("sprint", 1)
    rt.state.stories["s1"] = StoryState("s1", "Add todo", step, **kw)
    return rt.state.stories["s1"]


RESULTS = {LS: (0, FILE + "\n"), "pytest --cov": (0, "TOTAL 96%")}


@pytest.fixture(autouse=True)
def tracked(configured, fake) -> None:
    """Model the working tree so commits and reverts follow the files."""
    fake.track()


def write_test_file(rt, text=OLD) -> None:
    path = rt.config.repo / FILE
    system.make_dirs(path.parent)
    system.write_text(path, text)
    # Committed: the developer step quarantines and reverts out-of-scope changes.
    rt.git.commit([FILE], "test file")


def dispute_runtime(make_runtime, **kw):
    text = handoff("changes_requested", summary="why", dispute=DISPUTE_JSON)
    rt = make_runtime(FakeQuery(text), runner=FakeRunner(dict(RESULTS)), **kw)
    write_test_file(rt)
    open_story(rt)
    return rt


def events_of(rt, kind):
    return [e for e in rt.events.events() if e.kind == kind]


def test_a_developer_dispute_logs_one_dispute_event_and_no_gate(make_runtime) -> None:
    rt = dispute_runtime(make_runtime)
    report = run(rt, "developer")
    [event] = events_of(rt, "test-dispute")
    assert events_of(rt, "gate") == []
    assert (event.role, event.story) == ("developer", "s1")
    assert event.data == {
        "step": "implement",
        "verdict": "dispute",
        "reason": f"{TEST_ID} contradicts W6: rule says X, test expects Y",
        "now_at": "tests",
        "story_status": "active",
        "rounds": 0,
        "test": TEST_ID,
        "rule": "W6",
        "disputes": 1,
    }
    assert report["gate"] == event.data
    s = rt.state.stories["s1"]
    assert (s.step, s.rounds, s.disputes) == ("tests", 0, 1)
    assert s.dispute == OpenDispute(
        TEST_ID,
        "W6",
        "rule says X, test expects Y",
        FILE,
        BASE,
        output=gates.TEST_GREEN.format(test=TEST_ID),
    )


def test_a_dispute_does_not_run_the_implement_gate(make_runtime) -> None:
    rt = dispute_runtime(make_runtime)
    run(rt, "developer")
    assert rt.pipeline.checks.run.calls[0] == LS and len(rt.pipeline.checks.run.calls) == 2


def test_a_normal_gate_still_logs_a_gate_event(make_runtime) -> None:
    rt = make_runtime(FakeQuery(), runner=FakeRunner(dict(RESULTS)))
    open_story(rt)
    run(rt, "developer")
    assert len(events_of(rt, "gate")) == 1 and events_of(rt, "test-dispute") == []


def test_the_dispute_reaches_the_tester_then_the_architect_then_goes_away(make_runtime) -> None:
    rt = dispute_runtime(make_runtime)
    run(rt, "developer")
    raised_line = f"Test dispute (raised): {TEST_ID} contradicts W6: rule says X, test expects Y"
    rt.query_fn.text = handoff("changes_requested", summary="rule holds", next_role="architect")
    run(rt, "unit-tester")
    assert raised_line in rt.query_fn.calls[1]["prompt"]
    assert rt.state.stories["s1"].step == "design"
    rt.query_fn.text = handoff("done", summary="rule stands")
    run(rt, "architect")
    confirmed_line = raised_line.replace("(raised)", "(confirmed)")
    assert confirmed_line in rt.query_fn.calls[2]["prompt"]
    run(rt, "unit-tester")
    assert confirmed_line in rt.query_fn.calls[3]["prompt"]
    assert rt.state.stories["s1"].step == "implement"
    run(rt, "developer")
    assert "Test dispute" not in rt.query_fn.calls[4]["prompt"]


def test_the_dispute_line_follows_the_story_line(make_runtime) -> None:
    rt = dispute_runtime(make_runtime)
    run(rt, "developer")
    run(rt, "unit-tester")
    prompt = rt.query_fn.calls[1]["prompt"]
    assert prompt.index("Story s1: Add todo") < prompt.index("Test dispute (raised)")


def test_a_story_without_a_dispute_has_no_dispute_line(make_runtime) -> None:
    rt = make_runtime(FakeQuery(), runner=FakeRunner(dict(RESULTS)))
    open_story(rt)
    run(rt, "developer")
    assert "Test dispute" not in rt.query_fn.calls[0]["prompt"]


def ruling_runtime(make_runtime, step="review", **kw):
    rt = make_runtime(FakeQuery(handoff("done", ruling="revise_design")))
    open_story(rt, step, **kw)
    return rt


def test_a_ruling_applies_at_any_step_on_an_active_story(make_runtime) -> None:
    rt = ruling_runtime(make_runtime, rounds=2, disputes=2, dispute=open_dispute())
    report = run(rt, "manager")
    s = rt.state.stories["s1"]
    assert (s.step, s.rounds, s.disputes, s.dispute) == ("design", 0, 0, None)
    assert report["ruling"] == {"ruling": "revise_design", "applied": True, "now_at": "design"}
    [event] = events_of(rt, "ruling")
    assert event.data == {"ruling": "revise_design", "reason": "", "now_at": "design"}


def test_a_ruling_on_a_capped_story_behaves_as_before(make_runtime) -> None:
    rt = ruling_runtime(make_runtime, "implement", rounds=3, status=StoryStatus.NEEDS_MANAGER)
    report = run(rt, "manager")
    s = rt.state.stories["s1"]
    assert (s.step, s.status, s.rounds) == ("design", StoryStatus.ACTIVE, 0)
    assert report["ruling"]["applied"] is True


def test_a_ruling_applies_to_a_blocked_story(make_runtime) -> None:
    rt = ruling_runtime(make_runtime, status=StoryStatus.BLOCKED)
    assert run(rt, "manager")["ruling"]["applied"] is True
    assert rt.state.stories["s1"].status is StoryStatus.ACTIVE


def test_a_ruling_on_a_done_story_is_refused_in_the_report(make_runtime) -> None:
    rt = ruling_runtime(make_runtime, status=StoryStatus.DONE)
    report = run(rt, "manager")
    assert report["ruling"] == {
        "ruling": "revise_design",
        "applied": False,
        "why": "story s1 is done; a ruling cannot move it",
    }
    s = rt.state.stories["s1"]
    assert (s.step, s.status) == ("review", StoryStatus.DONE)
    assert events_of(rt, "ruling") == []


def test_a_storyless_ruling_is_refused_in_the_report(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", ruling="rescope")))
    report = run(rt, "manager", story_id=None)
    assert report["ruling"] == {
        "ruling": "rescope",
        "applied": False,
        "why": "a ruling needs a story; run the manager on that story",
    }
    assert events_of(rt, "ruling") == []


def test_a_manager_step_without_a_ruling_reports_none(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done")))
    open_story(rt, "review")
    assert "ruling" not in run(rt, "manager")
    assert rt.state.stories["s1"].step == "review"


def test_other_roles_reports_carry_no_ruling(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", ruling="rescope")))
    open_story(rt, "design")
    assert "ruling" not in run(rt, "architect")


def test_the_manager_context_lists_disputes_since_its_last_review(make_runtime) -> None:
    rt = dispute_runtime(make_runtime)
    run(rt, "developer")
    rt.query_fn.text = handoff("done")
    run(rt, "manager")
    # T9 puts the open dispute's line in every prompt on the story, the Manager's
    # included, so only the runner-context list is checked for repeats.
    first = context_of(rt.query_fn.calls[1]["prompt"])
    assert "test_disputes_since_last_review" in first and TEST_ID in first
    run(rt, "manager")
    second = context_of(rt.query_fn.calls[2]["prompt"])
    assert "test_disputes_since_last_review" in second and TEST_ID not in second


def context_of(prompt: str) -> str:
    """The Manager prompt's "Runner context" JSON, without the story lines."""
    return prompt.split("Runner context:", 1)[1]


# ----- end to end through the router (item 6) ---------------------------------


def test_a_dispute_round_trip_costs_no_round_and_no_handover(make_runtime) -> None:
    dispute = handoff("changes_requested", summary="why", dispute=DISPUTE_JSON)

    async def fix_test(rt) -> None:
        write_test_file(rt, NEW)
        rt.record_checkout()  # s61: the shortcut commit is ours, not a foreign one

    script = Script({"developer": [dispute], "unit-tester": [fix_test]})
    rt = build(make_runtime, script, steps=["tests", "implement", "review"])
    rt.pipeline.checks.read = functools.partial(gates.read_repo_file, rt.config.repo)
    inner = rt.pipeline.checks.run
    rt.pipeline.checks.run = lambda c: (0, FILE + "\n") if c == LS else inner(c)
    write_test_file(rt)
    add_story(rt, "s1", "implement")
    drive(rt)
    assert step_roles(rt)[:4] == ["developer", "unit-tester", "developer", "code-reviewer"]
    s = rt.state.stories["s1"]
    assert (s.rounds, s.dispute, s.status) == (0, None, StoryStatus.DONE)
    assert len(handover_events(rt)) == 1  # only the sprint end
    assert f"Test dispute (raised): {TEST_ID}" in script.prompts["unit-tester"][0]


def test_a_dispute_on_an_untracked_path_is_a_round_not_a_dispute(make_runtime) -> None:
    rt = dispute_runtime(make_runtime)
    rt.pipeline.checks.run.results[LS] = (0, "")
    run(rt, "developer")
    s = rt.state.stories["s1"]
    assert (s.step, s.rounds, s.dispute, s.disputes) == ("implement", 1, None, 0)
    assert events_of(rt, "test-dispute") == [] and len(events_of(rt, "gate")) == 1


# ----- F7: a repeated unchanged bounce escalates --------------------------------


def test_the_same_unchanged_bounce_twice_escalates_not_caps(make_runtime) -> None:
    rt = dispute_runtime(make_runtime)
    run(rt, "developer")
    rt.query_fn.text = handoff("done", summary="fixed")
    run(rt, "unit-tester")
    s = rt.state.stories["s1"]
    assert (s.step, s.rounds, s.status) == ("tests", 1, StoryStatus.ACTIVE)
    run(rt, "unit-tester")
    assert (s.step, s.rounds, s.status) == ("tests", 1, StoryStatus.NEEDS_MANAGER)
    assert events_of(rt, "escalation")[-1].data["verdict"] == "escalate"
