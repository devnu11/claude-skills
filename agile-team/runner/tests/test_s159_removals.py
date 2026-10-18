"""s159 G1/G2: the pending-tests registry and the red-first gate are gone."""

from __future__ import annotations

from agile_team import cli, onboard, roles, stages


def test_pending_tests_command_is_unknown() -> None:
    """s159 spec: pending tests command is unknown (s159 red)."""
    assert "pending-tests" not in [c.name for c in cli.COMMANDS]


def test_onboarding_writes_no_pending_line() -> None:
    """s159 spec: onboarding writes no pending line (s159 red)."""
    assert "!.team/pending-tests.json" not in onboard.gitignore_lines("ignored")
    assert onboard.RUN_IGNORE in onboard.gitignore_lines("ignored")


def test_red_stages_are_gone() -> None:
    """s159 spec: red stages are gone (s159 red)."""
    names = {m.name for m in stages.Name}
    assert not names & {"GATE_TESTS_RED", "GATE_TESTS_REWORK", "STOP_RED"}


def test_land_stage_exists() -> None:
    """s159 spec: land stage exists (s159 red)."""
    assert stages.Name.STORY_LAND.value == "story.land"


def test_test_claim_is_gone() -> None:
    """s159 spec: test claim is gone (s159 red)."""
    assert not hasattr(roles, "TestClaim")


def test_a_handoff_with_a_tests_key_still_parses() -> None:
    """s159 spec: a handoff with a tests key still parses (s159 red)."""
    text = '```handoff\n{"status": "done", "summary": "s", "tests": "changed"}\n```'
    handoff = roles.parse_handoff(text)
    assert handoff.status == "done"
    assert not hasattr(handoff, "tests")
