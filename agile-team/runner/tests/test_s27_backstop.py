"""s27 AC4b: the back-and-forth backstop (rules B1-B9 of the design amendment)."""

import dataclasses
import json
from pathlib import Path

import pytest
from agile_team import cli, gates, loops, router, state
from agile_team import config as cfg
from agile_team.gates import StoryStatus, Verdict
from agile_team.loops import Rule

from .pipeline_helpers import add_story
from .test_gates import STEPS, checks, story


def sb(reason, step="acceptance", to_step="e2e", verdict="return", event=""):
    """A setback on the acceptance>e2e pair unless told otherwise."""
    return loops.Setback(step, to_step, "customer-proxy", verdict, "role", reason, event)


def pipe(repeat=2, backstop=4):
    return gates.Pipeline(list(STEPS), 3, checks(), repeat, backstop)


# ---- B1-B3: loops helpers --------------------------------------------------


def test_rule_values_and_pair_not_saved():
    assert (Rule.REPEAT, Rule.BACKSTOP) == ("repeat", "backstop")
    s = sb("x")
    assert s.pair == ("acceptance", "e2e")
    assert "pair" not in dataclasses.asdict(s)


def test_extend_run_ignores_reasons_and_restarts_on_new_pair():
    a, b = sb("A"), sb("B")
    assert loops.extend_run([], a) == [a]
    assert loops.extend_run([a], b) == [a, b]
    other = sb("A", step="e2e", to_step="implement", verdict="bounce")
    assert loops.extend_run([a, b], other) == [other]


def test_after_pass_resets_only_on_the_upper_step():
    run = [sb("A"), sb("B")]
    assert loops.after_pass(run, "acceptance") == []
    assert loops.after_pass(run, "e2e") == run
    assert loops.after_pass(run, "review") == run
    assert loops.after_pass([], "acceptance") == []


@pytest.mark.parametrize(
    ("run", "setback", "expected"),
    [
        ([], sb("A"), 0),
        ([sb("A")], sb("B", step="e2e", to_step="implement"), 0),
        ([sb("A")], sb("B", verdict="hold"), 0),
        ([sb("A")], sb("B", step="e2e", to_step="e2e", verdict="bounce"), 0),
        ([sb("A")], sb("B"), 1),
        ([sb("A"), sb("B"), sb("C")], sb("D", verdict="bounce"), 3),
    ],
)
def test_bounces_counts_the_run_for_a_counted_setback(run, setback, expected):
    assert loops.bounces(run, setback) == expected


def test_backstop_reason_lists_every_reason():
    run = [sb("A", event="e1"), sb("B", event="e2"), sb("C", event="e3"), sb("D")]
    lines = loops.backstop_reason(run).splitlines()
    assert lines[0] == loops.BACKSTOP_HEAD.format(count=4, step="acceptance", to_step="e2e")
    assert lines[1:] == ["- e1: A", "- e2: B", "- e3: C", "- now: D"]


def test_trail_follows_the_rule_that_escalated():
    st = story("acceptance")
    st.streak, st.run = [sb("S")], [sb("R1"), sb("R2")]
    assert loops.trail(st) == st.streak
    st.escalated_by = Rule.REPEAT
    assert loops.trail(st) == st.streak
    st.escalated_by = Rule.BACKSTOP
    assert loops.trail(st) == st.run


# ---- B4 / B5: Pipeline.screen ---------------------------------------------


def test_default_backstop_is_four():
    assert pipe().backstop == 4
    assert gates.Pipeline(list(STEPS), 3, checks()).backstop == 4


def test_fourth_bounce_in_a_row_escalates_with_every_reason():
    p, st = pipe(), story("acceptance", rounds=1)
    st.run = [sb("A"), sb("B"), sb("C")]
    out = p.screen(st, sb("D"))
    assert out.verdict is Verdict.ESCALATE and out.rule is Rule.BACKSTOP
    assert out.bounce_to == "acceptance"
    assert out.reason == loops.backstop_reason([*st.run, sb("D")])
    p.advance(st, out)
    assert (st.step, st.rounds, st.status) == ("acceptance", 1, StoryStatus.NEEDS_MANAGER)
    assert st.escalated_by == "backstop"
    assert st.repeated == out.reason
    assert all(x in st.repeated for x in "ABCD")


