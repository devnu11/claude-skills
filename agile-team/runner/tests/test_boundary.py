"""s29: boundary data, texts and pure helpers (no I/O)."""

from dataclasses import asdict

import pytest
from agile_team import boundary as b
from agile_team.ci import CiResult, CiVerdict
from agile_team.events import Event, EventKind
from agile_team.loops import Author


def failure(**kw) -> b.Failure:
    base = {"stage": b.Stage.CHECK, "case": b.FixCase.TEAM_CHECK, "reason": "test failed"}
    return b.Failure(**{**base, **kw})


def test_enum_values() -> None:
    assert [e.value for e in b.Edge] == ["start", "end"]
    assert [e.value for e in b.Stage] == [
        "sync",
        "check",
        "push",
        "ci",
        "rebase",
        "push-rebased",
        "ci-rebased",
    ]
    assert [e.value for e in b.StepKind] == [
        "role",
        "boundary",
        "team-fix",
        "gate-fix",
    ]
    assert [e.value for e in b.BoundaryHold] == [
        "sync_conflict",
        "escalated",
        "reviewed",
        "push_permission",
        "push_rejected",
        "ci_failed",
        "ci_infra",
        "main_broken",
        "ci_pending",
        "error",
        "fix_handover",
    ]
    assert [e.value for e in b.FixCase] == ["team_check"]
    assert [e.value for e in b.Permission] == ["unasked", "yes", "no"]
    assert not hasattr(b, "CheckState")
    assert {e.value for e in b.BoundaryOutcome} == {
        "skipped", "current", "rebased", "conflict", "pass", "fail", "escalate", "held",
        "pushed", "local", "error", "done", "continued", "permission", "rerun", "superseded",
        "refused",
    }  # fmt: skip


def test_boundary_defaults_and_coercion() -> None:
    bd = b.Boundary("end", 3, stage="push", hold="escalated")
    assert bd.edge is b.Edge.END and bd.stage is b.Stage.PUSH
    assert bd.hold is b.BoundaryHold.ESCALATED
    fresh = b.Boundary(b.Edge.START, 1)
    assert fresh.stage is b.Stage.SYNC and fresh.hold is None and fresh.failure is None
    assert (fresh.streak, fresh.rounds, fresh.escalated, fresh.note) == ([], 0, None, "")
    assert not hasattr(fresh, "restack")


def test_stack_entry_and_upstream_state_defaults() -> None:
    e = b.StackEntry(1, "team/sprint-1", "a", "b")
    assert e.pr is None and e.pushed == "" and e.as_is == "" and e.stories == []
    assert e.supersedes == [] and not hasattr(e, "check") and not hasattr(e, "checked")
    u = b.UpstreamState()
    assert u.push is b.Permission.UNASKED and u.stack == [] and u.closed == 0 and u.last_end == ""


def test_next_stage_end_goes_through_every_stage() -> None:
    bd = b.Boundary(b.Edge.END, 1)
    seen = []
    while (nxt := b.next_stage(bd)) is not None:
        seen.append(nxt)
        bd.stage = nxt
    assert seen == [
        b.Stage.CHECK,
        b.Stage.PUSH,
        b.Stage.CI,
        b.Stage.REBASE,
        b.Stage.PUSH_REBASED,
        b.Stage.CI_REBASED,
    ]


def test_next_stage_start_skips_every_end_only_stage() -> None:
    bd = b.Boundary(b.Edge.START, 1, stage=b.Stage.CHECK)
    assert b.next_stage(bd) is None
    bd.stage = b.Stage.SYNC
    assert b.next_stage(bd) is b.Stage.CHECK


def test_stage_order_is_the_gate_order() -> None:
    """AC4.1: the rebase comes after the as-built push and its CI."""
    order = list(b.STAGES)
    assert order.index(b.Stage.PUSH) < order.index(b.Stage.CI) < order.index(b.Stage.REBASE)
    assert order.index(b.Stage.REBASE) < order.index(b.Stage.PUSH_REBASED)
    assert order.index(b.Stage.PUSH_REBASED) < order.index(b.Stage.CI_REBASED)
    assert (b.Stage.PUSH_REBASED.value, b.Stage.CI_REBASED.value) == ("push-rebased", "ci-rebased")


