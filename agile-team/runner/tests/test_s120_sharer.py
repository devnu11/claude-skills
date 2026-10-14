"""s120: the Sharer applies queued shares between steps (design S4, S7, S8; AC1, AC4)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agile_team import cli, shares, system
from agile_team import state as state_mod
from agile_team.events import EventKind
from agile_team.sharing import Sharer, Shares
from agile_team.state import RunState

from .test_s120_shares import BYTES, SHA, write_story

TARGET = "docs/design/s1-mock.html"
STORY_PATH = ".team/stories/s1.md"


def sha_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def queue(rt, data: bytes = BYTES, name: str = "mock.html", story: str = "s1") -> shares.Share:
    return Shares(rt.config.run_dir).queue(shares.Share("", story, name, data))


def world(rt, fake) -> None:
    write_story(rt.config.repo)
    fake.track()


def apply(rt) -> None:
    Sharer(rt).apply()


def share_events(rt) -> list:
    return [e for e in rt.events.events() if e.kind == "share"]


def told_texts(rt) -> list[str]:
    return [system.read_text(t.path) for t in rt.relay.told()]


# ----- state and event kind ---------------------------------------------------------


def test_event_kind() -> None:
    assert EventKind.SHARE == "share"


def test_state_round_trips_shares() -> None:
    st = RunState(shares={"f1": "unchanged"})
    assert RunState.from_json(st.to_json()).shares == {"f1": "unchanged"}


def test_legacy_state_loads_empty_shares() -> None:
    data = json.loads(RunState().to_json())
    data.pop("shares", None)
    assert RunState.from_json(json.dumps(data)).shares == {}


# ----- applying (S4) ----------------------------------------------------------------


def test_apply_copies_the_file_records_the_entry_and_commits_once(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    before = len(fake.tree.commits)
    queue(rt)
    apply(rt)
    repo = rt.config.repo
    assert system.read_bytes(repo / TARGET) == BYTES
    listed = shares.listed_of(rt.config, "s1")
    assert listed.files == (shares.SharedFile(TARGET, SHA),) and listed.problems == ()
    assert len(fake.tree.commits) == before + 1
    last = fake.tree.commits[-1]
    assert last.paths() == {TARGET, STORY_PATH}
    assert last.subject() == "chore(s1): share mock.html (f1)"


def test_apply_keeps_the_story_body_and_other_keys(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    apply(rt)
    text = system.read_text(rt.config.repo / STORY_PATH)
    assert text.startswith("---\nid: s1\ntitle: T\n") and text.endswith("---\n\nBody text.\n")


def test_apply_records_the_outcome_with_the_commit(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    apply(rt)
    assert rt.state.shares == {"f1": f"applied {fake.tree.head[:12]}"}
    assert state_mod.load(rt.config.run_dir).shares == rt.state.shares


def test_apply_makes_the_checkout_guard_expect_the_new_head(
    make_runtime, fake, monkeypatch
) -> None:
    rt = make_runtime()
    world(rt, fake)
    seen: list[str] = []
    monkeypatch.setattr(rt, "record_checkout", lambda: seen.append(fake.tree.head))
    queue(rt)
    apply(rt)
    assert seen == [fake.tree.head]


def test_apply_emits_one_share_event(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    apply(rt)
    [ev] = share_events(rt)
    assert ev.role == "liaison" and ev.story == "s1"
    assert ev.data["request"] == "f1" and ev.data["path"] == TARGET
    assert ev.data["sha256"] == SHA and ev.data["outcome"] == "applied"
    assert fake.tree.head.startswith(ev.data["commit"])


def test_apply_tells_the_po_once_with_the_exact_line(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    apply(rt)
    [text] = told_texts(rt)
    assert text == shares.TOLD.format(
        path=TARGET, story="s1", short=SHA[:12], commit=fake.tree.head[:12]
    )
    assert text.startswith(
        "Runner note: the liaison shared docs/design/s1-mock.html for s1 (sha256 "
    )


def test_apply_twice_settles_each_share_once(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    apply(rt)
    commits = len(fake.tree.commits)
    apply(rt)
    assert len(fake.tree.commits) == commits and len(share_events(rt)) == 1
    assert len(told_texts(rt)) == 1


def test_apply_settles_in_number_order(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt, b"one", "a.html")
    queue(rt, b"two", "b.html")
    apply(rt)
    subjects = [c.subject() for c in fake.tree.commits[-2:]]
    assert subjects == ["chore(s1): share a.html (f1)", "chore(s1): share b.html (f2)"]
    assert [f.path for f in shares.listed_of(rt.config, "s1").files] == [
        "docs/design/s1-a.html",
        "docs/design/s1-b.html",
    ]


def test_apply_with_nothing_queued_does_nothing(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    commits = len(fake.tree.commits)
    apply(rt)
    assert len(fake.tree.commits) == commits and share_events(rt) == [] and rt.state.shares == {}


def test_apply_makes_the_design_dir_when_missing(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    assert not system.is_dir(rt.config.repo / "docs" / "design")
    queue(rt)
    apply(rt)
    assert system.is_dir(rt.config.repo / "docs" / "design")


def test_binary_bytes_are_copied_exactly(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    raw = bytes(range(256)) * 3
    queue(rt, raw, "pic.png")
    apply(rt)
    assert system.read_bytes(rt.config.repo / "docs/design/s1-pic.png") == raw


# ----- unchanged and new versions ---------------------------------------------------


def test_resharing_identical_bytes_is_unchanged_with_no_commit_and_no_tell(
    make_runtime, fake
) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    apply(rt)
    commits = len(fake.tree.commits)
    queue(rt)
    apply(rt)
    assert rt.state.shares["f2"] == "unchanged"
    assert len(fake.tree.commits) == commits
    assert len(told_texts(rt)) == 1
    [_, second] = share_events(rt)
    assert second.data["outcome"] == "unchanged" and second.data["commit"] is None


def test_a_new_version_replaces_the_bytes_and_the_hash_in_a_new_commit(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    apply(rt)
    commits = len(fake.tree.commits)
    queue(rt, b"v2\n")
    apply(rt)
    assert len(fake.tree.commits) == commits + 1
    assert system.read_bytes(rt.config.repo / TARGET) == b"v2\n"
    listed = shares.listed_of(rt.config, "s1")
    assert listed.files == (shares.SharedFile(TARGET, sha_of(b"v2\n")),)
    assert rt.state.shares["f2"].startswith("applied ")
    assert len(told_texts(rt)) == 2


def test_unchanged_when_the_target_matches_but_the_entry_is_missing_is_applied(
    make_runtime, fake
) -> None:
    rt = make_runtime()
    world(rt, fake)
    system.make_dirs(rt.config.repo / "docs" / "design")
    system.write_bytes(rt.config.repo / TARGET, BYTES)
    queue(rt)
    apply(rt)
    assert rt.state.shares["f1"].startswith("applied ")
    assert shares.listed_of(rt.config, "s1").files == (shares.SharedFile(TARGET, SHA),)


# ----- refusals at apply time and the boundary --------------------------------------


def test_a_story_removed_after_queueing_is_refused_without_writes(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    system.remove(rt.config.repo / STORY_PATH)
    commits = len(fake.tree.commits)
    apply(rt)
    assert rt.state.shares["f1"] == ("refused: no story 's1': .team/stories/s1.md does not exist")
    assert len(fake.tree.commits) == commits
    assert not system.exists(rt.config.repo / TARGET)
    [ev] = share_events(rt)
    assert ev.data["outcome"] == "refused" and ev.data["commit"] is None and ev.data["reason"]
    assert told_texts(rt) == []


def test_a_share_whose_frontmatter_cannot_take_the_entry_is_refused(make_runtime, fake) -> None:
    rt = make_runtime()
    write_story(rt.config.repo, "no frontmatter here\n")
    fake.track()
    queue(rt)
    commits = len(fake.tree.commits)
    apply(rt)
    out = rt.state.shares["f1"]
    assert out.startswith(
        "refused: .team/stories/s1.md: cannot record the share; fix its frontmatter ("
    )
    assert len(fake.tree.commits) == commits and not system.exists(rt.config.repo / TARGET)
    assert system.read_text(rt.config.repo / STORY_PATH) == "no frontmatter here\n"


def test_a_refused_share_is_settled_and_not_retried(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    system.remove(rt.config.repo / STORY_PATH)
    apply(rt)
    write_story(rt.config.repo)
    apply(rt)
    assert len(share_events(rt)) == 1 and not system.exists(rt.config.repo / TARGET)


def test_shares_wait_while_a_boundary_is_open(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)
    rt.state.boundary = object()
    commits = len(fake.tree.commits)
    apply(rt)
    assert rt.state.shares == {} and len(fake.tree.commits) == commits and share_events(rt) == []
    rt.state.boundary = None
    apply(rt)
    assert rt.state.shares["f1"].startswith("applied ")


# ----- status (cli) -----------------------------------------------------------------


def test_status_shows_queued_shares_and_settled_ones(configured: Path, capsys) -> None:
    write_story(configured)
    run_dir = configured / ".team" / "run"
    Shares(run_dir).queue(shares.Share("", "s1", "a.html", BYTES))
    Shares(run_dir).queue(shares.Share("", "s1", "b.html", BYTES))
    state_mod.save(run_dir, RunState(shares={"f1": "unchanged"}))
    assert cli.main(["--repo", str(configured), "status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["queued_shares"] == ["f2"] and out["shares"] == {"f1": "unchanged"}


def test_status_with_no_shares(configured: Path, capsys) -> None:
    assert cli.main(["--repo", str(configured), "status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["queued_shares"] == [] and out["shares"] == {}
