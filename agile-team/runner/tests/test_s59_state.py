"""s59 R2/R10: ``group_files`` and the ``sync_from`` field in saved state."""

import json
from dataclasses import asdict

import pytest
from agile_team import boundary as bd
from agile_team import handover
from agile_team.handover import group_files
from agile_team.state import RunState


def test_group_files_groups_by_directory_and_sorts() -> None:
    assert group_files(["a/x.py", "a/y.py", "README.md"]) == ". (1): README.md; a (2): x.py, y.py"


def test_group_files_sorts_directories_and_names() -> None:
    assert group_files(["z/b.py", "z/a.py", "m/c.py"]) == "m (1): c.py; z (2): a.py, b.py"


def test_group_files_uses_the_parent_directory_only() -> None:
    assert group_files(["a/b/c.py"]) == "a/b (1): c.py"


def test_group_files_of_nothing_is_empty() -> None:
    assert group_files([]) == ""


def report(**fields) -> dict:
    boundary = {"edge": "start", "sprint": 1, "stage": "sync", "hold": "sync_conflict", **fields}
    return {"role": "runner", "status": "boundary", "boundary": boundary}


def test_the_boundary_fields_carry_the_count_groups_commit_and_subject() -> None:
    fields = handover.report_fields(
        report(files=["a/x.py", "b.py"], commit="abc", subject="s"), None
    )
    assert fields["file_count"] == "2"
    assert fields["file_groups"] == ". (1): b.py; a (1): x.py"
    assert fields["commit"] == "abc" and fields["subject"] == "s"


def test_a_report_without_commit_or_files_has_empty_fields() -> None:
    fields = handover.report_fields(report(), None)
    assert fields["commit"] == "" and fields["subject"] == ""
    assert fields["file_count"] == "0" and fields["file_groups"] == ""


def test_a_run_state_without_sync_from_loads_an_empty_one() -> None:
    st = RunState(sprint=1)
    st.boundary = bd.Boundary(bd.Edge.START, 1)
    data = json.loads(st.to_json())
    del data["boundary"]["sync_from"]
    assert RunState.from_json(json.dumps(data)).boundary.sync_from == ""


def test_sync_from_round_trips() -> None:
    st = RunState(sprint=1)
    st.boundary = bd.Boundary(bd.Edge.START, 1, sync_from="a" * 40)
    assert RunState.from_json(st.to_json()).boundary.sync_from == "a" * 40


@pytest.mark.parametrize("name", ["commit", "subject"])
def test_the_boundary_text_fields_include_commit_and_subject(name: str) -> None:
    assert name in handover.BOUNDARY_TEXT
    assert "sync_from" in asdict(bd.Boundary(bd.Edge.START, 1))


def test_s151_a_rebase_fix_round_trips_with_its_conflict() -> None:
    conflict = bd.Failure(bd.Stage.REPLAY, bd.FixCase.REBASE_CONFLICT, "out", files=["a.py"])
    st = RunState(sprint=1)
    st.boundary = bd.Boundary(bd.Edge.END, 1, rebase_fix=bd.RebaseFix(conflict, "done", "n"))
    fix = RunState.from_json(st.to_json()).boundary.rebase_fix
    assert fix == bd.RebaseFix(conflict, "done", "n")
    assert isinstance(fix.conflict, bd.Failure)
    assert fix.conflict.case.value == "rebase_conflict" and fix.conflict.files == ["a.py"]
