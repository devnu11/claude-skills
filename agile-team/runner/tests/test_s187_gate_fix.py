"""s187: a gate fix names its gated commit and tree, and an empty done doesn't count."""

import json

import pytest
from agile_team import loops, owners
from agile_team.boundary import StepKind
from agile_team.events import Event, EventKind
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import Git
from agile_team.owners import Fix, FixRecord, Item, Source, Tree, TreeState
from agile_team.state import RunState

from .conftest import handoff
from .fake_system import FAKE_HEAD, Done
from .test_s92_dispatch import (
    E2E_FAIL,
    E2E_FILE,
    events_of,
    fix_step,
    next_work,
    routed,
    run,
    runtime,
    story_of,
    tracked,  # noqa: F401  (autouse fixture of the s92 dispatch tests)
)

GATED = "a" * 40
HEAD = "b" * 40
C1, C2 = "c" * 40, "d" * 40
PATH = "/work/s1"
ITEM = Item(E2E_FILE, Source.TEST, [E2E_FILE], ["l1"])


def fix(gated="", unchanged=0) -> Fix:
    return Fix("integration-tester", [ITEM], gated=gated, unchanged=unchanged)


def tree(state, since=(), head=HEAD) -> Tree:
    return Tree(PATH, head, state, since)


# ---- owners: the Tree section ---------------------------------------------------


def test_short_is_twelve_characters() -> None:
    assert owners.SHORT == 12 and owners.format_short(GATED) == "a" * 12


def test_a_same_head_tree_section() -> None:
    lines = owners.format_tree_lines(fix(GATED), tree(TreeState.SAME, head=GATED))
    assert lines[0] == "Tree:"
    assert (
        f"- The gate ran on commit {'a' * 12} in {PATH}. Your working directory is that tree: "
        "run every command there and never cd out of it."
    ) in lines
    assert f"- Its head is still {'a' * 12}." in lines


def test_a_moved_head_lists_the_commits_since_in_order() -> None:
    since = ((C1, "fix(s1): one"), (C2, "fix(s1): two"))
    lines = owners.format_tree_lines(fix(GATED), tree(TreeState.MOVED, since))
    text = "\n".join(lines)
    assert f"- Its head is now {'b' * 12}. Commits since the gate, oldest first:" in lines
    assert f"    - {'c' * 12} fix(s1): one" in lines and f"    - {'d' * 12} fix(s1): two" in lines
    assert text.index("fix(s1): one") < text.index("fix(s1): two")


def test_a_rewritten_head_says_the_branch_was_rewritten() -> None:
    lines = owners.format_tree_lines(fix(GATED), tree(TreeState.REWRITTEN))
    want = (
        f"- Its head is now {'b' * 12}, which doesn't contain {'a' * 12}: "
        "its branch was rewritten since the gate ran."
    )
    assert want in lines


def test_an_unrecorded_gate_commit_names_the_path_and_head() -> None:
    lines = owners.format_tree_lines(fix(""), tree(TreeState.UNRECORDED))
    assert (
        f"- The gate's commit wasn't recorded. Your working directory is {PATH}: "
        "run every command there and never cd out of it."
    ) in lines
    assert f"- Its head is {'b' * 12}." in lines
    assert not any(line.startswith("- The gate ran on commit") for line in lines)


def test_an_unchanged_fix_ends_with_the_changed_nothing_line() -> None:
    last = owners.format_tree_lines(fix(GATED, 2), tree(TreeState.SAME, head=GATED))[-1]
    assert "Your last 2 fix step(s) on these items handed off done with no commit" in last
    assert "hand off changes_requested and name the commands you ran." in last


def test_a_fix_never_unchanged_has_no_changed_nothing_line() -> None:
    lines = owners.format_tree_lines(fix(GATED), tree(TreeState.SAME, head=GATED))
    assert not any("handed off done with no commit" in line for line in lines)


def test_mark_gated_sets_only_fixes_without_one() -> None:
    fixes = [fix(""), fix(GATED), fix("")]
    owners.mark_gated(fixes, HEAD)
    assert [f.gated for f in fixes] == [HEAD, GATED, HEAD]


def test_mark_gated_on_no_fixes_is_a_no_op() -> None:
    owners.mark_gated([], HEAD)


def test_load_fix_round_trips_gated_and_unchanged() -> None:
    from dataclasses import asdict

    back = owners.load_fix(json.loads(json.dumps(asdict(fix(GATED, 1)), default=str)))
    assert (back.gated, back.unchanged) == (GATED, 1)


def test_an_old_fix_dict_loads_with_empty_gated_and_zero_unchanged() -> None:
    old = {"role": "r", "items": [{"path": "p", "source": "test"}]}
    back = owners.load_fix(old)
    assert (back.gated, back.unchanged) == ("", 0)