def test_third_bounce_does_not_escalate():
    st = story("acceptance")
    st.run = [sb("A"), sb("B")]
    assert pipe().screen(st, sb("C")) is None


def test_hold_and_other_pair_do_not_trigger():
    st = story("acceptance")
    st.run = [sb("A"), sb("B"), sb("C")]
    assert pipe().screen(st, sb("D", verdict="hold")) is None
    assert pipe().screen(st, sb("D", step="e2e", to_step="implement")) is None


def test_repeat_wins_when_both_fire_on_the_same_setback():
    st = story("acceptance")
    st.streak, st.run = [sb("A")], [sb("A")]
    out = pipe(repeat=2, backstop=4).screen(st, sb("A"))
    assert out.rule is Rule.REPEAT
    assert pipe(repeat=2, backstop=2).screen(st, sb("A")).rule is Rule.REPEAT


def test_backstop_fires_first_when_reasons_differ():
    st = story("acceptance")
    st.streak, st.run = [sb("A")], [sb("A")]
    out = pipe(repeat=3, backstop=2).screen(st, sb("B"))
    assert out.verdict is Verdict.ESCALATE and out.rule is Rule.BACKSTOP


def test_repeat_escalation_leaves_escalated_by_repeat():
    p, st = pipe(), story("acceptance")
    st.streak, st.run = [sb("A")], [sb("A")]
    p.advance(st, p.screen(st, sb("A")))
    assert st.escalated_by == "repeat"


def test_clear_empties_run_and_escalated_by():
    p, st = pipe(), story("acceptance")
    st.run, st.escalated_by, st.repeated = [sb("A")], Rule.BACKSTOP, "x"
    p.apply_fault(st, "runner")
    assert (st.run, st.escalated_by, st.repeated) == ([], None, None)
    st.run, st.escalated_by = [sb("A")], Rule.BACKSTOP
    p.apply_ruling(st, "rescope")
    assert (st.run, st.escalated_by) == ([], None)


# ---- B2 / B3 / B6 / B8 through the runtime ---------------------------------


def _rt(make_runtime, script=None, backstop=4):
    from .pipeline_helpers import Script, build

    rt = build(make_runtime, script or Script(), steps=STEPS)
    rt.pipeline.repeat, rt.pipeline.backstop = 99, backstop
    return rt


def _dplan(rt, role, st):
    from agile_team.dispatch import Plan

    return Plan(role, rt.scope_for(role), st)


def _gate(rt, st, outcome, role="customer-proxy"):
    return rt._advance_and_log(_dplan(rt, rt.resolve(role), st), outcome)


def _return(rt, st, reason):
    """The Proxy sends the story from acceptance back to e2e; e2e then passes."""
    st.step = "acceptance"
    return _gate(rt, st, gates.Outcome(Verdict.RETURN, reason, "e2e"))


def _pass_e2e(rt, st):
    st.step = "e2e"
    _gate(rt, st, gates.Outcome(Verdict.PASS), "integration-tester")


def _kinds(rt, *kinds):
    return [e for e in rt.events.events() if e.kind in kinds]


def test_four_returns_with_different_keys_escalate_on_the_fourth(make_runtime, configured):
    rt = _rt(make_runtime)
    st = add_story(rt, step="acceptance", rounds=1)
    for i, reason in enumerate("ABC"):
        res = _return(rt, st, f"reason {reason}")
        assert res["verdict"] == "return"
        assert len(st.run) == i + 1
        _pass_e2e(rt, st)
        assert len(st.run) == i + 1  # the lower step passing does not reset
    res = _return(rt, st, "reason D")
    assert res["verdict"] == "escalate"
    assert (st.step, st.rounds, st.status) == ("acceptance", 1, StoryStatus.NEEDS_MANAGER)
    assert st.escalated_by == "backstop"
    assert all(f"reason {x}" in st.repeated for x in "ABCD")


