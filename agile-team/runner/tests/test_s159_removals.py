"""s159 G1/G2: the pending-tests registry and the red-first gate are gone."""

from __future__ import annotations

from agile_team import cli, onboard, roles, stages


def test_pending_tests_command_is_unknown() -> None:
    assert "pending-tests" not in [c.name for c in cli.COMMANDS]


def test_onboarding_writes_no_pending_line() -> None:
    assert "!.team/pending-tests.json" not in onboard.gitignore_lines("ignored")
    assert onboard.RUN_IGNORE in onboard.gitignore_lines("ignored")


def test_red_stages_are_gone() -> None:
    names = {m.name for m in stages.Name}
    assert not names & {"GATE_TESTS_RED", "GATE_TESTS_REWORK", "STOP_RED"}


def test_land_stage_exists() -> None:
    assert stages.Name.STORY_LAND.value == "story.land"


def test_test_claim_is_gone() -> None:
    assert not hasattr(roles, "TestClaim")


def test_a_handoff_with_a_tests_key_still_parses() -> None:
    text = '```handoff\n{"status": "done", "summary": "s", "tests": "changed"}\n```'
    handoff = roles.parse_handoff(text)
    assert handoff.status == "done"
    assert not hasattr(handoff, "tests")
