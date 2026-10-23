"""s178: parallel stories get distinct requirement ids (reserved per story, checked at design).

`git ls-tree` is scripted on the fake system (a unit test runs no process); files in a
story's worktree are written through ``system``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agile_team import config as config_mod
from agile_team import gates, requirements, state, system
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import Git
from agile_team.requirement_ids import BLOCK_SIZE, RequirementIds, list_block
from agile_team.workspaces import Workspaces

from .fake_system import Done, FakeSystem

FOLDER = "docs/requirements"


def _names(*numbers: int) -> str:
    return "".join(f"{FOLDER}/REQ-{n:03d}.md\n" for n in numbers)


class Sprint:
    """A sprint on the fake system: the head's ids, stories with branches and worktrees."""

    def __init__(self, fake: FakeSystem, repo: Path, head: range) -> None:
        self.fake, self.config = fake, config_mod.load(repo)
        fake.reply(("git", "ls-tree"), Done(0, ""))
        self.head(*head)
        self.state = state.RunState(sprint=1, story_branches=True)
        self.main = Git(repo)

    def head(self, *numbers: int) -> None:
        self.fake.reply(("git", "ls-tree", "--name-only", "HEAD"), Done(0, _names(*numbers)))

    def add(self, story_id: str, **fields: object) -> StoryState:
        story = StoryState(story_id, story_id, "design", sprint=1, **fields)  # type: ignore[arg-type]
        self.state.stories[story_id] = story
        return story

    def branch(self, ref: str, *numbers: int) -> None:
        self.fake.reply(("git", "ls-tree", "--name-only", ref), Done(0, _names(*numbers)))

    def gone(self, ref: str) -> None:
        self.fake.reply(("git", "ls-tree", "--name-only", ref), Done(128, "fatal: not a tree"))

    def worktree(self, story_id: str, *numbers: int) -> None:
        folder = self._config_of(story_id).requirements_dir
        system.make_dirs(folder)
        for n in numbers:
            system.write_text(folder / f"REQ-{n:03d}.md", "x\n")

    def _config_of(self, story_id: str) -> config_mod.Config:
        path = Workspaces(self.main, self.config).get_path(story_id)
        return self.config.get_worktree_config(path)

    def ids(self, story_id: str) -> RequirementIds:
        runtime = SimpleNamespace(
            state=self.state, config=self._config_of(story_id), main=self.main
        )
        return RequirementIds(runtime)  # type: ignore[arg-type]


def make(fake: FakeSystem, configured: Path, head: range = range(1, 11)) -> Sprint:
    return Sprint(fake, configured, head)


# -- requirements helpers --------------------------------------------------------


def test_parse_numbers_takes_stems_and_skips_others() -> None:
    paths = ["docs/requirements/REQ-007.md", "REQ-12.md", "README.md", "REQ-x.md"]
    assert requirements.parse_numbers(paths) == {7, 12}
    assert requirements.parse_numbers([]) == set()


def test_format_id_pads_to_three() -> None:
    assert requirements.format_id(7) == "REQ-007"
    assert requirements.format_id(1234) == "REQ-1234"


def test_list_numbers_reads_a_folder_and_a_missing_one(scratch: Path) -> None:
    assert requirements.list_numbers(scratch / "none") == set()
    system.write_text(scratch / "REQ-004.md", "x")
    system.write_text(scratch / "notes.md", "x")
    assert requirements.list_numbers(scratch) == {4}


def test_offer_section_has_head_ids_and_index() -> None:
    checked = requirements.Checked(FOLDER, (), {})
    offer = requirements.Offer("s1", "REQ-011", "REQ-011", "REQ-015")
    text = requirements.format_offer_section(checked, offer)
    assert text.startswith(requirements.coverage_section(checked, "s1"))
    assert "REQ-011.md, the next free id" in text
    assert "REQ-011 to REQ-015" in text
    plain = requirements.design_section(checked, "s1")
    assert "the next free id" in plain and "REQ-011" not in plain


def test_list_block_is_five_numbers_or_none() -> None:
    assert list(list_block(11)) == [11, 12, 13, 14, 15]
    assert len(list_block(3)) == BLOCK_SIZE == 5
    assert len(list_block(0)) == 0


# -- AC1: reserving ----------------------------------------------------------------


