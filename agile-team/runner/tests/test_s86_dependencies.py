"""s86: story dependencies as data: load, validate, route, warn (design DP1-DP14)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agile_team import cli, system
from agile_team import state as state_mod
from agile_team.dependencies import (
    CYCLE,
    MISMATCH,
    NOT_A_LIST,
    SELF,
    UNKNOWN,
    WAITING,
    WARNING,
    Declared,
    Moved,
    Proposal,
    above,
    apply,
    declared,
    find_cycle,
    graph_of,
    graph_refusal,
    inversions,
    listed,
    load_refusal,
    merged,
    mismatch_refusal,
    open_ids,
    shape_refusal,
    waiting_on,
    warning_texts,
    warnings,
)
from agile_team.gates import StoryState, StoryStatus
from agile_team.handover import Trigger as T
from agile_team.po_tools import Tools
from agile_team.priority import Change, Reorder, Source
from agile_team.router import Router
from agile_team.state import RunState

from .conftest import FakeQuery
from .fake_system import Done, FakeSystem
from .pipeline_helpers import add_story


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def st(sid: str, deps: list[str] | None = None, **kw) -> StoryState:
    return StoryState(sid, sid, "design", depends_on=deps or [], **kw)


def stories_of(**deps: list[str]) -> dict[str, StoryState]:
    return {sid: st(sid, d) for sid, d in deps.items()}


def put_file(config, sid: str, meta: str) -> None:
    path = config.stories_dir / f"{sid}.md"
    system.make_dirs(path.parent)
    ac = '  - id: AC1\n    text: "c"\n    environment: cli\n'
    system.write_text(path, f'---\nid: {sid}\ntitle: "A story"\n{meta}acceptance:\n{ac}---\nbody\n')


# ----- DP1: listed, state field ---------------------------------------------------


def test_listed_dedupes_keeping_first() -> None:
    assert listed(["s2", "s1", "s2"]) == ["s2", "s1"]
    assert listed([]) == []


@pytest.mark.parametrize("value", ["s1", {"a": 1}, [1], [True], ["s1", 2], None])
def test_listed_refuses_what_is_not_a_list_of_strings(value) -> None:
    assert listed(value) is None


def test_story_state_defaults_to_no_dependencies_and_old_state_loads() -> None:
    assert StoryState("s1", "t", "design").depends_on == []
    assert st("s1", ["s2"]).depends_on == ["s2"]


def test_old_state_json_without_depends_on_loads(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1")
    raw = {"stories": {"s1": {"id": "s1", "title": "t", "step": "design"}}}
    system.make_dirs(rt.config.run_dir)
    system.write_text(rt.config.run_dir / state_mod.STATE_FILE, json.dumps(raw))
    assert state_mod.load(rt.config.run_dir).stories["s1"].depends_on == []


# ----- DP2: declared, open_ids ----------------------------------------------------


def test_open_ids_leaves_out_done_stories() -> None:
    stories = {"s1": st("s1"), "s2": st("s2", status=StoryStatus.DONE)}
    assert open_ids(stories) == ["s1"]


def test_declared_reads_lists_and_skips_missing_files(make_runtime) -> None:
    config = make_runtime().config
    put_file(config, "s1", "id: s1\ndepends_on:\n  - s2  # why\n  - s3\n")
    found = declared(config, ["s1", "s9"])
    assert found == Declared({"s1": ["s2", "s3"]}, [])


def test_declared_no_frontmatter_or_no_key_means_empty(make_runtime) -> None:
    config = make_runtime().config
    put_file(config, "s1", "id: s1\n")
    system.write_text(config.stories_dir / "s2.md", "no frontmatter\n")
    assert declared(config, ["s1", "s2"]).lists == {"s1": [], "s2": []}


def test_declared_marks_bad_yaml_and_non_lists(make_runtime) -> None:
    config = make_runtime().config
    put_file(config, "s1", "depends_on: s2\n")
    put_file(config, "s2", "depends_on: [\n")
    put_file(config, "s3", "depends_on: [1]\n")
    found = declared(config, ["s1", "s2", "s3"])
    assert sorted(found.bad) == ["s1", "s2", "s3"]
    assert found.lists == {}


# ----- DP4: refusals --------------------------------------------------------------


def test_shape_refusal_names_the_stories_in_natural_order() -> None:
    assert shape_refusal(["s10", "s9"]) == NOT_A_LIST.format(ids="s9, s10")
    assert shape_refusal([]) is None


def test_graph_refusal_self() -> None:
    graph = {"s1": ["s1"], "s2": []}
    assert graph_refusal(graph, {"s1", "s2"}) == SELF.format(ids="s1")


def test_graph_refusal_self_lists_ids_in_natural_order() -> None:
    graph = {"s10": ["s10"], "s9": ["s9"]}
    assert graph_refusal(graph, set(graph)) == SELF.format(ids="s9, s10")


def test_graph_refusal_unknown_pairs_in_story_then_list_order() -> None:
    graph = {"s10": ["s30"], "s9": ["s40", "s2"], "s2": []}
    out = graph_refusal(graph, {"s2", "s9", "s10"})
    assert out == UNKNOWN.format(pairs="s9 on s40, s10 on s30")


def test_graph_refusal_cycle_and_ok() -> None:
    graph = {"s1": ["s2"], "s2": ["s3"], "s3": ["s1"]}
    assert graph_refusal(graph, set(graph)) == CYCLE.format(cycle="s1 -> s2 -> s3 -> s1")
    assert graph_refusal({"s1": ["s2"], "s2": []}, {"s1", "s2"}) is None


def test_dependency_on_a_done_story_is_valid_and_not_waiting() -> None:
    stories = {"s1": st("s1", ["s2"]), "s2": st("s2", status=StoryStatus.DONE)}
    assert graph_refusal(graph_of(stories), set(stories)) is None
    assert waiting_on(stories["s1"], stories) == []


def test_load_refusal_order_shape_self_unknown_cycle() -> None:
    stories = stories_of(s1=[], s2=[], s3=[])
    found = Declared({"s1": ["s1"], "s2": ["s9"], "s3": ["s2"]}, ["s3"])
    assert load_refusal(found, stories) == NOT_A_LIST.format(ids="s3")
    found = Declared({"s1": ["s1"], "s2": ["s9"]}, [])
    assert load_refusal(found, stories) == SELF.format(ids="s1")
    found = Declared({"s2": ["s9"], "s3": ["s2"]}, [])
    assert load_refusal(found, stories) == UNKNOWN.format(pairs="s2 on s9")
    found = Declared({"s2": ["s3"], "s3": ["s2"]}, [])
    assert load_refusal(found, stories) == CYCLE.format(cycle="s2 -> s3 -> s2")
    assert load_refusal(Declared({"s2": ["s1"]}, []), stories) is None


def test_merged_lets_loaded_lists_replace_state_lists() -> None:
    stories = stories_of(s1=["s2"], s2=[], s3=["s1"])
    assert merged(stories, Declared({"s1": []}, [])) == {"s1": [], "s2": [], "s3": ["s1"]}


def test_apply_sets_only_listed_stories() -> None:
    stories = stories_of(s1=["s2"], s2=[], s3=["s1"])
    apply(Declared({"s1": [], "s2": ["s3"]}, []), stories)
    assert [stories[i].depends_on for i in ("s1", "s2", "s3")] == [[], ["s3"], ["s1"]]


# ----- DP6: mismatch --------------------------------------------------------------


def test_mismatch_refusal_texts() -> None:
    found = Declared({"s5": ["s1", "s2"]}, [])
    out = mismatch_refusal(Proposal("s5", ["s1"]), found)
    assert out == MISMATCH.format(story="s5", file="s1, s2", given="s1")
    assert mismatch_refusal(Proposal("s5", ["s1", "s2"]), found) is None
    assert mismatch_refusal(Proposal("s5", ["s2", "s1"]), found) is not None  # order counts
    assert mismatch_refusal(Proposal("s6", ["s1"]), found) is None  # no file


# ----- DP7: cycles ----------------------------------------------------------------


def test_find_cycle_none() -> None:
    assert find_cycle({"s1": ["s2"], "s2": [], "s3": ["s1", "s2"]}) == []
    assert find_cycle({}) == []


def test_find_cycle_three() -> None:
    assert find_cycle({"s1": ["s2"], "s2": ["s3"], "s3": ["s1"]}) == ["s1", "s2", "s3", "s1"]


def test_find_cycle_starts_at_the_id_reached_again() -> None:
    graph = {"s1": ["s2"], "s2": ["s3"], "s3": ["s2"]}
    assert find_cycle(graph) == ["s2", "s3", "s2"]


def test_find_cycle_of_two_cycles_takes_the_one_from_the_lowest_id() -> None:
    graph = {"s9": ["s8"], "s8": ["s9"], "s2": ["s3"], "s3": ["s2"]}
    assert find_cycle(graph) == ["s2", "s3", "s2"]


def test_find_cycle_skips_ids_outside_the_graph() -> None:
    assert find_cycle({"s1": ["s77"]}) == []


def test_find_cycle_natural_order_not_text_order() -> None:
    graph = {"s10": ["s11"], "s11": ["s10"], "s9": ["s8"], "s8": ["s9"]}
    assert find_cycle(graph) == ["s8", "s9", "s8"]


# ----- DP8, DP11, DP12, DP13: waiting, above, warnings ----------------------------


def test_waiting_on_keeps_list_order_and_counts_missing_ones() -> None:
    stories = {
        "s1": st("s1", ["s4", "s2", "s3", "s9"]),
        "s2": st("s2"),
        "s3": st("s3", status=StoryStatus.DONE),
        "s4": st("s4"),
    }
    assert waiting_on(stories["s1"], stories) == ["s4", "s2", "s9"]


def test_above_lists_dependencies_ranked_after_the_story() -> None:
    a = st("a", ["c", "b", "z"])
    assert above(a, ["a", "b", "c"]) == ["c", "b"]
    assert above(a, ["b", "c", "a"]) == []
    assert above(a, ["b", "c"]) == []  # not in the queue


def test_inversions_and_warning_texts() -> None:
    stories = {"a": st("a", ["b"]), "b": st("b"), "c": st("c", ["a"])}
    queue = ["a", "b", "c"]
    assert inversions(queue, stories) == [("a", "b")]
    assert warning_texts(stories["a"], queue) == [WARNING.format(story="a", dependency="b")]
    assert warning_texts(stories["c"], queue) == []


def test_warnings_only_for_new_inversions_in_after_order() -> None:
    stories = {"a": st("a", ["b"]), "b": st("b"), "c": st("c", ["d"]), "d": st("d")}
    moved = Moved(["a", "b", "d", "c"], ["a", "b", "c", "d"])  # a>b existed; c>d is new
    assert warnings(moved, stories) == ["c is above d, which it depends on"]
    assert warnings(Moved(["b", "a"], ["b", "a"]), stories) == []


def test_text_constants() -> None:
    assert WARNING == "{story} is above {dependency}, which it depends on"
    assert WAITING == "waiting on {ids}"


# ----- DP2, DP5: Runtime.load_dependencies ----------------------------------------


def test_load_dependencies_applies_and_saves(make_runtime) -> None:
    rt = make_runtime()
    for sid in ("s1", "s2"):
        add_story(rt, sid)
    put_file(rt.config, "s2", "depends_on:\n  - s1\n")
    assert rt.load_dependencies() is None
    assert rt.state.stories["s2"].depends_on == ["s1"]
    assert state_mod.load(rt.config.run_dir).stories["s2"].depends_on == ["s1"]


def test_file_without_the_key_clears_the_state_list(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1")
    add_story(rt, "s2", depends_on=["s1"])
    put_file(rt.config, "s2", "id: s2\n")
    assert rt.load_dependencies() is None
    assert rt.state.stories["s2"].depends_on == []


def test_load_dependencies_refusal_changes_nothing_and_saves_nothing(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", depends_on=["s3"])
    add_story(rt, "s2")
    add_story(rt, "s3")
    state_mod.save(rt.config.run_dir, rt.state)
    put_file(rt.config, "s1", "depends_on: []\n")
    put_file(rt.config, "s2", "depends_on: [s2]\n")
    assert rt.load_dependencies() == SELF.format(ids="s2")
    assert rt.state.stories["s1"].depends_on == ["s3"]
    assert state_mod.load(rt.config.run_dir).stories["s1"].depends_on == ["s3"]


def test_done_stories_and_stories_without_files_keep_their_lists(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", depends_on=["s3"], status=StoryStatus.DONE)
    add_story(rt, "s2", depends_on=["s3"])
    add_story(rt, "s3")
    put_file(rt.config, "s1", "depends_on: []\n")
    assert rt.load_dependencies() is None
    assert rt.state.stories["s1"].depends_on == ["s3"]
    assert rt.state.stories["s2"].depends_on == ["s3"]


def test_bad_file_shape_is_refused(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1")
    put_file(rt.config, "s1", "depends_on: s2\n")
    assert rt.load_dependencies() == NOT_A_LIST.format(ids="s1")


# ----- DP3, DP5: cmd_start --------------------------------------------------------


def start_args(repo: Path, home: Path, *extra: str):
    return cli.build_parser().parse_args(
        ["--repo", str(repo), "--home", str(home), "start", *extra]
    )


def test_start_refuses_a_cycle_in_the_files(
    configured: Path, key_home: Path, fake: FakeSystem
) -> None:
    fake.programs.update({"pytest": "/bin/pytest", "ruff": "/bin/ruff"})
    run_dir = configured / ".team/run"
    stories = {"s1": st("s1"), "s2": st("s2")}
    state_mod.save(run_dir, RunState(stories=stories))
    stories_dir = configured / ".team/stories"
    system.make_dirs(stories_dir)
    system.write_text(stories_dir / "s1.md", "---\ndepends_on: [s2]\n---\n")
    system.write_text(stories_dir / "s2.md", "---\ndepends_on: [s1]\n---\n")
    q = FakeQuery("never")
    with pytest.raises(cli.CliError) as err:
        cli.cmd_start(start_args(configured, key_home, "--task", "t"), q)
    refusal = CYCLE.format(cycle="s1 -> s2 -> s1")
    assert str(err.value) == cli.START_REFUSED.format(refusal=refusal, folder=".team/stories")
    assert q.calls == []


def test_start_loads_the_lists_before_the_po_runs(
    configured: Path, key_home: Path, fake: FakeSystem
) -> None:
    fake.programs.update({"pytest": "/bin/pytest", "ruff": "/bin/ruff"})
    run_dir = configured / ".team/run"
    state_mod.save(run_dir, RunState(stories={"s1": st("s1"), "s2": st("s2")}))
    system.make_dirs(configured / ".team/stories")
    system.write_text(configured / ".team/stories/s2.md", "---\ndepends_on: [s1]\n---\n")
    assert cli.cmd_start(start_args(configured, key_home, "--task", "t"), FakeQuery("ok")) == 0
    assert state_mod.load(run_dir).stories["s2"].depends_on == ["s1"]


def test_start_refused_text() -> None:
    assert cli.START_REFUSED == "story files: {refusal}; fix depends_on in {folder}"


# ----- DP3, DP5: start_sprint -----------------------------------------------------


def open_two(t: Tools) -> None:
    for sid in ("s1", "s2"):
        put_file(t.runtime.config, sid, "")
        call(t.open_story({"id": sid, "title": sid}))


def test_start_sprint_with_a_bad_file_is_refused_and_does_not_begin(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_two(t)
    put_file(rt.config, "s1", "depends_on: [s2]\n")
    put_file(rt.config, "s2", "depends_on: [s1]\n")
    out = call(t.start_sprint({"goal": "G", "stories": ["s1", "s2"]}))
    assert out["status"] == "refused"
    assert CYCLE.format(cycle="s1 -> s2 -> s1") in json.dumps(out)
    assert rt.state.sprint == 0
    assert rt.state.stories["s1"].sprint is None


def test_start_sprint_loads_the_lists_first(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_two(t)
    put_file(rt.config, "s2", "depends_on: [s1]\n")
    out = call(t.start_sprint({"goal": "G", "stories": ["s1", "s2"]}))
    assert out["sprint"] == 1
    assert rt.state.stories["s2"].depends_on == ["s1"]


def test_start_sprint_existing_refusals_come_first(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_two(t)
    put_file(rt.config, "s1", "depends_on: [s1]\n")
    out = call(t.start_sprint({"goal": "G", "stories": ["s9"]}))
    assert out["status"] == "refused" and "s9" in out["reason"]


# ----- DP6: open_story ------------------------------------------------------------


def test_open_story_with_depends_on_records_it_and_the_event(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    put_file(rt.config, "s1", "")
    call(t.open_story({"id": "s1", "title": "A"}))
    put_file(rt.config, "s2", "depends_on: [s1]\n")
    out = call(t.open_story({"id": "s2", "title": "B", "depends_on": ["s1", "s1"]}))
    assert out["step"] == "design"
    assert rt.state.stories["s2"].depends_on == ["s1"]
    opened = [e for e in rt.events.events() if e.kind == "story-opened"][-1]
    assert opened.data["depends_on"] == ["s1"]


def test_open_story_without_depends_on_means_empty(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    put_file(rt.config, "s1", "")
    call(t.open_story({"id": "s1", "title": "A"}))
    assert rt.state.stories["s1"].depends_on == []
    opened = [e for e in rt.events.events() if e.kind == "story-opened"][-1]
    assert opened.data["depends_on"] == []


@pytest.mark.parametrize("bad", ["s1", [1], {"a": 1}])
def test_open_story_refuses_depends_on_that_is_not_a_list_of_ids(make_runtime, bad) -> None:
    rt = make_runtime()
    put_file(rt.config, "s2", "")
    out = call(Tools(rt).open_story({"id": "s2", "title": "B", "depends_on": bad}))
    assert out["status"] == "refused"
    assert out["reason"] == NOT_A_LIST.format(ids="s2")
    assert "s2" not in rt.state.stories


def test_open_story_refuses_a_file_list_that_differs(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    put_file(rt.config, "s1", "")
    call(t.open_story({"id": "s1", "title": "A"}))
    put_file(rt.config, "s2", "depends_on: [s1]\n")
    out = call(t.open_story({"id": "s2", "title": "B"}))
    assert out["reason"] == MISMATCH.format(story="s2", file="s1", given="")
    assert "s2" not in rt.state.stories


def test_open_story_accepts_the_same_list_as_the_file(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    put_file(rt.config, "s1", "")
    call(t.open_story({"id": "s1", "title": "A"}))
    put_file(rt.config, "s2", "depends_on: [s1]\n")
    call(t.open_story({"id": "s2", "title": "B", "depends_on": ["s1"]}))
    assert rt.state.stories["s2"].depends_on == ["s1"]


def test_open_story_refuses_a_bad_file(make_runtime) -> None:
    rt = make_runtime()
    put_file(rt.config, "s2", "depends_on: s1\n")
    out = call(Tools(rt).open_story({"id": "s2", "title": "B"}))
    assert out["reason"] == NOT_A_LIST.format(ids="s2")


def test_open_story_refuses_self_and_unknown(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    put_file(rt.config, "s2", "depends_on: [s2]\n")
    out = call(t.open_story({"id": "s2", "title": "B", "depends_on": ["s2"]}))
    assert out["reason"] == SELF.format(ids="s2")
    put_file(rt.config, "s2", "depends_on: [s7]\n")
    out = call(t.open_story({"id": "s2", "title": "B", "depends_on": ["s7"]}))
    assert out["reason"] == UNKNOWN.format(pairs="s2 on s7")
    assert rt.state.stories == {}


def test_open_story_duplicate_id_is_still_refused_first(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    put_file(rt.config, "s1", "")
    call(t.open_story({"id": "s1", "title": "A"}))
    out = call(t.open_story({"id": "s1", "title": "A", "depends_on": "bad"}))
    assert out["status"] == "refused" and out["reason"] != NOT_A_LIST.format(ids="s1")


def test_open_story_schema_takes_depends_on() -> None:
    from agile_team.po_tools import SCHEMAS

    assert "depends_on" in str(SCHEMAS["open_story"])
    assert "reloads depends_on" in str(SCHEMAS["start_sprint"])


# ----- DP9, DP10: the router ------------------------------------------------------


@pytest.fixture
def tracked(configured, fake: FakeSystem) -> None:
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))


@pytest.mark.usefixtures("tracked")
def test_router_skips_a_story_waiting_on_an_undone_one(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s9", sprint=None)
    add_story(rt, "s1", depends_on=["s9"])
    add_story(rt, "s2")
    assert Router(rt).next_work().story.id == "s2"


@pytest.mark.usefixtures("tracked")
def test_router_picks_it_once_the_dependency_is_done(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s9", sprint=None)
    add_story(rt, "s1", depends_on=["s9"])
    assert Router(rt).next_work() is None
    rt.state.stories["s9"].status = StoryStatus.DONE
    assert Router(rt).next_work().story.id == "s1"


@pytest.mark.usefixtures("tracked")
def test_router_does_not_continue_a_started_story_waiting_on_a_dependency(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s9", sprint=None)
    add_story(rt, "s1", "implement", commit="abc", depends_on=["s9"])
    assert Router(rt).next_work() is None


@pytest.mark.usefixtures("tracked")
def test_stall_line_says_waiting_on(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", "implement", hold="stopped")
    add_story(rt, "s2", depends_on=["s1"])
    p = asyncio.run(Router(rt).advance())
    assert p.kinds == [T.STALLED]
    assert p.lines == [
        "Nothing in sprint 1 can move.",
        "s1 at implement: held (stopped)",
        "s2 at design: waiting on s1",
    ]


@pytest.mark.usefixtures("tracked")
def test_stall_line_lists_waiting_ids_in_list_order(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s5", sprint=None)
    add_story(rt, "s4", sprint=None)
    add_story(rt, "s1", depends_on=["s5", "s4"])
    p = asyncio.run(Router(rt).advance())
    assert "s1 at design: waiting on s5, s4" in p.lines


@pytest.mark.usefixtures("tracked")
def test_a_hold_reads_before_waiting(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s9", sprint=None)
    add_story(rt, "s1", hold="questions", depends_on=["s9"])
    p = asyncio.run(Router(rt).advance())
    assert "s1 at design: held (questions)" in p.lines


# ----- DP12: reorder warnings -----------------------------------------------------


def two_stories(rt) -> None:
    add_story(rt, "s1", depends_on=["s2"])
    add_story(rt, "s2")
    rt.state.order = ["s2", "s1"]


def priority_events(rt) -> list:
    return [e for e in rt.events.events() if e.kind == "priority"]


def test_a_move_above_a_dependency_warns_and_is_not_refused(make_runtime) -> None:
    rt = make_runtime()
    two_stories(rt)
    after = rt.reorder(Reorder(Change.SET, ["s1", "s2"]))
    assert after == ["s1", "s2"]
    data = priority_events(rt)[-1].data
    assert data["warnings"] == ["s1 is above s2, which it depends on"]


def test_an_old_inversion_is_not_repeated(make_runtime) -> None:
    rt = make_runtime()
    two_stories(rt)
    rt.reorder(Reorder(Change.SET, ["s1", "s2"]))
    rt.reorder(Reorder(Change.SET, ["s1", "s2"]))
    assert priority_events(rt)[-1].data["warnings"] == []


def test_a_clean_move_has_empty_warnings_and_other_keys_stay(make_runtime) -> None:
    rt = make_runtime()
    two_stories(rt)
    rt.reorder(Reorder(Change.SET, ["s2", "s1"], reason="r"))
    data = priority_events(rt)[-1].data
    assert data["warnings"] == []
    assert data["change"] == "set" and data["order"] == ["s2", "s1"] and data["reason"] == "r"


def test_human_requests_carry_warnings_too(make_runtime) -> None:
    rt = make_runtime()
    two_stories(rt)
    rt.state.order = ["s2", "s1"]
    rt.state.stories["s1"].sprint = None
    rt.state.stories["s2"].sprint = None
    rt.reorder(Reorder(Change.MOVE, ["s1", "s2"], "s1", "x", source=Source.HUMAN))
    event = priority_events(rt)[-1]
    assert event.role is None and event.data["warnings"]


def test_po_move_story_carries_warnings(make_runtime) -> None:
    rt = make_runtime()
    two_stories(rt)
    call(Tools(rt).move_story({"story": "s1", "position": 1, "reason": "urgent"}))
    assert priority_events(rt)[-1].data["warnings"] == ["s1 is above s2, which it depends on"]