def test_events_carry_bounces_rule_count_and_history(make_runtime, configured):
    rt = _rt(make_runtime)
    st = add_story(rt, step="acceptance")
    for reason in "ABC":
        _return(rt, st, f"reason {reason}")
        _pass_e2e(rt, st)
    _return(rt, st, "reason D")
    gate_events = [e for e in _kinds(rt, "gate") if "bounces" in e.data]
    assert [e.data["bounces"] for e in gate_events if e.data["verdict"] == "return"] == [1, 2, 3]
    (esc,) = _kinds(rt, "escalation")
    assert esc.data["rule"] == "backstop"
    assert esc.data["count"] == 4
    earlier = [e.id for e in gate_events if e.data["verdict"] == "return"]
    assert esc.data["history"] == earlier
    assert esc.data["bounces"] == 4


def test_repeat_escalation_event_carries_rule_repeat(make_runtime, configured):
    rt = _rt(make_runtime)
    rt.pipeline.repeat = 2
    st = add_story(rt, step="acceptance")
    _return(rt, st, "same")
    _return(rt, st, "same")
    (esc,) = _kinds(rt, "escalation")
    assert esc.data["rule"] == "repeat"
    assert st.escalated_by == "repeat"


def test_hold_neither_counts_nor_resets_and_has_zero_bounces(make_runtime, configured):
    rt = _rt(make_runtime)
    st = add_story(rt, step="acceptance")
    _return(rt, st, "A")
    st.step = "acceptance"
    _gate(rt, st, gates.Outcome(Verdict.HOLD, "stopped"))
    assert [s.reason for s in st.run] == ["A"]
    hold = [e for e in _kinds(rt, "gate") if e.data["verdict"] == "hold"][-1]
    assert hold.data["bounces"] == 0


def test_pass_at_acceptance_restarts_the_count(make_runtime, configured):
    rt = _rt(make_runtime)
    st = add_story(rt, step="acceptance")
    _return(rt, st, "A")
    _return(rt, st, "B")
    st.step = "acceptance"
    _gate(rt, st, gates.Outcome(Verdict.PASS))
    assert st.run == []
    st.status, st.step = StoryStatus.ACTIVE, "acceptance"
    assert _return(rt, st, "C")["verdict"] == "return"
    assert len(st.run) == 1


def test_a_different_pair_restarts_the_count_at_one(make_runtime, configured):
    rt = _rt(make_runtime)
    st = add_story(rt, step="acceptance")
    for reason in "AB":
        _return(rt, st, reason)
    st.step = "e2e"
    _gate(rt, st, gates.Outcome(Verdict.BOUNCE, "Z", "implement"), "integration-tester")
    assert [s.reason for s in st.run] == ["Z"]
    gate = _kinds(rt, "gate")[-1]
    assert gate.data["bounces"] == 1


def test_returns_add_no_rounds(make_runtime, configured):
    rt = _rt(make_runtime)
    st = add_story(rt, step="acceptance", rounds=0)
    for reason in "ABC":
        _return(rt, st, reason)
        _pass_e2e(rt, st)
    _return(rt, st, "D")
    assert st.rounds == 0


# ---- B6 / B7: the Manager's view and brief --------------------------------


def test_backstop_heading_text_and_table():
    assert router.HEADINGS[Rule.BACKSTOP] is router.BACKSTOP_HEADING
    assert router.HEADINGS[Rule.REPEAT] is router.REPEAT_HEADING
    text = router.BACKSTOP_HEADING.format(id="s1", step="acceptance", to_step="e2e", count=4)
    assert text.startswith("Story s1 bounced between acceptance and e2e 4 times in a row")
    assert "repeated_setback" in text