def test_parallel_briefs_get_distinct_blocks(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    first, second = sprint.add("s1"), sprint.add("s2")
    one = sprint.ids("s1").reserve(first)
    two = sprint.ids("s2").reserve(second)
    assert (one.next_free, one.first, one.last) == ("REQ-011", "REQ-011", "REQ-015")
    assert (two.next_free, two.first, two.last) == ("REQ-016", "REQ-016", "REQ-020")
    assert (first.req_block, second.req_block) == (11, 16)
    assert one.story == "s1"


def test_branch_ids_count(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s2", branch="s2/b", base_sha="base")
    sprint.branch("s2/b", *range(1, 12))
    mine = sprint.add("s1")
    assert sprint.ids("s1").reserve(mine).next_free == "REQ-012"


def test_uncommitted_worktree_ids_count(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s2")
    sprint.worktree("s2", 11)
    mine = sprint.add("s1")
    assert sprint.ids("s1").reserve(mine).next_free == "REQ-012"


def test_kept_block_survives_a_second_brief(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    mine = sprint.add("s1")
    sprint.ids("s1").reserve(mine)
    sprint.add("s2", req_block=16)
    assert sprint.ids("s1").reserve(mine).first == "REQ-011"
    assert mine.req_block == 11


def test_block_taken_elsewhere_moves_above_everything(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    mine = sprint.add("s1", req_block=11)
    sprint.add("s2", branch="s2/b", base_sha="base")
    sprint.branch("s2/b", *range(1, 14))
    assert sprint.ids("s1").reserve(mine).first == "REQ-014"
    sprint.head(*range(1, 20))
    assert sprint.ids("s1").reserve(mine).first == "REQ-020"


def test_whole_block_written_offers_above_it(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    mine = sprint.add("s1")
    sprint.worktree("s1", 11, 12, 13, 14, 15)
    assert sprint.ids("s1").reserve(mine).next_free == "REQ-016"


def test_next_free_is_lowest_unwritten_in_block(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    mine = sprint.add("s1")
    sprint.worktree("s1", 11, 12)
    assert sprint.ids("s1").reserve(mine).next_free == "REQ-013"


# -- AC3: freed ids ----------------------------------------------------------------


def test_cancelled_story_frees_its_block(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s2", req_block=11, status=StoryStatus.CANCELLED)
    mine = sprint.add("s1")
    assert sprint.ids("s1").reserve(mine).first == "REQ-011"


def test_story_moved_out_of_sprint_frees_its_block(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    other = sprint.add("s2", req_block=11)
    other.sprint = None
    mine = sprint.add("s1")
    assert sprint.ids("s1").reserve(mine).first == "REQ-011"


def test_deleted_branch_holds_nothing(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s2", branch="s2/b", base_sha="base")
    sprint.gone("s2/b")
    mine = sprint.add("s1")
    assert sprint.ids("s1").reserve(mine).first == "REQ-011"


# -- AC2: clashes ------------------------------------------------------------------


def test_clash_with_sprint_head(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s1", base_sha="base")
    sprint.branch("base", *range(1, 10))
    sprint.worktree("s1", 10)
    lines = sprint.ids("s1").list_clashes("s1")
    assert lines[0].startswith("s1 adds requirement ids that other work already holds")
    assert "- REQ-010 is already used on the sprint head" in lines[1:]


def test_clash_with_another_open_branch_names_the_story(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s1", base_sha="base")
    sprint.add("s2", branch="s2/b", base_sha="base")
    sprint.branch("base", *range(1, 11))
    sprint.branch("s2/b", *range(1, 12))
    sprint.worktree("s1", 11)
    assert "- REQ-011 is already used by s2" in sprint.ids("s1").list_clashes("s1")


def test_clash_with_another_stories_block(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s1", base_sha="base", req_block=11)
    sprint.add("s2", base_sha="base", req_block=16)
    sprint.branch("base", *range(1, 11))
    sprint.worktree("s1", 16)
    assert "- REQ-016 is reserved by s2" in sprint.ids("s1").list_clashes("s1")


def test_id_in_own_block_is_not_reported(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s1", base_sha="base", req_block=11)
    sprint.add("s2", branch="s2/b", base_sha="base")
    sprint.branch("base", *range(1, 11))
    sprint.branch("s2/b", *range(1, 12))
    sprint.worktree("s1", 11)
    assert sprint.ids("s1").list_clashes("s1") == []


def test_no_clash_unknown_story_or_no_base(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    sprint.add("s1", base_sha="base")
    sprint.add("s3")
    sprint.branch("base", *range(1, 11))
    sprint.worktree("s1", 11)
    assert sprint.ids("s1").list_clashes("s1") == []
    assert sprint.ids("s1").list_clashes("nope") == []
    sprint.worktree("s3", 10)
    assert sprint.ids("s3").list_clashes("s3") == []


def test_clash_retry_brief_names_a_free_id(fake: FakeSystem, configured: Path) -> None:
    sprint = make(fake, configured)
    mine = sprint.add("s1", base_sha="base", req_block=11)
    sprint.add("s2", branch="s2/b", base_sha="base")
    sprint.branch("base", *range(1, 11))
    sprint.branch("s2/b", *range(1, 14))
    sprint.worktree("s1", 11)
    assert sprint.ids("s1").reserve(mine).first == "REQ-014"


# -- the design gate ---------------------------------------------------------------


def _checks(clashed: object | None = None) -> gates.Checks:
    checks = gates.Checks({"test": "T"}, 95.0, lambda command: (0, ""))
    checks.design_file = lambda story: f"docs/design/{story}.md"
    checks.read = lambda path: "## Files\n\n- src/a.py\n"
    checks.traced = lambda story: ["trace line"]
    if clashed is not None:
        checks.clashed = clashed  # type: ignore[assignment]
    return checks


def test_designed_lists_clash_lines_after_trace_lines() -> None:
    checks = _checks(lambda story: [f"- clash for {story}"])
    out = checks.designed(StoryState("s1", "t", "design"))
    assert out.verdict is gates.Verdict.BOUNCE and out.bounce_to == "design"
    assert out.reason.splitlines() == ["trace line", "- clash for s1"]


def test_exempt_story_never_asks_for_clashes() -> None:
    def boom(story: str) -> list[str]:
        raise AssertionError("asked")

    exempt = StoryState("s1", "t", "design", trace=gates.Trace.EXEMPT)
    assert _checks(boom).designed(exempt).verdict is gates.Verdict.PASS


def test_default_checks_report_no_clashes() -> None:
    assert _checks().clashed("s1") == []


def test_req_block_round_trips_and_defaults_to_zero() -> None:
    st = state.RunState(sprint=1)
    st.stories["s1"] = StoryState("s1", "t", "design", req_block=11)
    back = state.RunState.from_json(st.to_json())
    assert back.stories["s1"].req_block == 11
    assert StoryState("s2", "t", "design").req_block == 0