def test_fix_records_default_gated_and_head_to_empty() -> None:
    record = FixRecord("r", ["f"], None)
    assert (record.gated, record.head) == ("", "")


# ---- git_ops.list_after ---------------------------------------------------------


def test_list_after_gives_the_commits_after_a_sha_oldest_first(repo, fake) -> None:
    fake.reply(("git", "log", "--reverse"), Done(0, f"{C1}\x1fone\n{C2}\x1ftwo\n"))
    assert Git(repo).list_after(GATED) == [(C1, "one"), (C2, "two")]
    argv = next(c.argv for c in fake.commands if "--reverse" in c.argv)
    assert f"{GATED}..HEAD" in argv


def test_list_after_is_empty_at_head(repo, fake) -> None:
    fake.reply(("git", "log", "--reverse"), Done(0, ""))
    assert Git(repo).list_after(GATED) == []


# ---- dispatch: stamping gated and head ------------------------------------------


def test_a_routed_gate_stamps_each_fix_and_the_event_with_the_head(make_runtime) -> None:
    rt, _ = runtime(make_runtime, coverage=(1, E2E_FAIL))
    run(rt, "developer")
    assert [f.gated for f in story_of(rt).fixes] == [FAKE_HEAD]
    assert events_of(rt, "gate")[-1].data["head"] == FAKE_HEAD


def test_an_escalation_event_carries_the_head(make_runtime) -> None:
    rt, script = runtime(make_runtime, coverage=(1, E2E_FAIL))
    script.writes["integration-tester"] = (E2E_FILE, "def test_keep():\n    assert 1\n")
    run(rt, "developer")
    fix_step(rt, "integration-tester")
    run(rt, "developer")
    head = rt.git.head()
    assert head != FAKE_HEAD and events_of(rt, "escalation")[-1].data["head"] == head


# ---- dispatch: the brief's Tree section -----------------------------------------


def start_brief(rt) -> str:
    return events_of(rt, "step-start")[-1].data["brief"]


def test_the_gate_fix_brief_and_prompt_end_with_the_tree_section(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    fix_step(rt, "integration-tester")
    brief = start_brief(rt)
    assert "Tree:" in brief
    assert f"The gate ran on commit {FAKE_HEAD[:12]} in {rt.config.repo}" in brief
    assert f"- Its head is still {FAKE_HEAD[:12]}." in brief


def test_a_moved_worktree_lists_the_commit_since_the_gate(make_runtime, fake) -> None:
    rt, _ = routed(make_runtime, handoff())
    head = "e" * 40
    rt.worktree_of = "s1"
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, head + "\n"))
    fake.reply(("git", "merge-base"), Done(0))
    fake.reply(("git", "log", "--reverse"), Done(0, f"{head}\x1fchore: moved\n"))
    fix_step(rt, "integration-tester")
    brief = start_brief(rt)
    assert f"- Its head is now {'e' * 12}." in brief and f"    - {'e' * 12} chore: moved" in brief


def test_a_rewritten_worktree_says_so(make_runtime, fake) -> None:
    rt, _ = routed(make_runtime, handoff())
    rt.worktree_of = "s1"
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, "f" * 40 + "\n"))
    fake.reply(("git", "merge-base"), Done(1))
    fix_step(rt, "integration-tester")
    assert "its branch was rewritten since the gate ran" in start_brief(rt)


