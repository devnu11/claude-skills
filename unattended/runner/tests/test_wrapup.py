from __future__ import annotations

from unattended.wrapup import DEFAULT_WRAP_UP_PROMPT, Allowance, build_wrap_up_prompt


def test_the_prompt_names_the_reason() -> None:
    prompt = build_wrap_up_prompt(DEFAULT_WRAP_UP_PROMPT, "deadline (graceful)")
    assert "The run is being stopped: deadline (graceful)." in prompt
    assert "{reason}" not in prompt


def test_the_allowance_counts_from_the_turns_start() -> None:
    allowance = Allowance(0.5, start=2.0)
    assert not allowance.is_used_up(2.4)
    assert allowance.is_used_up(2.5)
    assert not allowance.is_used_up(None)