def test_fix_kinds_table() -> None:
    assert b.FIX_KINDS == {b.FixCase.TEAM_CHECK: b.StepKind.TEAM_FIX}
    assert set(b.FIX_LINES) == {b.FixCase.TEAM_CHECK}
    assert frozenset(b.STAGES[2:]) == b.END_ONLY
    assert b.Stage.SYNC not in b.END_ONLY and b.Stage.CHECK not in b.END_ONLY


def test_setback_key_uses_edge_stage_and_normalised_reason() -> None:
    bd = b.Boundary(b.Edge.END, 2)
    a = b.setback(bd, failure(reason="FAILED test_x in 1.2s at /tmp/a1"))
    c = b.setback(bd, failure(reason="FAILED test_x in 9.9s at /tmp/zz"))
    assert (a.step, a.to_step, a.role, a.verdict, a.author) == (
        "end",
        "check",
        "runner",
        "bounce",
        Author.RUNNER,
    )
    assert a.key == c.key and a.key.startswith("end>check ")
    assert b.setback(bd, failure(reason="other thing")).key != a.key


def test_held_text() -> None:
    assert b.held_text(b.Boundary(b.Edge.END, 1)) == ""
    held = b.Boundary(b.Edge.END, 1, hold=b.BoundaryHold.ERROR)
    assert b.held_text(held) == ", held: error"


def make_ctx() -> b.FixContext:
    return b.FixContext(team="agile-team", target="origin/main", sha="abc")


def test_fix_brief_team_check() -> None:
    bd = b.Boundary(b.Edge.START, 4, stage=b.Stage.CHECK)
    bd.failure = failure(reason="lint failed (exit 1)")
    brief = b.fix_brief(bd, make_ctx())
    assert brief.startswith(b.FIX_HEADING.format(sprint=4, edge="start", stage="check"))
    assert "The full checks failed on the team branch agile-team at abc." in brief
    assert "lint failed (exit 1)" in brief
    assert brief.endswith("```")
    assert "From the PO" not in brief


def test_fix_context_has_three_fields() -> None:
    assert [f for f in b.FixContext.__dataclass_fields__] == ["team", "target", "sha"]


def test_fix_brief_carries_the_po_note_last() -> None:
    bd = b.Boundary(b.Edge.END, 2, note="the human fixed the token")
    bd.failure = failure()
    assert b.fix_brief(bd, make_ctx()).endswith("\n\nFrom the PO: the human fixed the token")


def test_output_block_format() -> None:
    assert b.OUTPUT_BLOCK == "Output:\n```\n{output}\n```"


def test_exact_strings() -> None:
    assert not hasattr(b, "MERGE_MESSAGE")
    for gone in ("STACKED_LINE", "MERGED_NOTE", "NOTHING_REPORT"):
        assert not hasattr(b, gone)
    assert b.SYNC_OFF == "[upstream] remote is empty"
    assert b.NO_REMOTE.format(remote="origin") == "no remote 'origin'"
    assert b.NO_TARGET.format(target="origin/main") == "origin/main does not exist"
    assert b.NOT_PERMITTED == "the human said no to pushing"
    assert b.BOUNDARY_ROLE == "runner" and b.FIX_ROLE == "devops"


def test_manager_view_shape_and_event_filter() -> None:
    first = failure(reason="boom 1")
    bd = b.Boundary(b.Edge.END, 2, escalated="boom 1", failure=first)
    s1 = b.setback(bd, first)
    s1.event = "e0005"
    s2 = b.setback(bd, failure(reason="boom 2"))
    s2.event = "e0008"
    bd.streak = [s1, s2]
    events = [
        Event(EventKind.BOUNDARY, "runner", None, {"stage": "check"}, id="e0004"),
        Event(EventKind.BOUNDARY, "runner", None, {"stage": "check"}, id="e0005"),
        Event(EventKind.STEP_END, "devops", None, {}, id="e0006"),
        Event(EventKind.STEP_END, "devops", "s1", {}, id="e0007"),
        Event(EventKind.STEP_END, "developer", None, {}, id="e0009"),
    ]
    view = b.manager_view(bd, events)
    assert view["edge"] == "end" and view["sprint"] == 2 and view["stage"] == "check"
    assert view["reason"] == "boom 1" and view["count"] == 2 and view["key"] == s2.key
    assert view["history"] == [asdict(s1), asdict(s2)]
    assert [e["id"] for e in view["events"]] == ["e0005", "e0006"]


def test_due_holds_kind_role_and_brief() -> None:
    d = b.Due(b.StepKind.BOUNDARY, "runner", "")
    assert (d.kind, d.role, d.brief) == (b.StepKind.BOUNDARY, "runner", "")


