"""s135: the PO schedules and requests stories; it no longer writes them (AC5, AC6)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agile_team import (
    ci,
    dependencies,
    frontmatter,
    guard,
    ops_review,
    po_tools,
    priority,
    relay,
    request_files,
    shares,
    sprint_add,
    story_admin,
    story_spec,
)
from agile_team.events import EventKind
from agile_team.git_ops import Git
from agile_team.po_tools import Tools
from agile_team.priority import After, Priority, Source
from agile_team.sprint_add import Addition, SprintAdd
from agile_team.state import StoryState

from .fake_system import Done
from .story_setup import Opening, opened

STORY_FILE = ".team/stories/s1.md"


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def ask(t: Tools, **evidence) -> dict:
    args = {"summary": "tests hang", "evidence": {"output": "boom"} | evidence}
    return call(t.request_story(args))


# ----- AC5: the guard refuses story files ------------------------------------------


def scope(repo: Path, role: str = "product-owner") -> guard.Scope:
    return guard.Scope(role, repo, [".team/stories/**", ".team/po/**", "**"])


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
def test_every_role_is_refused_the_story_files(repo: Path, tool) -> None:
    for role in ("product-owner", "developer"):
        found = guard.check_tool_use(
            scope(repo, role), guard.ToolCall(tool, {guard.WRITE_TOOLS[tool]: STORY_FILE})
        )
        assert found == f"{role} may not write {STORY_FILE}; only the runner writes it"


def test_story_files_are_runner_files() -> None:
    assert guard.STORY_FILES == ".team/stories/**"
    assert guard.RUNNER_FILES == (guard.pending_tests.REGISTRY, guard.STORY_FILES)


def test_a_story_file_in_a_steps_tree_is_out_of_scope(repo: Path, fake) -> None:
    fake.reply(("git", "status"), Done(0, " M .team/stories/s1.md\0"))
    audit = guard.audit_step(Git(repo), scope(repo))
    assert audit.out_of_scope == [STORY_FILE] and audit.in_scope == []


def test_other_team_files_stay_writable(repo: Path) -> None:
    call_ = guard.ToolCall("Write", {"file_path": ".team/po/notes.md"})
    assert guard.check_tool_use(scope(repo), call_) is None


def test_the_po_role_writes_only_its_notes(make_runtime) -> None:
    assert make_runtime().book.spec("product-owner").write == [".team/po/**"]


# ----- open_story is gone (S3, S4) --------------------------------------------------


def test_open_story_is_removed() -> None:
    assert "open_story" not in po_tools.SCHEMAS
    assert "mcp__team__open_story" not in po_tools.tool_names()
    assert not hasattr(Tools, "open_story")
    assert po_tools.STORY_ARGS == {}


def test_the_dependency_proposal_helpers_are_removed() -> None:
    for name in ("Proposal", "mismatch_refusal", "MISMATCH"):
        assert not hasattr(dependencies, name)


def test_no_text_names_open_story() -> None:
    texts = [
        po_tools.UNKNOWN_BUG,
        story_admin.UNKNOWN,
        priority.UNKNOWN,
        dependencies.UNKNOWN,
        story_spec.PROBLEMS[story_spec.Problem.NO_FILE],
        ci.CI_OURS_REFUSAL,
        ops_review.UNFILED,
    ]
    assert [t for t in texts if "open_story" in t] == []


def test_the_new_texts() -> None:
    assert (
        story_admin.UNKNOWN == "unknown story {story!r}; ask the liaison for it with request_story"
    )
    assert po_tools.UNKNOWN_BUG == (
        "unknown story {story!r}; ask the liaison for it with request_story, "
        "then record_ci_bug once the runner opens it"
    )
    assert priority.UNKNOWN == "unknown stories: {ids}; ask the liaison for them with request_story"
    assert dependencies.UNKNOWN == (
        "depends_on names unknown stories: {pairs}; only opened stories can be listed"
    )
    assert story_spec.PROBLEMS[story_spec.Problem.NO_FILE] == "no story file"
    assert "request_story" in ci.CI_OURS_REFUSAL and "request_story" in ops_review.UNFILED


# ----- request_story (S5) -----------------------------------------------------------


def test_the_schema_and_the_kind() -> None:
    desc, schema = po_tools.SCHEMAS["request_story"]
    assert schema == {"summary": str, "evidence": dict}
    assert desc.startswith("Ask the liaison to write a story")
    assert "mcp__team__request_story" in po_tools.tool_names()
    assert "story-request" in relay.KINDS
    assert EventKind.STORY_REQUEST == "story-request"
    assert EventKind.STORY_AMENDED == "story-amended" and EventKind.STORY_REFUSED == "story-refused"
    assert po_tools.MAX_OUTPUT == 6000


def test_a_good_request_posts_one_message_and_emits_one_event(make_runtime) -> None:
    rt = make_runtime()
    opened(rt, Opening("s1", "one"))
    t = Tools(rt)
    out = ask(t, story="s1", step="implement", files=["a.py", "b.py"], output="boom\n")
    assert out["status"] == "requested" and out["message"] == "m1"
    assert out["next"] == "the liaison writes the story; the runner opens it and tells you its id"
    [msg] = rt.relay.messages()
    assert msg.kind == "story-request" and msg.stories == ["s1"]
    assert msg.text == (
        "The PO asks for a story: tests hang\nStory: s1 at implement\nFiles: a.py, b.py\n"
        "Failing output:\nboom\n"
    )
    [ev] = [e for e in rt.events.events() if e.kind == EventKind.STORY_REQUEST]
    assert ev.role == "product-owner" and ev.story == "s1"
    assert ev.data == {
        "message": "m1",
        "summary": "tests hang",
        "step": "implement",
        "files": ["a.py", "b.py"],
    }


def test_a_request_outside_any_story(make_runtime) -> None:
    rt = make_runtime()
    out = ask(Tools(rt))
    assert out["status"] == "requested"
    [msg] = rt.relay.messages()
    assert msg.stories == [] and "Story: none\nFiles: none\n" in msg.text
    [ev] = [e for e in rt.events.events() if e.kind == EventKind.STORY_REQUEST]
    assert ev.story is None


def test_long_output_keeps_its_tail_with_the_cut_head(make_runtime) -> None:
    rt = make_runtime()
    ask(Tools(rt), output="x" * 1000 + "y" * 6000)
    [msg] = rt.relay.messages()
    tail = msg.text.split("Failing output:\n", 1)[1]
    assert tail == "[first 1000 characters cut]\n" + "y" * 6000


def test_output_at_the_limit_is_kept_whole(make_runtime) -> None:
    rt = make_runtime()
    ask(Tools(rt), output="z" * 6000)
    assert rt.relay.messages()[0].text.endswith("Failing output:\n" + "z" * 6000)


def refusal_of(t: Tools, args: dict) -> str:
    out = call(t.request_story(args))
    assert out["status"] == "refused"
    assert t.runtime.relay.messages() == []
    return out["reason"]


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"summary": "  ", "evidence": {"output": "x"}}, "a summary is required"),
        (
            {"summary": "s", "evidence": "text"},
            "evidence must be an object {story, step, output, files}",
        ),
        (
            {"summary": "s", "evidence": {"story": 3, "output": "x"}},
            "evidence.story must be a string",
        ),
        (
            {"summary": "s", "evidence": {"step": 3, "output": "x"}},
            "evidence.step must be a string",
        ),
        ({"summary": "s", "evidence": {"output": 3}}, "evidence.output must be a string"),
        (
            {"summary": "s", "evidence": {"story": "s9", "output": "x"}},
            "unknown story 's9'",
        ),
        (
            {"summary": "s", "evidence": {"output": "  "}},
            "evidence.output must hold the failing output",
        ),
        ({"summary": "s", "evidence": {}}, "evidence.output must hold the failing output"),
        (
            {"summary": "s", "evidence": {"output": "x", "files": "a.py"}},
            "evidence.files must be a list of paths",
        ),
        (
            {"summary": "s", "evidence": {"output": "x", "files": ["a", 2]}},
            "evidence.files must be a list of paths",
        ),
    ],
)
def test_the_refusals(make_runtime, args, reason) -> None:
    assert refusal_of(Tools(make_runtime()), args) == reason


def test_the_first_refusal_wins(make_runtime) -> None:
    args = {"summary": "", "evidence": 5}
    assert refusal_of(Tools(make_runtime()), args) == "a summary is required"
    args = {"summary": "s", "evidence": {"story": "s9", "output": ""}}
    assert refusal_of(Tools(make_runtime()), args) == "unknown story 's9'"


def test_a_request_blocks_nothing(make_runtime) -> None:
    rt = make_runtime()
    opened(rt, Opening("s1", "one"))
    before = rt.state.stories["s1"].status
    ask(Tools(rt), story="s1")
    assert rt.state.stories["s1"].status == before and rt.state.stories["s1"].hold is None


# ----- sprint_add and Priority.with_after -------------------------------------------


def sprint_runtime(make_runtime):
    rt = make_runtime()
    for sid in ("s1", "s2", "s3"):
        opened(rt, Opening(sid, sid))
    rt.state.sprint, rt.state.order = 1, ["s1", "s2", "s3"]
    rt.state.stories["s1"].sprint = 1
    return rt


def test_the_addition_defaults_to_the_po() -> None:
    add = Addition(["s2"], "why")
    assert add.source is Source.PO and add.after == ""
    assert Source.LIAISON == "liaison" and priority.SOURCE_ROLES[Source.LIAISON] == "liaison"


def test_the_moved_texts_still_resolve_from_po_tools() -> None:
    for name in (
        "ADD_NEEDS_REASON",
        "NO_OPEN_SPRINT",
        "ALREADY_IN_SPRINT",
        "SPRINT_REFUSAL_BOUNDARY",
    ):
        assert getattr(po_tools, name) is getattr(sprint_add, name)
    assert po_tools.held_text is sprint_add.held_text


def test_refusals_keep_their_texts(make_runtime) -> None:
    rt = sprint_runtime(make_runtime)
    adder = SprintAdd(rt)
    assert adder.refusal(Addition(["s2"], "")) == po_tools.ADD_NEEDS_REASON.format(sprint=1)
    assert adder.refusal(Addition(["s1"], "x")) == po_tools.ALREADY_IN_SPRINT.format(
        sprint=1, ids="s1"
    )
    assert adder.refusal(Addition(["s2"], "x")) is None and adder.boundary_refusal() is None
    rt.state.sprint = 0
    assert adder.refusal(Addition(["s2"], "x")) == po_tools.NO_OPEN_SPRINT.format(sprint=0)


def test_apply_by_the_po_logs_the_po_role(make_runtime) -> None:
    rt = sprint_runtime(make_runtime)
    order = SprintAdd(rt).apply(Addition(["s3"], "why"))
    assert rt.state.stories["s3"].sprint == 1 and order == ["s3", "s1", "s2"]
    [ev] = [e for e in rt.events.events() if e.kind == EventKind.SPRINT_ADD]
    assert ev.role == "product-owner" and ev.data == {
        "sprint": 1,
        "stories": ["s3"],
        "reason": "why",
    }


def test_apply_with_after_places_right_after_it(make_runtime) -> None:
    rt = sprint_runtime(make_runtime)
    SprintAdd(rt).apply(Addition(["s3"], "why", Source.LIAISON, "s1"))
    assert rt.state.order == ["s1", "s3", "s2"]
    [ev] = [e for e in rt.events.events() if e.kind == EventKind.SPRINT_ADD]
    assert ev.role == "liaison"


def stories(*ids: str) -> list[StoryState]:
    return [StoryState(i, i, "design") for i in ids]


def test_with_after_inserts_right_after_the_anchor() -> None:
    p = Priority(["s1", "s2", "s3"], [])
    assert p.with_after(After("s4", "s1"), stories("s1", "s2", "s3", "s4")) == [
        "s1",
        "s4",
        "s2",
        "s3",
    ]


def test_with_after_appends_when_the_anchor_is_not_in_the_plan() -> None:
    p = Priority(["s1", "s2"], [])
    assert p.with_after(After("s3", "s9"), stories("s1", "s2", "s3")) == ["s1", "s2", "s3"]


def test_with_after_moves_a_story_that_is_already_listed() -> None:
    p = Priority(["s1", "s2", "s3"], [])
    assert p.with_after(After("s1", "s3"), stories("s1", "s2", "s3")) == ["s2", "s3", "s1"]


# ----- story_spec DRAFT and frontmatter ---------------------------------------------

BODY = (
    '---\ntitle: "T"\nacceptance:\n  - id: AC1\n    text: "x"\n    environment: cli\n'
    "---\n\nUser story.\n"
)


def read(text: str, kind: story_spec.Kind = story_spec.Kind.DRAFT, story: str = ""):
    return story_spec.parse(story_spec.Source(story, "d.md", text, kind), ["cli"])


def test_a_clean_draft_has_no_problems_and_no_id() -> None:
    out = read(BODY)
    assert out.problems == () and out.spec is not None and out.spec.title == "T"


def test_a_draft_reports_each_runner_key() -> None:
    assert story_spec.RUNNER_KEYS == ("id", "shared")
    assert story_spec.PROBLEMS[story_spec.Problem.RUNNER_KEY] == (
        "{key} is written by the runner; remove it"
    )
    out = read(BODY.replace("title:", "id: s3\nshared: []\ntitle:", 1))
    assert out.problems == (
        "d.md: id is written by the runner; remove it",
        "d.md: shared is written by the runner; remove it",
    )


def test_a_filed_source_still_needs_its_id() -> None:
    out = read(BODY, story_spec.Kind.FILED, "s1")
    assert out.problems and "id" in out.problems[0]
    assert (
        read(BODY.replace("title:", "id: s1\ntitle:", 1), story_spec.Kind.FILED, "s1").problems
        == ()
    )


def test_the_default_kind_is_filed() -> None:
    assert story_spec.Source("s1", "f", "x").kind is story_spec.Kind.FILED


def test_frontmatter_parse() -> None:
    meta, body = frontmatter.parse("---\nid: s1\nn: 2\n---\n\nBody\n")
    assert meta == {"id": "s1", "n": 2} and body.strip() == "Body"
    assert frontmatter.parse("no frontmatter") is None
    assert frontmatter.parse("---\nk: [unclosed\n---\nx\n") is None


def test_without_key_drops_an_indented_block() -> None:
    head = "id: s1\nacceptance:\n  - id: AC1\n    text: x\ntitle: T\n"
    assert frontmatter.without_key(head, "acceptance") == "id: s1\ntitle: T\n"


def test_without_key_drops_a_block_whose_items_sit_at_column_zero() -> None:
    head = "id: s1\nacceptance:\n- id: AC1\n  text: x\n- id: AC2\ntitle: T\n"
    assert frontmatter.without_key(head, "acceptance") == "id: s1\ntitle: T\n"


def test_without_key_leaves_other_text_alone() -> None:
    head = "id: s1\ntitle: T\n"
    assert frontmatter.without_key(head, "acceptance") == head


def test_request_files_moved_out_of_shares() -> None:
    assert shares.bad_request is request_files.bad_request
    assert shares.BadRequest is request_files.BadRequest
    fields = request_files.Fields({"n": request_files.NUMBER})
    assert isinstance(fields.loaded("not json"), str)
    assert fields.loaded('{"n": 1}') == {"n": 1}
    assert fields.problem({"n": "x"}, "n") is not None and fields.problem({"n": 1}, "n") is None
