"""s27: repeated setbacks escalate (loops, screen, config, state)."""

import dataclasses

import pytest
from agile_team import config as cfg
from agile_team import gates, loops, state
from agile_team.gates import StoryStatus, Verdict

from .test_gates import checks, story

EXAMPLES = [
    (
        "tests fail:\n FAILED tests/test_x.py::test_a - assert 3 == 4\n1 failed in 0.42s",
        "tests fail: failed <path>::test_a - assert <n> == <n> <n> failed in <n>s",
    ),
    ("coverage 93.5% is below 95.0%", "coverage <n>% is below <n>%"),
    (
        "nothing is listening at 127.0.0.1:8799 (connection refused)",
        "nothing is listening at <host> (connection refused)",
    ),
    ("e2e passed at 2:20pm on 2026-10-10T14:20:00Z", "e2e passed at <time> on <time>"),
]


@pytest.mark.parametrize(("reason", "expected"), EXAMPLES)
def test_normalise_worked_examples(reason, expected):
    assert loops.normalise(reason) == expected


def test_same_reason_other_numbers_same_key():
    a = loops.Setback(
        "acceptance", "e2e", "customer-proxy", "bounce", "role", "down at 127.0.0.1:8799 pid 12"
    )
    b = loops.Setback(
        "acceptance", "e2e", "customer-proxy", "bounce", "role", "down at 127.0.0.1:9000 pid 99"
    )
    assert a.key == b.key
    assert a.key.startswith("acceptance>e2e ")


def test_different_tests_different_keys():
    def make(name):
        return loops.Setback(
            "tests", "tests", "unit-tester", "bounce", "runner", f"FAILED t.py::{name}"
        )

    assert make("test_a").key != make("test_b").key


def test_stored_key_is_recomputed():
    s = loops.Setback("a", "b", "r", "bounce", "role", "x", key="forged")
    assert s.key == "a>b x"
    assert s.author is loops.Author.ROLE


def _sb(reason):
    return loops.Setback("a", "b", "r", "bounce", "runner", reason)


def test_extend_and_repeats():
    first, same, other = _sb("x"), _sb("x"), _sb("y")
    assert loops.repeats([], first) == 0
    assert loops.extend([], first) == [first]
    assert loops.repeats([first], same) == 1
    assert loops.extend([first], same) == [first, same]
    assert loops.repeats([first], other) == 0
    assert loops.extend([first], other) == [other]


def test_pipeline_repeat_default_and_first_setback_moves():
    pipe = gates.Pipeline(["design", "tests"], 3, checks())
    assert pipe.repeat == 2
    st = story("tests")
    setback = _sb("x")
    assert pipe.screen(st, setback) is None


def test_second_same_setback_escalates_without_round():
    pipe = gates.Pipeline(["design", "tests"], 3, checks())
    st = story("tests", rounds=1)
    st.streak = [_sb("x")]
    out = pipe.screen(st, _sb("x"))
    assert out.verdict is Verdict.ESCALATE
    pipe.advance(st, out)
    assert (st.step, st.rounds) == ("tests", 1)
    assert st.status is StoryStatus.NEEDS_MANAGER
    assert st.repeated == "x"


def test_different_reason_resets_and_repeat_three():
    pipe = gates.Pipeline(["design", "tests"], 3, checks(), 3)
    st = story("tests")
    st.streak = [_sb("x"), _sb("x")]
    assert pipe.screen(st, _sb("y")) is None
    assert pipe.screen(st, _sb("x")).verdict is Verdict.ESCALATE


def test_fault_kinds_and_apply():
    pipe = gates.Pipeline(["design", "tests", "e2e"], 3, checks())
    assert pipe.fault_kind("runner") is loops.Fault.RUNNER
    assert pipe.fault_kind("integration-tester") is loops.Fault.PIPELINE
    assert pipe.fault_kind("devops") is loops.Fault.OFF_PIPELINE
    st = story("tests", rounds=2, disputes=1)
    st.streak, st.repeated = [_sb("x")], "x"
    pipe.apply_fault(st, "integration-tester")
    assert (st.step, st.status) == ("e2e", StoryStatus.ACTIVE)
    assert (st.rounds, st.disputes, st.streak, st.repeated) == (0, 0, [], None)
    pipe.apply_fault(story("tests"), "runner")


def test_runner_fault_blocks():
    pipe = gates.Pipeline(["tests"], 3, checks())
    st = story("tests")
    pipe.apply_fault(st, "runner")
    assert st.status is StoryStatus.BLOCKED


def test_config_repeat(repo):
    known = cfg.Known({"developer"}, {"package", "web", "harness"})
    assert cfg.Gates().repeat == 2
    raw = {"gates": {"repeat": 1}}
    problems = cfg.validate(cfg.from_raw(repo, raw), known)
    assert "gates.repeat must be at least 2" in problems


def test_state_roundtrip_streak():
    st = story("tests")
    st.streak, st.repeated = [_sb("x")], "x"
    data = dataclasses.asdict(st)
    loaded = state._story(data)
    assert loaded.streak == [_sb("x")]
    assert loaded.repeated == "x"
    for k in ("streak", "repeated"):
        data.pop(k)
    old = state._story(data)
    assert (old.streak, old.repeated) == ([], None)