@pytest.mark.parametrize("case", list(b.FixCase))
def test_every_fix_case_has_lines(case) -> None:
    assert len(b.FIX_LINES[case]) == 2


# ----- s151: the gate in code, the helpers and the texts ---------------------


def green_entry(**kw) -> b.StackEntry:
    entry = b.StackEntry(1, "team/sprint-1", "a", "b", pushed="p1", as_is="p1")
    entry.ci = CiResult(1, "u", "p1", CiVerdict.GREEN)
    for key, value in kw.items():
        setattr(entry, key, value)
    return entry


def test_own_entry_finds_the_sprints_entry_or_none() -> None:
    one, two = b.StackEntry(1, "x1", "a", "b"), b.StackEntry(2, "x2", "a", "b")
    assert b.own_entry([one, two], 2) is two
    assert b.own_entry([one, two], 3) is None
    assert b.own_entry([], 1) is None


def test_rebase_refusal_is_empty_only_on_green_at_the_pushed_head() -> None:
    assert b.rebase_refusal(green_entry()) == ""


def test_rebase_refusal_without_an_entry() -> None:
    assert b.rebase_refusal(None) == b.NO_AS_IS


def test_rebase_refusal_without_a_ci_read_names_the_branch_and_sha() -> None:
    reason = b.rebase_refusal(green_entry(ci=None))
    assert reason == b.REBASE_WAITS.format(branch="team/sprint-1", sha="p1", verdict="no CI read")


def test_rebase_refusal_without_a_push_says_nothing_pushed() -> None:
    entry = green_entry(pushed="", as_is="")
    entry.ci = None
    assert "nothing pushed" in b.rebase_refusal(entry)


@pytest.mark.parametrize("verdict", [v for v in CiVerdict if v is not CiVerdict.GREEN])
def test_rebase_refusal_for_every_other_verdict(verdict) -> None:
    entry = green_entry()
    entry.ci = CiResult(1, "u", "p1", verdict)
    assert b.rebase_refusal(entry) == b.REBASE_WAITS.format(
        branch="team/sprint-1", sha="p1", verdict=verdict
    )


def test_rebase_refusal_for_green_on_another_sha() -> None:
    entry = green_entry()
    entry.ci = CiResult(1, "u", "other", CiVerdict.GREEN)
    assert b.rebase_refusal(entry).startswith("the rebase waits for green CI")


def test_s151_texts_are_exact() -> None:
    assert b.NOTHING_NEW == (
        "sprint {sprint} added no commit since the last sprint end; nothing to push or rebase"
    )
    assert b.SUPERSEDED_NOTE == (
        "sprint {old}'s PR #{pr} is superseded: sprint {sprint}'s branch holds its commits"
    )
    assert b.NO_AS_IS == "no as-built push is recorded for this sprint"
    assert b.REBASE_UNCHANGED == "the rebase changed nothing; {branch} stays at {sha}"
    assert b.NOT_REBASED == (
        " The team branch is not rebased onto {target}: the rebase waits for green CI."
    )
    assert b.LOCAL_REPORT == (
        "Sprint {sprint}'s branch {branch} is checked but not pushed ({why}). No CI result exists."
    )
    assert "rebased onto {target} ({sha})" in b.REBASED_PUSHED_REPORT
    assert "The PR is NOT ready; do not merge it." in b.REBASED_NOT_GREEN
    assert "nothing is rebased" in b.CI_RED_HELD
    assert "rebased onto {target} only once it is green" in b.PUSHED_REPORT
    assert b.SUPERSEDES_LINE.startswith("Holds the commits of earlier sprint PRs {prs}")
    assert 'Merge with "Rebase and merge".' in b.PR_BODY
    assert "{supersedes}" in b.PR_BODY and "{stories}" in b.PR_BODY


def test_legacy_tables() -> None:
    assert b.LEGACY_STAGES == {"review": b.Stage.PUSH, "restack": b.Stage.PUSH}
    assert frozenset({"review_check", "review_conflict"}) == b.RETIRED_CASES
    assert b.RETIRED_ENTRY_KEYS == ("checked", "check")
    assert b.RETIRED_BOUNDARY_KEYS == ("restack",)


def test_big_pr_note_no_longer_names_the_bottom_of_the_stack() -> None:
    assert "bottom of the stack" not in b.BIG_PR_NOTE
    assert "Merge it by fast-forward" in b.BIG_PR_NOTE