def _events(n):
    from agile_team.events import Event, EventKind

    return [Event(EventKind.GATE, "customer-proxy", "s1", {}, id=f"e{i}") for i in range(1, n + 1)]


def test_manager_view_of_a_backstop_escalation():
    st = story("acceptance")
    st.run = [sb(r, event=f"e{i}") for i, r in enumerate(["A", "B", "C", "D"], 1)]
    st.escalated_by, st.repeated = Rule.BACKSTOP, loops.backstop_reason(st.run)
    st.streak = [sb("D", event="e4")]
    view = loops.manager_view(st, _events(5))
    assert view["rule"] == "backstop"
    assert view["pair"] == "acceptance>e2e"
    assert view["count"] == 4
    assert all(x in json.dumps(view["history"], default=str) for x in "ABCD")
    ids = [e["id"] if isinstance(e, dict) else e.id for e in view["events"]]
    assert ids[0] == "e1"


def test_manager_view_of_a_repeat_escalation_uses_the_streak():
    st = story("acceptance")
    st.streak = [sb("A", event="e1"), sb("A", event="e2")]
    st.run = [sb("A", event="e1"), sb("A", event="e2"), sb("A", event="e3")]
    st.escalated_by, st.repeated = Rule.REPEAT, "A"
    view = loops.manager_view(st, _events(3))
    assert view["rule"] == "repeat"
    assert view["count"] == 2


# ---- config and state ------------------------------------------------------


def test_config_backstop_default_and_floor(tmp_path):
    known = cfg.Known({"developer"}, {"package", "web", "harness"})
    assert cfg.Gates().backstop == 4
    problems = cfg.validate(cfg.from_raw(tmp_path, {"gates": {"backstop": 1}}), known)
    assert "gates.backstop must be at least 2" in problems
    ok = cfg.validate(cfg.from_raw(tmp_path, {"gates": {"backstop": 2}}), known)
    assert "gates.backstop must be at least 2" not in ok


def test_make_pipeline_passes_backstop(tmp_path):
    config = cfg.from_raw(tmp_path, {"gates": {"backstop": 6, "repeat": 3}})
    made = cli.make_pipeline(config)
    assert (made.repeat, made.backstop) == (3, 6)


def test_state_roundtrip_run_and_escalated_by():
    st = story("acceptance")
    st.run, st.escalated_by = [sb("A", event="e1"), sb("B", event="e2")], Rule.BACKSTOP
    data = json.loads(json.dumps(dataclasses.asdict(st), default=str))
    loaded = state._story(data)
    assert loaded.run == st.run
    assert loaded.escalated_by == "backstop"
    for k in ("run", "escalated_by"):
        data.pop(k)
    old = state._story(data)
    assert (old.run, old.escalated_by) == ([], None)


def test_run_state_file_roundtrip(tmp_path: Path):
    rs = state.RunState()
    st = story("acceptance")
    st.run, st.escalated_by = [sb("A")], Rule.BACKSTOP
    rs.stories["s1"] = st
    state.save(tmp_path, rs)
    back = state.load(tmp_path).stories["s1"]
    assert back.run == [sb("A")]
    assert back.escalated_by == "backstop"


# ---- B9: dashboard ---------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "agile_team/dashboard/fixtures/snapshot.json"
PAGE = Path(__file__).parent.parent / "agile_team/dashboard/index.html"


def test_page_labels_backstop_escalations():
    html = PAGE.read_text(encoding="utf-8")
    assert (
        'e.data.rule === "backstop" ? "back and forth → needs manager" : "repeat → needs manager"'
        in html
    )


def test_fixture_escalation_has_rule_and_keyed_gate_has_bounces():
    events = json.loads(FIXTURE.read_text(encoding="utf-8"))["events"]
    (esc,) = [e for e in events if e["kind"] == "escalation"]
    assert esc["data"]["rule"] == "repeat"
    keyed = [e for e in events if e["kind"] == "gate" and "key" in e["data"]]
    assert keyed and all(e["data"]["bounces"] == 1 for e in keyed[:1])
