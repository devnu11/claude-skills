"""s2: requirement changes through the runtime: settle_tree, the bounce, events, auto-accept,
the architect's stop check, the hand-over and the CLI."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import cli, gates, guard, handover, stages, stop_checks, system
from agile_team import requirement_changes as rc
from agile_team.dashboard import snapshot
from agile_team.dispatch import Plan, StepRequest
from agile_team.git_ops import CO_AUTHOR, Authored, Git, with_trailer
from agile_team.roles import Handoff, HandoffError, parse_handoff
from agile_team.stop_checks import StopCheck, StopChecks

from .conftest import FakeQuery, handoff, write_story
from .fake_system import Done, FakeSystem
from .pipeline_helpers import add_story

FOLDER = "docs/requirements"
HELD = "chore(team): architect's unexplained requirement edits, held back"


@pytest.fixture(autouse=True)
def tracked(configured: Path, fake: FakeSystem) -> None:
    fake.track()


def req(req_id: str, covers: str = "", status: str = "active", body: str = "Words.") -> str:
    items = f"covers: [{covers}]\n" if covers else ""
    return f"---\nid: {req_id}\ntitle: T\nstatus: {status}\n{items}---\n\n{body}\n"


def path_of(req_id: str) -> str:
    return f"{FOLDER}/{req_id}.md"


def seed(rt, req_id: str, text: str) -> None:
    """A requirement already committed at HEAD."""
    repo = rt.config.repo
    system.make_dirs((repo / path_of(req_id)).parent)
    system.write_text(repo / path_of(req_id), text)
    Git(repo).commit([path_of(req_id)], f"seed {req_id}")


def writes(rt, files: dict[str, str | None]) -> Callable[[], None]:
    """A query action that writes (or, for None, removes) files."""

    def action() -> None:
        for rel, text in files.items():
            target = rt.config.repo / rel
            if text is None:
                system.remove(target)
                continue
            system.make_dirs(target.parent)
            system.write_text(target, text)

    return action


def tracked_diff(fake: FakeSystem, *entries: tuple[str, str]) -> None:
    """Script ``git diff --name-status -z`` (the fake tree does not model diff)."""
    fake.reply(("git", "diff"), Done(0, "".join(f"{k}\0{p}\0" for k, p in entries)))


def architect(make_runtime, text: str, files: dict | None = None, story: str | None = "s1"):
    """A runtime whose architect writes ``files`` and answers ``text``; the story at design."""
    holder: dict[str, Any] = {}
    query = FakeQuery(text, action=lambda: holder["action"]())
    rt = make_runtime(query)
    holder["action"] = writes(rt, files or {})
    if story:
        env = rt.config.environments[0].name
        add_story(rt, story, "design")
        write_story(rt.config, story, env)
    return rt


def step(rt, story: str | None = "s1") -> dict:
    return asyncio.run(rt.run_role(StepRequest("architect", "go", story)))


def message_of(fake: FakeSystem, sha: str) -> str:
    return next(c.message for c in fake.tree.commits if c.sha == sha)


def events(rt, kind: str) -> list:
    return [e for e in rt.events.events() if e.kind == kind]


C9_KEYS = ("requirement_changes", "redesigned_stories", "affected_done_stories", "held_back")


# ----- the handoff field (AC2, T6) -----


def test_handoff_parses_requirement_changes() -> None:
    parsed = parse_handoff(handoff(requirement_changes={"REQ-003": "why"}))
    assert isinstance(parsed, Handoff) and parsed.requirement_changes == {"REQ-003": "why"}


def test_handoff_without_the_field_has_none() -> None:
    assert parse_handoff(handoff()).requirement_changes == {}


@pytest.mark.parametrize("bad", [["REQ-003"], "why", {"REQ-003": 5}, {"REQ-003": None}, 7])
def test_handoff_rejects_a_field_that_is_not_ids_to_reasons(bad: Any) -> None:
    with pytest.raises(HandoffError, match="requirement_changes must map requirement ids"):
        parse_handoff(handoff(requirement_changes=bad))


# ----- trailers (AC3, T13) -----


def test_with_trailer_puts_requirement_trailers_in_one_block_with_the_co_author() -> None:
    text = with_trailer("s\n\nb", ["Requirement-Changed: REQ-001: x"])
    assert text.endswith(f"\n\nRequirement-Changed: REQ-001: x\n{CO_AUTHOR}\n")
    assert text.startswith("s\n\nb\n\n")


def test_with_trailer_without_trailers_is_what_it_was() -> None:
    assert with_trailer("subject\n") == f"subject\n\n{CO_AUTHOR}\n"
    assert with_trailer("subject", []) == f"subject\n\n{CO_AUTHOR}\n"


def test_authored_trailers_default_to_none() -> None:
    assert Authored("m").trailers == ()


# ----- no candidates (AC1, T5) -----


def test_a_step_without_requirement_files_runs_no_diff_or_show(
    make_runtime, fake: FakeSystem
) -> None:
    rt = architect(make_runtime, handoff(), {"docs/architecture.md": "x"}, story=None)
    report = step(rt, None)
    assert report["status"] == "done" and report["commit"]
    assert not [c for c in fake.commands if {"diff", "show"} & set(c.argv)]
    assert not [k for k in C9_KEYS if k in report]


# ----- landing (AC1, AC3, AC4, T11, T15) -----


def land(make_runtime, fake: FakeSystem, reasons: dict | None = None):
    rt = architect(make_runtime, handoff(requirement_changes=reasons or {}), story="s1")
    seed(rt, "REQ-003", req("REQ-003"))
    seed(rt, "REQ-010", req("REQ-010"))
    tracked_diff(fake, ("M", path_of("REQ-003")), ("M", path_of("REQ-010")))
    rt.query_fn.action = writes(
        rt,
        {
            path_of("REQ-003"): req("REQ-003", body="edited"),
            path_of("REQ-010"): req("REQ-010", body="edited"),
            path_of("REQ-005"): req("REQ-005"),
            "docs/design/s1.md": "design",
        },
    )
    return rt


def test_explained_and_added_requirements_land_with_trailers_in_natural_order(
    make_runtime, fake: FakeSystem
) -> None:
    rt = land(make_runtime, fake, {"REQ-003": "  because\n now ", "REQ-010": "ten"})
    report = step(rt)
    assert report["requirement_changes"] == [
        {"id": "REQ-003", "change": "changed", "reason": "because now"},
        {"id": "REQ-005", "change": "added", "reason": "new requirement"},
        {"id": "REQ-010", "change": "changed", "reason": "ten"},
    ]
    message = message_of(fake, report["commit"])
    assert message.rstrip().endswith(
        "Requirement-Changed: REQ-003: because now\n"
        "Requirement-Changed: REQ-005: new requirement\n"
        "Requirement-Changed: REQ-010: ten\n"
        f"{CO_AUTHOR}"
    )
    assert not [
        k for k in ("held_back", "redesigned_stories", "affected_done_stories") if k in report
    ]


def test_each_landed_change_emits_an_event_with_the_step_commit(
    make_runtime, fake: FakeSystem
) -> None:
    rt = land(make_runtime, fake, {"REQ-003": "because", "REQ-010": "ten"})
    report = step(rt)
    found = events(rt, "requirement-changed")
    assert [e.data for e in found] == [
        {"id": "REQ-003", "change": "changed", "reason": "because", "sha": report["commit"]},
        {"id": "REQ-005", "change": "added", "reason": "new requirement", "sha": report["commit"]},
        {"id": "REQ-010", "change": "changed", "reason": "ten", "sha": report["commit"]},
    ]
    assert {(e.role, e.story) for e in found} == {("architect", "s1")}


def test_the_dashboard_history_reads_the_commit_sha_from_the_event(
    make_runtime, fake: FakeSystem
) -> None:
    rt = land(make_runtime, fake, {"REQ-003": "because", "REQ-010": "ten"})
    report = step(rt)
    raw = [json.loads(json.dumps(e.__dict__)) for e in events(rt, "requirement-changed")]
    history = snapshot._history(raw)
    assert [row["sha"] for row in history["REQ-003"]] == [report["commit"]]
    assert history["REQ-005"][0]["change"] == "added"


def test_a_reason_for_an_id_that_is_not_a_candidate_is_ignored(
    make_runtime, fake: FakeSystem
) -> None:
    rt = architect(
        make_runtime, handoff(requirement_changes={"REQ-999": "stray"}), {"docs/a.md": "x"}
    )
    report = step(rt)
    assert "Requirement-Changed" not in message_of(fake, report["commit"])
    assert events(rt, "requirement-changed") == []


# ----- unexplained edits are held back (AC2, T8-T10) -----


def held_run(make_runtime, fake: FakeSystem, text: str | None = None, ids=("REQ-003",)):
    rt = architect(make_runtime, text or handoff(), story="s1")
    for rid in ids:
        seed(rt, rid, req(rid))
    tracked_diff(fake, *[("M", path_of(rid)) for rid in ids])
    files = {path_of(rid): req(rid, body="edited") for rid in ids}
    rt.query_fn.action = writes(rt, {**files, "docs/design/s1.md": "design"})
    return rt, step(rt)


def test_an_unexplained_change_is_held_back_and_the_step_bounces(
    make_runtime, fake: FakeSystem
) -> None:
    rt, report = held_run(make_runtime, fake)
    assert report["status"] == "bad_handoff"
    assert report["reason"] == rc.UNEXPLAINED.format(
        explain="explain change to REQ-003", sha=report["held_back"]
    )
    assert report["reason"].startswith("explain change to REQ-003 (your edits are held back in ")
    held = next(c for c in fake.tree.commits if c.sha == report["held_back"])
    assert held.subject() == HELD and held.paths() == {path_of("REQ-003")}
    step_commit = next(c for c in fake.tree.commits if c.sha == report["commit"])
    assert path_of("REQ-003") not in step_commit.paths()
    assert system.read_text(rt.config.repo / path_of("REQ-003")) == req("REQ-003")
    assert events(rt, "requirement-changed") == []
    assert rt.state.stories["s1"].rounds == 1 and rt.state.stories["s1"].step == "design"
    assert events(rt, "step-end")[0].data["status"] == "bad_handoff"
    assert events(rt, "step-end")[0].data["summary"] == report["reason"]
    assert "Requirement-Changed" not in held.message


def test_the_held_back_edit_is_reverted_after_it_is_committed(
    make_runtime, fake: FakeSystem
) -> None:
    held_run(make_runtime, fake)
    subjects = [c.subject() for c in fake.tree.commits]
    held_at = subjects.index(HELD)
    assert subjects[held_at + 1].startswith(f'Revert "{HELD}')


def test_several_unexplained_changes_are_named_in_natural_order_and_others_still_land(
    make_runtime, fake: FakeSystem
) -> None:
    rt = architect(make_runtime, handoff(requirement_changes={"REQ-005": "ok"}))
    for rid in ("REQ-004", "REQ-003", "REQ-005"):
        seed(rt, rid, req(rid))
    tracked_diff(fake, *[("M", path_of(r)) for r in ("REQ-004", "REQ-003", "REQ-005")])
    rt.query_fn.action = writes(
        rt,
        {
            path_of("REQ-004"): req("REQ-004", body="e"),
            path_of("REQ-003"): req("REQ-003", body="e"),
            path_of("REQ-005"): req("REQ-005", body="e"),
            path_of("REQ-006"): req("REQ-006"),
        },
    )
    report = step(rt)
    assert report["reason"].startswith("explain change to REQ-003; explain change to REQ-004 (")
    commit = next(c for c in fake.tree.commits if c.sha == report["commit"])
    assert commit.paths() == {path_of("REQ-005"), path_of("REQ-006")}
    assert [r["id"] for r in report["requirement_changes"]] == ["REQ-005", "REQ-006"]
    assert [e.data["id"] for e in events(rt, "requirement-changed")] == ["REQ-005", "REQ-006"]


def test_a_malformed_handoff_with_a_changed_requirement_keeps_both_messages(
    make_runtime, fake: FakeSystem
) -> None:
    _, report = held_run(make_runtime, fake, text="no handoff block here")
    assert report["status"] == "bad_handoff"
    assert "; explain change to REQ-003 (your edits are held back in " in report["reason"]
    assert not report["reason"].startswith("explain")


def test_a_blank_reason_counts_as_missing(make_runtime, fake: FakeSystem) -> None:
    _, report = held_run(make_runtime, fake, text=handoff(requirement_changes={"REQ-003": "  "}))
    assert report["reason"].startswith("explain change to REQ-003")


def test_a_removed_requirement_without_a_reason_is_held_back(
    make_runtime, fake: FakeSystem
) -> None:
    rt = architect(make_runtime, handoff())
    seed(rt, "REQ-003", req("REQ-003"))
    tracked_diff(fake, ("D", path_of("REQ-003")))
    rt.query_fn.action = writes(rt, {path_of("REQ-003"): None, "docs/design/s1.md": "d"})
    report = step(rt)
    assert report["reason"].startswith("explain change to REQ-003 (")
    assert system.exists(rt.config.repo / path_of("REQ-003"))


# ----- auto-accept (AC5, T17-T19) -----


def accept_run(make_runtime, fake: FakeSystem, before: str, after: str, why: str = "because"):
    rt = architect(make_runtime, handoff(requirement_changes={"REQ-003": why}), story="s9")
    add_story(rt, "s5", "implement", rounds=2)
    add_story(rt, "s6", "design")
    add_story(rt, "s7", "implement", status=gates.StoryStatus.DONE)
    add_story(rt, "s8", "implement", status=gates.StoryStatus.CANCELLED)
    if before:
        seed(rt, "REQ-003", before)
        tracked_diff(fake, ("M", path_of("REQ-003")))
    rt.query_fn.action = writes(rt, {path_of("REQ-003"): after, "docs/design/s9.md": "d"})
    return rt, step(rt, "s9")


ALL = "'s5/AC1', 's6/AC1', 's7/AC1', 's8/AC1', 's9/AC1'"


def test_a_changed_requirement_sends_past_design_stories_back_without_a_round(
    make_runtime, fake: FakeSystem
) -> None:
    rt, report = accept_run(
        make_runtime, fake, req("REQ-003", ALL), req("REQ-003", ALL, body="edited")
    )
    s = rt.state.stories
    assert (s["s5"].step, s["s5"].rounds) == ("design", 0)
    assert s["s5"].note == rc.REDESIGN_NOTE.format(
        by="s9", sha=report["commit"][:12], changes="REQ-003 changed: because"
    )
    assert (s["s6"].step, s["s6"].note) == ("design", "")
    assert s["s7"].status is gates.StoryStatus.DONE and s["s7"].step == "implement"
    assert (s["s8"].status, s["s8"].step) == (gates.StoryStatus.CANCELLED, "implement")
    assert "Back to design" not in s["s9"].note
    assert report["redesigned_stories"] == ["s5"]
    assert report["affected_done_stories"] == ["s7"]


def test_the_redesign_is_saved(make_runtime, fake: FakeSystem) -> None:
    rt, _ = accept_run(make_runtime, fake, req("REQ-003", ALL), req("REQ-003", ALL, body="e"))
    saved = json.loads(system.read_text(rt.config.run_dir / "state.json"))
    assert saved["stories"]["s5"]["step"] == "design"


def test_an_added_requirement_changes_nothing_for_other_stories(
    make_runtime, fake: FakeSystem
) -> None:
    rt, report = accept_run(make_runtime, fake, "", req("REQ-003", ALL))
    assert rt.state.stories["s5"].step == "implement" and rt.state.stories["s5"].rounds == 2
    assert "redesigned_stories" not in report and "affected_done_stories" not in report


def test_dropping_a_cover_still_sends_that_story_back(make_runtime, fake: FakeSystem) -> None:
    rt, report = accept_run(make_runtime, fake, req("REQ-003", "'s5/AC1'"), req("REQ-003"))
    assert rt.state.stories["s5"].step == "design"
    assert report["redesigned_stories"] == ["s5"]


def test_retiring_a_requirement_counts(make_runtime, fake: FakeSystem) -> None:
    rt, report = accept_run(
        make_runtime,
        fake,
        req("REQ-003", "'s5/AC1', 's7/AC1'"),
        req("REQ-003", "'s5/AC1', 's7/AC1'", "retired"),
        "obsolete",
    )
    assert report["requirement_changes"][0]["change"] == "retired"
    assert report["redesigned_stories"] == ["s5"] and report["affected_done_stories"] == ["s7"]
    assert "REQ-003 retired: obsolete" in rt.state.stories["s5"].note


@pytest.mark.parametrize(
    ("step_name", "expected"),
    [
        ("design", False),
        ("ops-review", True),
        ("tests", True),
        ("review", True),
        ("nowhere", False),
    ],
)
def test_is_past_design(make_runtime, step_name: str, expected: bool) -> None:
    rt = make_runtime()
    rt.pipeline.steps = ["design", "ops-review", "tests", "implement", "review"]
    story = gates.StoryState("s1", "T", step_name)
    assert rt.pipeline.is_past_design(story) is expected


def test_is_past_design_without_a_design_step_counts_from_the_first(make_runtime) -> None:
    rt = make_runtime()
    rt.pipeline.steps = ["tests", "implement"]
    assert not rt.pipeline.is_past_design(gates.StoryState("s1", "T", "tests"))
    assert rt.pipeline.is_past_design(gates.StoryState("s1", "T", "implement"))


# ----- the PO hand-over (AC5, T20) -----

DONE_REPORT = {
    "status": "done",
    "role": "architect",
    "affected_done_stories": ["s6", "s7"],
    "requirement_changes": [
        {"id": "REQ-003", "change": "changed", "reason": "why"},
        {"id": "REQ-004", "change": "retired", "reason": "gone"},
    ],
}


def test_the_trigger_value() -> None:
    assert handover.Trigger.AFFECTED_DONE == "affected_done"


def test_a_report_with_affected_done_stories_gets_the_line() -> None:
    fields = handover.report_fields(DONE_REPORT, "s9")
    assert fields["affected_done"] == "s6, s7"
    assert fields["requirement_changes"] == "REQ-003 changed: why; REQ-004 retired: gone"
    lines = handover.report_lines(DONE_REPORT, "s9")
    assert handover.AFFECTED_DONE_LINE.format(**fields) in lines
    assert "request_story" in handover.AFFECTED_DONE_LINE


def test_a_report_without_them_has_no_such_row() -> None:
    report = {"status": "done", "role": "architect"}
    assert handover.Trigger.AFFECTED_DONE not in handover.triggers(report)
    assert handover.report_fields(report, None)["affected_done"] == ""


def test_the_row_comes_right_after_quarantine() -> None:
    report = {**DONE_REPORT, "quarantine": "abc"}
    found = handover.triggers(report)
    assert (
        found.index(handover.Trigger.AFFECTED_DONE) == found.index(handover.Trigger.QUARANTINE) + 1
    )


# ----- the architect's stop check (AC2, T12) -----


class StopGit:
    """The git the hook uses: its digest calls plus diff and show."""

    def __init__(self, repo: Path, diff: str, show: dict[str, str]) -> None:
        self.repo, self.diff, self.show = repo, diff, show

    def head(self) -> str:
        return "abc123"

    def content_digest(self, base: str) -> str:
        return "d1"

    def changed_paths(self) -> list[str]:
        return []

    def run(self, *args: str) -> str:
        return self.diff if args[0] == "diff" else self.show[args[-1]]


@pytest.fixture
def stop(make_runtime, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    def build(reasons: dict, files: dict[str, tuple[str, str]], kind: str = "M"):
        rt = make_runtime()
        diff = "".join(f"{kind}\0{p}\0" for p, (old, _) in files.items() if old)
        show = {f"HEAD:{p}": old for p, (old, _) in files.items()}
        rt.git = StopGit(rt.config.repo, diff, show)
        story = add_story(rt, "s1", "design")
        resolved = rt.resolve("architect")
        plan = Plan(resolved, rt.scope_for(resolved), story)
        plan.stop_hook = StopChecks(rt, plan)
        for p, (_, new) in files.items():
            system.make_dirs((rt.config.repo / p).parent)
            system.write_text(rt.config.repo / p, new)
        found = list(files)
        monkeypatch.setattr(guard, "audit_step", lambda g, s: SimpleNamespace(in_scope=found))
        plan.said.text = handoff(requirement_changes=reasons)
        data = {"hook_event_name": "Stop", "stop_hook_active": False}
        return asyncio.run(plan.stop_hook.hook(data, None, None))

    return build


def test_an_unexplained_change_refuses_the_architects_stop(stop) -> None:
    answer = stop({}, {path_of("REQ-003"): (req("REQ-003"), req("REQ-003", body="e"))})
    assert answer["decision"] == "block"
    assert rc.STOP_EXPLAIN.format(explain="explain change to REQ-003") in answer["reason"]


def test_an_explained_change_passes_the_stop(stop) -> None:
    files = {path_of("REQ-003"): (req("REQ-003"), req("REQ-003", body="e"))}
    assert stop({"REQ-003": "why"}, files) == {}


def test_an_added_requirement_needs_no_reason_at_the_stop(stop) -> None:
    assert stop({}, {path_of("REQ-003"): ("", req("REQ-003"))}) == {}


def test_only_the_architect_has_the_requirements_check() -> None:
    assert StopCheck.REQUIREMENTS == "requirements"
    assert StopCheck.REQUIREMENTS in stop_checks.checks_for("architect")
    assert stop_checks.STOP_CHECKS["architect"] == (StopCheck.REQUIREMENTS,)
    for role in ("developer", "developer-cli", "unit-tester", "code-reviewer", "devops"):
        assert StopCheck.REQUIREMENTS not in stop_checks.checks_for(role)
    spec = stop_checks.SPECS[StopCheck.REQUIREMENTS]
    assert spec.step is None and spec.stage == stages.Name.STOP_REQUIREMENTS
    assert stages.Name.STOP_REQUIREMENTS == "stop.requirements"


# ----- the CLI (AC6, T21-T22) -----


def cli_log(configured: Path, capsys) -> tuple[int, str, str]:
    code = cli.main(["--repo", str(configured), "requirements", "log"])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_requirements_log_prints_the_rows_as_json(
    configured: Path, fake: FakeSystem, capsys
) -> None:
    out = f"{'a' * 40}\x1f2026-01-01T00:00:00+00:00\x1fREQ-003: why\x1e REQ-004: x\x1d\n"
    fake.reply(("git", "log"), Done(0, out))
    code, text, _ = cli_log(configured, capsys)
    assert code == 0
    assert json.loads(text)[0] == {
        "id": "REQ-003",
        "reason": "why",
        "sha": "a" * 40,
        "date": "2026-01-01T00:00:00+00:00",
    }
    argv = next(c.argv for c in fake.commands if "log" in c.argv)
    assert "--reverse" in argv and argv[-2:] == ("--", FOLDER)


def test_requirements_log_with_no_trailers_prints_an_empty_list(
    configured: Path, fake: FakeSystem, capsys
) -> None:
    fake.reply(("git", "log"), Done(0, ""))
    code, text, _ = cli_log(configured, capsys)
    assert (code, json.loads(text)) == (0, [])


def test_requirements_log_outside_a_repo_exits_1_on_stderr(
    configured: Path, fake: FakeSystem, capsys
) -> None:
    fake.reply(("git", "log"), Done(128, "", "fatal: not a git repository"))
    code, text, err = cli_log(configured, capsys)
    assert code == 1 and text == ""
    assert err.startswith("agile-team requirements log: ") and "not a git repository" in err


def test_requirements_actions_are_a_table_of_check_and_log() -> None:
    assert list(cli.REQUIREMENT_ACTIONS) == ["check", "log"]
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["requirements", "nope"])


def test_requirements_check_still_works(configured: Path, capsys) -> None:
    code = cli.main(["--repo", str(configured), "requirements", "check"])
    assert code == 0 and "problems" in json.loads(capsys.readouterr().out)


# ----- the role files (AC7, T23) -----

ROLES = Path(cli.__file__).parent / "roles"
ARCHITECT = (ROLES / "architect.md").read_text()
PRODUCT_OWNER = (ROLES / "product-owner.md").read_text()


def test_the_architect_file_documents_requirement_changes() -> None:
    assert "requirement_changes" in ARCHITECT and "Requirement-Changed" in ARCHITECT


def test_the_product_owner_file_tells_it_to_ask_for_a_follow_up() -> None:
    assert "affected_done_stories" in PRODUCT_OWNER and "request_story" in PRODUCT_OWNER
