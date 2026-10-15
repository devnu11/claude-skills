"""s128 S2: a command job records why agile-team stopped, not a bare ``done``."""

from __future__ import annotations

import json
from pathlib import Path

from unattended import command_job
from unattended.command_job import RunOutput
from unattended.limits import REASON_LIMIT, Outcome, OutcomeKind

HALT = "agile-team start: checkout-changed; run `agile-team start --resume` to carry on"


def write_state(cwd: Path, data: object) -> None:
    path = cwd / ".team/run/state.json"
    path.parent.mkdir(parents=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def test_exit_zero_records_status_and_reason(tmp_path: Path) -> None:
    write_state(tmp_path, {"status": "blocked", "status_reason": "x"})
    out = command_job.outcome_for(0, RunOutput("", tmp_path))
    assert out == Outcome(OutcomeKind.DONE, "agile-team blocked: x")


def test_exit_zero_with_no_reason_records_the_status_alone(tmp_path: Path) -> None:
    write_state(tmp_path, {"status": "done", "status_reason": None})
    assert command_job.outcome_for(0, RunOutput("", tmp_path)).reason == "agile-team done"
    assert command_job.agile_status(RunOutput("", tmp_path)) == "agile-team done"


def test_exit_zero_with_no_state_file_records_nothing(tmp_path: Path) -> None:
    assert command_job.outcome_for(0, RunOutput("", tmp_path)) == Outcome(OutcomeKind.DONE, "")
    assert command_job.agile_status(RunOutput("", tmp_path)) is None


def test_bad_json_or_a_non_string_status_gives_none(tmp_path: Path) -> None:
    write_state(tmp_path, "{not json")
    assert command_job.agile_status(RunOutput("", tmp_path)) is None
    (tmp_path / ".team/run/state.json").write_text(json.dumps({"status": 3}))
    assert command_job.agile_status(RunOutput("", tmp_path)) is None
    (tmp_path / ".team/run/state.json").write_text(json.dumps([1]))
    assert command_job.agile_status(RunOutput("", tmp_path)) is None


def test_the_reason_is_cut_to_the_limit(tmp_path: Path) -> None:
    write_state(tmp_path, {"status": "blocked", "status_reason": "y" * 500})
    reason = command_job.agile_status(RunOutput("", tmp_path))
    assert reason is not None and len(reason) == REASON_LIMIT
    assert reason.startswith("agile-team blocked: yyy")


def test_a_halt_line_is_recorded_on_a_failed_exit(tmp_path: Path) -> None:
    out = command_job.outcome_for(78, RunOutput(f"noise\n{HALT}\n", tmp_path))
    assert out == Outcome(OutcomeKind.FAILED, "exit code 78; agile-team halted: checkout-changed")


def test_without_a_halt_line_the_state_file_explains(tmp_path: Path) -> None:
    write_state(tmp_path, {"status": "halted", "status_reason": "checkout-changed"})
    out = command_job.outcome_for(78, RunOutput("nothing", tmp_path))
    assert out.kind is OutcomeKind.FAILED
    assert out.reason == "exit code 78; agile-team halted: checkout-changed"


def test_the_halt_line_beats_the_state_file(tmp_path: Path) -> None:
    write_state(tmp_path, {"status": "blocked", "status_reason": "old"})
    out = command_job.outcome_for(78, RunOutput(HALT, tmp_path))
    assert out.reason == "exit code 78; agile-team halted: checkout-changed"


def test_with_neither_it_is_just_the_exit_code(tmp_path: Path) -> None:
    assert command_job.outcome_for(3, RunOutput("boom", tmp_path)) == Outcome(
        OutcomeKind.FAILED, "exit code 3"
    )


def test_an_offline_failure_is_unchanged(tmp_path: Path) -> None:
    write_state(tmp_path, {"status": "blocked", "status_reason": "x"})
    out = command_job.outcome_for(1, RunOutput("getaddrinfo ENOTFOUND api.anthropic.com", tmp_path))
    assert out.kind is OutcomeKind.OFFLINE and out.reason.endswith(", exit code 1")
    assert "agile-team" not in out.reason
