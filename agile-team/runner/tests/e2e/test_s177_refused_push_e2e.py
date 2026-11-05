"""s177 end to end on real git: a refused sprint push, with a pre-receive hook on the bare origin.

The scene is the s159 one. The hook refuses the push and, depending on the test, leaves the
remote alone (AC1), puts the pushed merge on the remote (AC2) or moves the remote on (AC3).
One group per AC id.
"""

from __future__ import annotations

from agile_team.events import EventKind
from agile_team.gates import Verdict
from agile_team.landing import MAX_RESTARTS

from ..conftest import git
from .test_s151_as_built_end_e2e import Scene
from .test_s151_as_built_end_e2e import scene as scene_fixture
from .test_s159_landing_e2e import SPRINT, entry, land, open_story, remote_sprint, start_sprint

scene = scene_fixture
REFUSAL = "refused by the s177 hook"
HOOK_HEAD = (
    "#!/bin/sh\nread old new ref\n"
    f'[ "$ref" = refs/heads/{SPRINT} ] || exit 0\n'
    "COUNT=$(git rev-parse --absolute-git-dir)/count\n"
)
HOOK_REFUSE = f'echo "{REFUSAL}" >&2\nexit 1\n'
# Leave the hook's quarantine so the objects and the ref survive the refusal.
OUT = "env -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES"
COPY = 'cp -R "$GIT_QUARANTINE_PATH"/. "$(git rev-parse --absolute-git-dir)/objects/"\n'
HOOK_KEEP = COPY + OUT + ' git update-ref "$ref" "$new"\n'
HOOK_MOVE = (
    'n=$(cat "$COUNT" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$COUNT"\n'
    + COPY
    + f'tree=$({OUT} git rev-parse "$old^{{tree}}")\n'
    + f'new=$({OUT} git commit-tree "$tree" -p "$old" -m "other $n")\n'
    + OUT
    + ' git update-ref "$ref" "$new"\n'
)
MOVE_ONCE = '[ "$(cat "$COUNT" 2>/dev/null || echo 0)" -ge 1 ] && exit 0\n' + HOOK_MOVE + "exit 1\n"


def install_hook(scene: Scene, body: str) -> None:
    hook = scene.origin / "hooks" / "pre-receive"
    hook.write_text(HOOK_HEAD + body)
    hook.chmod(0o755)


def events(scene: Scene, kind: EventKind) -> list:
    return [e for e in scene.rt.events.events() if e.kind == kind]


def test_ac1_an_unmoved_remote_holds_at_once_and_the_retry_pushes_the_same_merge(
    scene: Scene,
) -> None:
    start = start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    install_hook(scene, HOOK_REFUSE)
    report = land(scene, story)
    assert report["gate"]["verdict"] == Verdict.HOLD
    assert REFUSAL in report["gate"]["reason"]
    merge = story.landed.merge
    assert merge and story.landed.pushed == merge
    assert remote_sprint(scene) == entry(scene).pushed == start
    assert events(scene, EventKind.LANDING_DROPPED) == []
    install_hook(scene, "")
    retry = land(scene, story)
    assert retry["gate"]["verdict"] == Verdict.PASS
    assert remote_sprint(scene) == merge == entry(scene).pushed


def test_ac2_a_remote_equal_to_the_merge_counts_as_landed_without_a_drop(scene: Scene) -> None:
    start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    install_hook(scene, HOOK_KEEP + HOOK_REFUSE)
    report = land(scene, story)
    assert report["gate"]["verdict"] == Verdict.PASS, report["gate"]["reason"]
    merge = report["land"]["merge"]
    assert remote_sprint(scene) == merge == entry(scene).pushed == entry(scene).head
    assert scene.head() == merge
    [landed] = events(scene, EventKind.STORY_LANDED)
    assert landed.data["ci"] == "green" and landed.data["merge"] == merge
    assert events(scene, EventKind.LANDING_DROPPED) == []


def test_ac3_a_remote_that_moved_on_once_is_followed_and_landed_again(scene: Scene) -> None:
    start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    install_hook(scene, MOVE_ONCE)
    report = land(scene, story)
    assert report["gate"]["verdict"] == Verdict.PASS
    assert len(events(scene, EventKind.LANDING_DROPPED)) == 1
    assert remote_sprint(scene) == report["land"]["merge"] == entry(scene).pushed


def test_ac3_the_kept_moving_hold_comes_after_max_restarts_distinct_heads(scene: Scene) -> None:
    start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    install_hook(scene, HOOK_MOVE + "exit 1\n")
    report = land(scene, story)
    assert report["gate"]["verdict"] == Verdict.HOLD
    reason = report["gate"]["reason"]
    assert "kept moving" in reason
    heads = git(scene.origin, "rev-list", SPRINT).split()
    assert len(heads) >= MAX_RESTARTS
    assert all(h in reason or h[:8] in reason for h in heads[:MAX_RESTARTS])
