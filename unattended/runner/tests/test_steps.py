from __future__ import annotations

import anyio
from unattended.steps import POST, PRE, Advice, Steps, build_reply


def run_after(steps: Steps) -> dict:
    return anyio.run(steps.complete_step, {}, "tool-1", {})


def run_before(steps: Steps) -> dict:
    return anyio.run(steps.check_step, {}, "tool-1", {})


def test_hooks_cover_both_sides_of_a_step() -> None:
    steps = Steps()
    hooks = steps.hooks
    assert hooks[PRE][0].hooks == [steps.check_step]
    assert hooks[POST][0].hooks == [steps.complete_step]


def test_a_step_runs_while_the_run_may_go_on() -> None:
    assert run_before(Steps()) == {}
    assert run_after(Steps()) == {}


def test_end_refuses_the_next_step_and_keeps_the_first_reason() -> None:
    steps = Steps()
    steps.end("deadline (graceful)")
    steps.end("later")
    assert run_before(steps) == {"continue_": False, "stopReason": "deadline (graceful)"}


def test_checks_add_context_for_the_model_in_order() -> None:
    steps = Steps([lambda: Advice("first"), lambda: Advice(), lambda: Advice("second")])
    reply = run_after(steps)
    assert reply == {
        "hookSpecificOutput": {"hookEventName": POST, "additionalContext": "first\n\nsecond"}
    }
    assert steps.halt is None


def test_a_check_can_end_the_run_after_its_step() -> None:
    steps = Steps([lambda: Advice("wrap up", stop="cost cap")])
    reply = run_after(steps)
    assert steps.halt == "cost cap"
    assert reply["continue_"] is False
    assert reply["stopReason"] == "cost cap"
    assert reply["hookSpecificOutput"]["additionalContext"] == "wrap up"


def test_a_reply_without_context_or_halt_is_empty() -> None:
    assert build_reply("", None) == {}


def test_wrapping_up_denies_tools_but_lets_the_turn_go_on() -> None:
    steps = Steps()
    steps.end("cap")
    steps.wrap_up()
    reply = run_before(steps)
    assert "continue_" not in reply
    assert reply["hookSpecificOutput"]["permissionDecision"] == "deny"