def test_a_fix_queued_before_s187_is_unrecorded(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    story_of(rt).fixes[0].gated = ""
    fix_step(rt, "integration-tester")
    assert "The gate's commit wasn't recorded." in start_brief(rt)


# ---- dispatch: an empty done is not a fix ---------------------------------------


def test_an_empty_done_keeps_the_fix_queued_with_no_round(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    gate = fix_step(rt, "integration-tester")["gate"]
    s = story_of(rt)
    assert gate["verdict"] == "route" and (s.step, s.rounds) == ("implement", 0)
    assert [(f.role, f.unchanged) for f in s.fixes] == [("integration-tester", 1)]
    assert "handed off done with no commit, so the items still stand" in gate["reason"]
    assert f"the gate ran on {FAKE_HEAD[:12]}" in gate["reason"] and E2E_FILE in gate["reason"]
    work = next_work(rt)
    assert (work.role, work.kind) == ("integration-tester", StepKind.GATE_FIX)


def test_the_next_brief_after_an_empty_done_has_the_changed_nothing_line(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    fix_step(rt, "integration-tester")
    fix_step(rt, "integration-tester")
    assert "Your last 1 fix step(s) on these items handed off done" in start_brief(rt)


def test_a_second_empty_done_escalates_to_the_manager(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    fix_step(rt, "integration-tester")
    gate = fix_step(rt, "integration-tester")["gate"]
    s = story_of(rt)
    assert gate["verdict"] == "escalate" and s.status is StoryStatus.NEEDS_MANAGER
    assert s.fixes == [] and s.rounds == 0
    [event] = events_of(rt, "escalation")
    assert "handed off done with no commit" in event.data["reason"]


def test_a_done_fix_with_a_commit_pops_as_before(make_runtime) -> None:
    rt, script = routed(make_runtime, handoff())
    script.writes["integration-tester"] = (E2E_FILE, "def test_keep():\n    assert 1\n")
    report = fix_step(rt, "integration-tester")
    assert "gate" not in report and story_of(rt).fixes == []
    assert next_work(rt).role == "developer"


def test_find_unchanged_fix_is_none_when_a_commit_was_made() -> None:
    from agile_team.dispatch import find_unchanged_fix

    s = StoryState("s1", "T", "implement", sprint=1)
    s.fixes = [fix(GATED)]
    assert find_unchanged_fix(s, "abc") is None
    assert s.fixes[0].unchanged == 0


def test_find_unchanged_fix_routes_with_the_count_raised_and_leaves_state_alone() -> None:
    from agile_team.dispatch import find_unchanged_fix

    rest = Fix("developer", [ITEM])
    s = StoryState("s1", "T", "implement", sprint=1)
    s.fixes = [fix(GATED), rest]
    outcome = find_unchanged_fix(s, None)
    assert outcome.verdict.value == "route"
    assert [(f.role, f.unchanged) for f in outcome.fixes] == [
        ("integration-tester", 1),
        ("developer", 0),
    ]
    assert s.fixes[0].unchanged == 0


# ---- dispatch: the record and its event -----------------------------------------


def test_record_fix_writes_gated_and_head_on_record_and_event(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    fix_step(rt, "integration-tester")
    [record] = story_of(rt).fixed
    assert (record.gated, record.head) == (FAKE_HEAD, FAKE_HEAD)
    data = events_of(rt, "gate-fix")[-1].data
    assert (data["gated"], data["head"]) == (FAKE_HEAD, FAKE_HEAD)


def test_state_json_keeps_gated_unchanged_and_head() -> None:
    s = StoryState("s1", "T", "implement", sprint=1)
    s.fixes = [fix(GATED, 1)]
    s.fixed = [FixRecord("integration-tester", [E2E_FILE], None, gated=GATED, head=HEAD)]
    state = RunState()
    state.stories["s1"] = s
    back = RunState.from_json(state.to_json()).stories["s1"]
    assert (back.fixes, back.fixed) == (s.fixes, s.fixed)


# ---- loops: the Manager's view ---------------------------------------------------


def record(gated, commit, head="") -> FixRecord:
    return FixRecord("integration-tester", [E2E_FILE], commit, gated=gated, head=head)


def test_gate_fix_is_a_history_kind() -> None:
    assert "gate-fix" in loops.HISTORY_KINDS


def test_fix_rounds_group_by_gated_in_first_seen_order() -> None:
    rounds = loops.list_fix_rounds(
        [record(GATED, None, HEAD), record(HEAD, C1, C1), record(GATED, C2, C2)]
    )
    assert [r["gated"] for r in rounds] == ["a" * 12, "b" * 12]
    assert rounds[0]["fixes"] == [
        {"role": "integration-tester", "files": [E2E_FILE], "commit": "none", "head": "b" * 12},
        {"role": "integration-tester", "files": [E2E_FILE], "commit": "d" * 12, "head": "d" * 12},
    ]


def test_fix_rounds_mark_a_missing_sha_unrecorded() -> None:
    [only] = loops.list_fix_rounds([record("", None)])
    assert only["gated"] == "unrecorded" and only["fixes"][0]["head"] == "unrecorded"


def test_fix_rounds_of_no_records_is_empty() -> None:
    assert loops.list_fix_rounds([]) == []


def test_manager_view_has_fix_rounds_and_the_gate_fix_events() -> None:
    from agile_team.loops import Setback

    s = StoryState("s1", "T", "implement", sprint=1)
    s.fixed = [record(GATED, None, GATED)]
    s.streak = [Setback("implement", "implement", "developer", "route", "role", "r", "e1")]
    s.repeated = "same again"
    events = [
        Event(EventKind.GATE_FIX, "integration-tester", "s1", {"commit": None}, id="e2"),
        Event(EventKind.GATE_FIX, "integration-tester", "s2", {"commit": None}, id="e3"),
    ]
    view = loops.manager_view(s, events)
    assert view["fix_rounds"][0]["fixes"][0]["commit"] == "none"
    assert [e["id"] for e in view["events"]] == ["e2"]


@pytest.mark.parametrize("n", [0, 1])
def test_unchanged_defaults_to_zero_on_a_new_fix(n) -> None:
    assert fix().unchanged == 0 and fix(unchanged=n).unchanged == n
