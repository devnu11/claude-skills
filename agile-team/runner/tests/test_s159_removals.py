"""s159 G1/G2/AC4.x: pending tests and the red-first gate are gone; land is the runner's."""

import importlib

import pytest
from agile_team import cli, gates, halt, roles, stages, state, waits
from agile_team import onboard as onboard_mod
from agile_team.ledger import Entry


def test_the_registry_module_is_gone_r1() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agile_team.pending_tests")


def test_the_pending_tests_command_is_gone_r1() -> None:
    assert "pending-tests" not in {c.name for c in cli.COMMANDS}
    assert not hasattr(cli, "PENDING_ARGS")


def test_onboarding_writes_no_pending_line_r1() -> None:
    texts = [str(v) for k, v in vars(onboard_mod).items() if not k.startswith("__")]
    lists = [x for v in vars(onboard_mod).values() if isinstance(v, (list, tuple)) for x in v]
    assert not [t for t in texts + [str(x) for x in lists] if "pending-tests" in t]


def test_the_red_stages_are_gone_r1() -> None:
    names = {n.value for n in stages.Name}
    assert not names & {"gate.tests-red", "gate.tests-rework", "stop.red"}
    assert not {"boundary.rebase", "boundary.push-rebased", "boundary.ci-rebased"} & names
    assert {"story.land", "boundary.open", "boundary.replay"} <= names
    assert {"boundary.push-replayed", "boundary.ci-replayed"} <= names
    assert "story" in stages.NAMESPACES


def test_the_red_gate_pieces_are_gone_r1() -> None:
    for name in ["REWORK_UNCLAIMED", "REWORK_PASS", "GREEN_TOO_EARLY", "NOT_PENDING"]:
        assert not hasattr(gates, name), name
    assert not hasattr(roles, "TestClaim")


def test_a_handoff_with_a_tests_key_parses_and_ignores_it_r1() -> None:
    text = '```handoff\n{"status": "done", "summary": "s", "tests": "changed"}\n```'
    parsed = roles.parse_handoff(text)
    assert parsed.status == "done"
    assert not hasattr(parsed, "tests")


def test_land_belongs_to_the_runner_r1() -> None:
    assert gates.STEP_ROLES["land"] == "runner"
    assert "land" in gates.CHECKPOINT_STEPS


def test_the_limit_status_halts_with_exit_75_r1() -> None:
    assert state.RunStatus.LIMIT == "limit"
    assert state.RunState(status=state.RunStatus.LIMIT).halted()
    rule = halt.HALTS[halt.HaltKind.LIMIT]
    assert (rule.status, rule.note_kind, rule.exit_code) == (state.RunStatus.LIMIT, "blocked", 75)


def test_ledger_entry_new_fields_default_false_r1() -> None:
    e = Entry(role="developer", model="opus", cost_usd=1.0)
    assert e.resumed is False and e.estimated is False
    assert Entry.from_dict({"role": "r", "model": "m", "cost_usd": 1.0, "resumed": True}).resumed


def test_new_wait_reasons_r1() -> None:
    values = {w.value for w in waits.WaitReason}
    assert {
        "land_queue",
        "permission",
        "landing_ci",
        "worktree_drift",
        "open_cap",
        "reserve",
    } <= values
