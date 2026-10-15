"""s154 AC3 (G7): a bouncing gate event carries the failing tests' error lines."""

from agile_team import gates
from agile_team.gates import Verdict
from agile_team.results import FAILURES_SHOWN, Ran

from .pipeline_helpers import add_story
from .test_gates import STEPS
from .test_s27_backstop import _dplan, _rt


def gate_data(make_runtime, outcome, step="implement"):
    """Run ``outcome`` through the gate log; the data of the gate event it emitted."""
    rt = _rt(make_runtime)
    st = add_story(rt, step=step)
    rt._advance_and_log(_dplan(rt, rt.resolve("customer-proxy"), st), outcome)
    return [e for e in rt.events.events() if e.kind == "gate"][-1].data


def bounce(**kw):
    return gates.Outcome(Verdict.BOUNCE, "red", STEPS[0], **kw)


def test_s154_ac3_a_bounce_event_carries_the_failures(make_runtime, configured):
    ran = Ran("test", 1, "t", failures={"t::a": "AssertionError: x"})
    data = gate_data(make_runtime, bounce(ran=ran))
    assert data["failures"] == {"t::a": "AssertionError: x"}
    assert "failures_more" not in data


def test_s154_ac3_failures_merge_over_ran_and_extra_ran(make_runtime, configured):
    first = Ran("test", 1, "t", failures={"t::a": "old"})
    extra = Ran("coverage", 1, "t", failures={"t::a": "new", "t::b": "b"})
    data = gate_data(make_runtime, bounce(ran=first, extra_ran=(extra,)))
    assert data["failures"] == {"t::a": "new", "t::b": "b"}


def test_s154_ac3_a_bounce_over_the_cap_counts_the_rest(make_runtime, configured):
    many = {f"t::{i}": "e" for i in range(FAILURES_SHOWN + 3)}
    data = gate_data(make_runtime, bounce(ran=Ran("test", 1, "t", failures=many)))
    assert len(data["failures"]) == FAILURES_SHOWN
    assert data["failures_more"] == 3


def test_s154_ac3_a_bounce_without_failures_carries_neither_key(make_runtime, configured):
    data = gate_data(make_runtime, bounce(ran=Ran("test", 1, "t")))
    assert "failures" not in data
    assert "failures_more" not in data


def test_s154_ac3_a_passing_gate_carries_neither_key(make_runtime, configured):
    ran = Ran("test", 1, "t", failures={"t::a": "e"})
    data = gate_data(make_runtime, gates.Outcome(Verdict.PASS, ran=ran))
    assert "failures" not in data
    assert "failures_more" not in data
