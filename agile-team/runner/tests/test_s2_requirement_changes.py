"""s2: the requirement_changes module: classify, explain, trailers, accept scope, the log."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agile_team import requirement_changes as rc
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import GitError

from .fake_system import FakeSystem

FOLDER = "docs/requirements"


def req(
    path_id: str = "REQ-003", status: str = "active", covers: str = "", body: str = "Words."
) -> str:
    """A requirement file's text."""
    items = f"covers: [{covers}]\n" if covers else ""
    return f"---\nid: {path_id}\ntitle: T\nstatus: {status}\n{items}---\n\n{body}\n"


def versions(before: str | None, after: str | None) -> rc.Versions:
    return rc.Versions(f"{FOLDER}/REQ-003.md", before, after)


class StubGit:
    """Answers the few git calls the module makes; records them."""

    def __init__(self, answers: dict[str, Any] | None = None, repo: Path | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[tuple[str, ...]] = []
        self.repo = repo or Path("/repo")

    def run(self, *args: str) -> str:
        self.calls.append(args)
        answer = self.answers.get(args[0], "")
        if isinstance(answer, dict):
            answer = answer[args[-1]]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def commit(self, paths: list[str], message: str) -> str:
        self.calls.append(("commit", message, *paths))
        return "held1"

    def revert(self, sha: str) -> str:
        self.calls.append(("revert", sha))
        return "rev1"


# ----- candidates (C1) -----


def test_candidates_keep_only_direct_req_files_in_the_folder() -> None:
    paths = [
        f"{FOLDER}/REQ-003.md",
        f"{FOLDER}/sub/REQ-1.md",
        f"{FOLDER}/README.md",
        "docs/REQ-003.md",
        "src/a.py",
        f"{FOLDER}/REQ-010.md",
    ]
    assert rc.candidates(paths, FOLDER) == [f"{FOLDER}/REQ-003.md", f"{FOLDER}/REQ-010.md"]


def test_candidates_of_nothing_is_empty() -> None:
    assert rc.candidates([], FOLDER) == []


# ----- classify (C2) -----


def test_a_file_with_no_before_is_added_even_when_born_retired() -> None:
    assert rc.classify(versions(None, req())).change is rc.Change.ADDED
    assert rc.classify(versions(None, req(status="retired"))).change is rc.Change.ADDED


def test_a_removed_file_is_retired() -> None:
    assert rc.classify(versions(req(), None)).change is rc.Change.RETIRED


def test_flipping_status_to_retired_is_retired() -> None:
    assert rc.classify(versions(req(), req(status="retired"))).change is rc.Change.RETIRED


def test_other_edits_are_changed() -> None:
    assert rc.classify(versions(req(), req(body="New."))).change is rc.Change.CHANGED
    assert rc.classify(versions(req(status="retired"), req())).change is rc.Change.CHANGED
    both = versions(req(status="retired"), req(status="retired", body="More."))
    assert rc.classify(both).change is rc.Change.CHANGED


def test_the_id_is_the_file_stem_and_the_file_is_kept() -> None:
    changed = rc.classify(versions(req(), req(body="x")))
    assert (changed.id, changed.file) == ("REQ-003", f"{FOLDER}/REQ-003.md")


def test_stories_are_the_union_of_both_versions_in_natural_order() -> None:
    before = req(covers="'s10/AC1', 's2/AC1', 's5/AC1'")
    after = req(covers="'s2/AC2', 'nope', 's9/AC1', 5")
    assert rc.classify(versions(before, after)).stories == ("s2", "s5", "s9", "s10")


def test_a_version_without_frontmatter_has_no_status_and_no_covers() -> None:
    changed = rc.classify(versions("just words", req(covers="'s4/AC1'")))
    assert (changed.change, changed.stories) == (rc.Change.CHANGED, ("s4",))
    assert rc.classify(versions("just words", "other words")).stories == ()


def test_the_classifier_never_refuses_broken_frontmatter() -> None:
    changed = rc.classify(versions("---\n: [bad\n---\n", "---\n: [bad\n---\nx\n"))
    assert changed.change is rc.Change.CHANGED


# ----- reasons (C3) -----


def changed(req_id: str = "REQ-003", kind: rc.Change = rc.Change.CHANGED) -> rc.Changed:
    return rc.Changed(req_id, kind, f"{FOLDER}/{req_id}.md", ())


def test_reason_whitespace_is_collapsed_to_one_line() -> None:
    assert rc.reason_for(changed(), {"REQ-003": "  two\n  lines\there "}) == "two lines here"


def test_an_added_change_without_a_reason_gets_the_default() -> None:
    added = changed(kind=rc.Change.ADDED)
    assert rc.reason_for(added, {}) == rc.NEW_REASON == "new requirement"
    assert rc.reason_for(added, {"REQ-003": "because"}) == "because"


def test_a_blank_reason_on_a_changed_requirement_is_empty() -> None:
    assert rc.reason_for(changed(), {"REQ-003": "  "}) == ""
    assert rc.reason_for(changed(), {}) == ""
    assert rc.reason_for(changed(kind=rc.Change.RETIRED), {}) == ""


def test_needs_reason_kinds() -> None:
    assert {rc.Change.CHANGED, rc.Change.RETIRED} == rc.NEEDS_REASON


def test_sorting_splits_landed_from_held_in_natural_order() -> None:
    items = [
        changed("REQ-010"),
        changed("REQ-004", rc.Change.ADDED),
        changed("REQ-009"),
        changed("REQ-002", rc.Change.RETIRED),
    ]
    sorting = rc.sort_changes(items, {"REQ-010": "why ten", "REQ-777": "ignored"})
    assert [e.changed.id for e in sorting.landed] == ["REQ-004", "REQ-010"]
    assert [c.id for c in sorting.held] == ["REQ-002", "REQ-009"]
    assert sorting.held_files == [f"{FOLDER}/REQ-002.md", f"{FOLDER}/REQ-009.md"]
    assert sorting.trailers == (
        "Requirement-Changed: REQ-004: new requirement",
        "Requirement-Changed: REQ-010: why ten",
    )


def test_a_reason_for_a_non_candidate_is_ignored() -> None:
    sorting = rc.sort_changes([changed()], {"REQ-003": "ok", "REQ-999": "stray"})
    assert [e.changed.id for e in sorting.landed] == ["REQ-003"]
    assert sorting.held == () and "REQ-999" not in " ".join(sorting.trailers)


def test_explained_reports_and_trailers() -> None:
    explained = rc.Explained(changed(kind=rc.Change.RETIRED), "gone")
    assert explained.trailer() == "Requirement-Changed: REQ-003: gone"
    assert explained.report() == {"id": "REQ-003", "change": "retired", "reason": "gone"}


def test_explain_text_joins_with_semicolons() -> None:
    held = [changed("REQ-003"), changed("REQ-004")]
    assert rc.explain_text(held) == "explain change to REQ-003; explain change to REQ-004"


def test_messages_are_exact() -> None:
    assert rc.HELD_SUBJECT == "chore(team): {role}'s unexplained requirement edits, held back"
    assert rc.UNEXPLAINED.startswith("{explain} (your edits are held back in {sha}")
    assert rc.TRAILER == "Requirement-Changed: {id}: {reason}"
    assert rc.GLOB == "REQ-*.md" and rc.TRAILER_KEY == "Requirement-Changed"


# ----- auto-accept helpers (C8) -----


def landed(req_id: str, kind: rc.Change, stories: tuple[str, ...], reason: str = "why") -> Any:
    return rc.Explained(rc.Changed(req_id, kind, f"{FOLDER}/{req_id}.md", stories), reason)


def test_traced_unions_needs_reason_kinds_without_the_own_story() -> None:
    items = [
        landed("REQ-001", rc.Change.CHANGED, ("s10", "s2", "s9")),
        landed("REQ-002", rc.Change.RETIRED, ("s2", "s5")),
        landed("REQ-003", rc.Change.ADDED, ("s7",)),
    ]
    assert rc.traced(items, "s9") == ["s2", "s5", "s10"]
    assert rc.traced(items, None) == ["s2", "s5", "s9", "s10"]


def story(sid: str, step: str, status: StoryStatus = StoryStatus.ACTIVE) -> StoryState:
    return StoryState(sid, "T", step, status=status)


def test_find_affected_sorts_done_from_redesign_and_skips_the_rest() -> None:
    stories = {
        "s5": story("s5", "implement"),
        "s6": story("s6", "design"),
        "s7": story("s7", "done", StoryStatus.DONE),
        "s8": story("s8", "implement", StoryStatus.CANCELLED),
    }
    scope = rc.AcceptScope(("s5", "s6", "s7", "s8", "s99"), lambda s: s.step == "implement")
    found = rc.find_affected(stories, scope)
    assert found == rc.Affected(redesign=("s5",), done=("s7",))


def test_affected_defaults_to_nothing() -> None:
    assert rc.Affected() == rc.Affected((), ())


def test_redesign_note_names_the_step_story_sha_and_only_its_changes() -> None:
    items = [
        landed("REQ-003", rc.Change.CHANGED, ("s5",), "wording"),
        landed("REQ-004", rc.Change.RETIRED, ("s6",), "obsolete"),
        landed("REQ-005", rc.Change.RETIRED, ("s5", "s6"), "dropped"),
    ]
    sha = "ab" * 20
    note = rc.redesign_note(items, rc.NoteTarget("s5", "s9", sha))
    assert note.startswith("Back to design: s9's step changed requirements this story traces (")
    assert "REQ-003 changed: wording; REQ-005 retired: dropped" in note
    assert "REQ-004" not in note and sha[:12] in note


# ----- git seam (C2, C4, C10) -----


def test_name_status_reads_z_pairs_and_marks_untracked_as_added() -> None:
    a, b, c, d = (f"{FOLDER}/REQ-00{n}.md" for n in (1, 2, 3, 4))
    out = f"M\0{a}\0D\0{b}\0T\0{c}\0"
    git = StubGit({"diff": out})
    assert rc.name_status(git, [a, b, c, d]) == {a: "M", b: "D", c: "M", d: "A"}
    argv = git.calls[0]
    assert argv[: len(rc.DIFF_ARGV)] == rc.DIFF_ARGV and list(argv[len(rc.DIFF_ARGV) :]) == [
        a, b, c, d,
    ]  # fmt: skip


def test_read_versions_reads_head_and_disk(fake: FakeSystem) -> None:
    path = f"{FOLDER}/REQ-003.md"
    git = StubGit({"show": "OLD"}, repo=fake.workdir)
    fake.put(fake.workdir / path, "NEW")
    assert rc.read_versions(git, (path, "M")) == rc.Versions(path, "OLD", "NEW")
    assert git.calls == [("show", f"HEAD:{path}")]


def test_read_versions_added_has_no_before_and_deleted_has_no_after(fake: FakeSystem) -> None:
    path = f"{FOLDER}/REQ-003.md"
    git = StubGit({"show": "OLD"}, repo=fake.workdir)
    fake.put(fake.workdir / path, "NEW")
    assert rc.read_versions(git, (path, "A")) == rc.Versions(path, None, "NEW")
    assert rc.read_versions(git, (path, "D")) == rc.Versions(path, "OLD", None)


def test_find_changes_with_nothing_runs_no_git() -> None:
    git = StubGit()
    assert rc.find_changes(git, []) == []
    assert git.calls == []


def test_find_changes_classifies_each_path(fake: FakeSystem) -> None:
    kept, gone, new = (f"{FOLDER}/REQ-00{n}.md" for n in (1, 2, 3))
    texts = {f"HEAD:{kept}": req("REQ-001"), f"HEAD:{gone}": req("REQ-002")}
    git = StubGit({"diff": f"M\0{kept}\0D\0{gone}\0", "show": texts}, repo=fake.workdir)
    fake.put(fake.workdir / kept, req("REQ-001", body="edited"))
    fake.put(fake.workdir / new, req("REQ-003"))
    found = {c.id: c.change for c in rc.find_changes(git, [kept, gone, new])}
    assert found == {
        "REQ-001": rc.Change.CHANGED,
        "REQ-002": rc.Change.RETIRED,
        "REQ-003": rc.Change.ADDED,
    }


def test_hold_back_commits_the_files_alone_then_reverts_and_returns_the_sha() -> None:
    git = StubGit()
    held = rc.HeldBack("architect", (f"{FOLDER}/REQ-003.md",))
    assert rc.hold_back(git, held) == "held1"
    subject = "chore(team): architect's unexplained requirement edits, held back"
    assert git.calls == [("commit", subject, f"{FOLDER}/REQ-003.md"), ("revert", "held1")]


# ----- the log (C10) -----

SEP, END, UNIT = "\x1e", "\x1d", "\x1f"


def record(sha: str, date: str, *values: str) -> str:
    return f"{sha}{UNIT}{date}{UNIT}{SEP.join(values)}{END}\n"


def test_parse_log_gives_rows_in_order_and_skips_commits_without_trailers() -> None:
    out = record("a" * 40, "2026-01-01T10:00:00+00:00", "REQ-003: first", "REQ-004: second")
    out += record("b" * 40, "2026-01-02T10:00:00+00:00")
    out += record("c" * 40, "2026-01-03T10:00:00+00:00", "REQ-003: third")
    rows = rc.parse_log(out)
    assert rows == [
        {"id": "REQ-003", "reason": "first", "sha": "a" * 40, "date": "2026-01-01T10:00:00+00:00"},
        {"id": "REQ-004", "reason": "second", "sha": "a" * 40, "date": "2026-01-01T10:00:00+00:00"},
        {"id": "REQ-003", "reason": "third", "sha": "c" * 40, "date": "2026-01-03T10:00:00+00:00"},
    ]


def test_parse_log_skips_malformed_values_and_keeps_colons_in_reasons() -> None:
    values = ("no separator", "REQ-x: bad id", "XREQ-1: prefix", "REQ-7:", "REQ-8: ", "REQ-9: a: b")
    rows = rc.parse_log(record("d" * 40, "2026-02-01T00:00:00+00:00", *values))
    assert [(r["id"], r["reason"]) for r in rows] == [("REQ-9", "a: b")]


def test_parse_log_of_nothing_is_empty() -> None:
    assert rc.parse_log("") == [] and rc.parse_log("\n") == []


def test_log_runs_one_git_log_limited_to_the_folder() -> None:
    git = StubGit({"log": record("e" * 40, "2026-03-01T00:00:00+00:00", "REQ-001: x")})
    rows = rc.log(git, FOLDER)
    assert [r["id"] for r in rows] == ["REQ-001"]
    argv = git.calls[0]
    assert len(git.calls) == 1 and argv[0] == "log" and "--reverse" in argv
    assert any(a.endswith(rc.LOG_FORMAT) for a in argv)
    assert argv[-2:] == ("--", FOLDER)


def test_log_lets_a_git_error_through() -> None:
    with pytest.raises(GitError):
        rc.log(StubGit({"log": GitError("not a repo")}), FOLDER)
