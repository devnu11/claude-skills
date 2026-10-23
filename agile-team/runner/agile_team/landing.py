"""Landing a story on the sprint branch (s159 L3 to L12, E3).

A land merges the story branch with ``--no-ff`` in a scratch worktree, runs the full checks on the
merge, pushes it to a landing branch for CI, and only on green pushes the sprint branch and
fast-forwards the main checkout. Anything red leaves the sprint branch where it was.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import carry, fullcheck, rewrite, stages, story_rebase, story_spec, system, test_reports
from .boundary import (
    SPRINT_BRANCH_DIVERGED,
    Permission,
    PrMode,
    StackEntry,
    find_current_entry,
)
from .boundary_runner import BoundaryRunner
from .ci import CI_LOOKS, CI_POLL_S, CheckKind, CiResult, CiVerdict, ShaWatch, check_lines, label
from .ci_triage import rerun_key
from .dispatch import halted_report
from .events import Event, EventKind
from .gates import StoryState, Verdict
from .git_ops import Git
from .halt import Halt, HaltKind
from .reverts import REVERT_BODY, REVERT_SUBJECT
from .stage_log import place_of
from .story_branches import (
    Landed,
    StoryCi,
    StoryRebase,
    format_landing_branch,
    format_story_branch,
    merge_id,
    merge_subject,
)
from .upstream import Lease, UpstreamError
from .workspaces import LAND

if TYPE_CHECKING:
    from .dispatch import Runtime

LAND_STORY_CLASH = (
    "story {id}: its story file clashes between the story branch and the sprint branch's "
    "story-admin edits: {lines}; the land holds. Ask the liaison to settle it with story amend, "
    "then continue_story"
)
LANDED_NOTE = "Landed on {branch} as {merge}."
STORY_PR_BODY = (
    "Story {id} of the agile team, built on its own branch. It lands on {branch} by a tested merge."
)
CONFLICT_REASON = "merging {branch} into the sprint branch stopped on a conflict in {files}"
PUSH_REFUSED = "the landing push was refused: {why}"
CI_HELD = "landing CI on {sha} is {verdict}; the land holds"
SPRINT_PUSH_REFUSED = "pushing the sprint branch {branch} was refused: {why}"
MAX_RESTARTS = 5
PERMISSION_WAIT = "push_permission"
GIVE_UP_MOVED = "sprint head moved"
GIVE_UP_REFUSED = "sprint push refused"
REVERT_CONFLICT = "reverting story {story} stopped: {why}; nothing was reverted"


@dataclass(frozen=True)
class StoryFile:
    """The story file's three copies: the story branch's, the common base's, the sprint's."""

    ours: Path
    base: Path
    theirs: Path


@dataclass(frozen=True)
class Merged:
    """What ``git merge-file`` made of the three copies."""

    clean: bool
    text: str


def merge_story_file(paths: StoryFile) -> Merged:
    """L5: the branch copy with the sprint side's edits since the base re-applied on top."""
    command = ("git", "merge-file", "-p", str(paths.ours), str(paths.base), str(paths.theirs))
    done = system.run(system.Command(command, system.get_temp_dir()))
    return Merged(done.code == 0, done.out)


def make_report(story: StoryState, found: tuple[Verdict, str], **land: Any) -> dict[str, Any]:
    """A land step's report: the gate's verdict and reason (``bounce_to`` in ``land``)."""
    verdict, reason = found
    gate = {"verdict": verdict, "reason": reason, "bounce_to": land.pop("bounce_to", None)}
    return {"role": "runner", "status": "land", "story": story.id, "gate": gate, "land": land}


@dataclass
class Attempt:
    """One pass of a land: the story, the sprint entry, and the merge once it is made."""

    story: StoryState
    entry: StackEntry | None
    head: str
    merge: str = ""
    revert_of: str = ""
    reason: str = ""
    not_carried: str = ""
    dropped: list[dict[str, Any]] = field(default_factory=list)
    carried: dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        """The merge commit's subject."""
        return merge_subject(self.story.id, self.story.title)


class Lander:
    """Lands stories one at a time, under the main lock."""

    def __init__(self, runtime: Runtime, lock: asyncio.Lock) -> None:
        self.runtime = runtime
        self.lock = lock

    # ----- entry points

    async def land(self, story: StoryState) -> dict[str, Any]:
        """L3 to L12: land the story; a step report with the gate verdict and the land facts."""
        log = self.runtime.stage_log
        with log.within(place_of(story)), log.open(stages.Name.STORY_LAND) as run:
            try:
                report = await self.run_land(story)
            finally:
                self.runtime.flags.landing_base = ""
            run.detail = self.describe(report)
            return report

    def describe(self, report: dict[str, Any]) -> str:
        """AC9.2: the stage's detail: the verdict, the reason and the CI."""
        land = report.get("land") or {}
        gate = report.get("gate") or {}
        parts = [str(gate.get("verdict", report.get("status", ""))), str(gate.get("reason", ""))]
        parts += [f"ci {land['ci']}"] if land.get("ci") else []
        return "; ".join(p for p in parts if p)

    async def land_revert(self, story: StoryState, reason: str) -> dict[str, Any]:
        """E3: revert the story's landing merge in the land worktree and land the revert."""
        assert story.landed is not None
        attempt = Attempt(story, self.sprint_entry, self.sprint_head, revert_of=story.landed.merge)
        attempt.reason = reason
        try:
            report = await self.run_attempts(attempt)
        finally:
            self.runtime.flags.landing_base = ""
        return await self.add_later(attempt, report)

    async def add_later(self, attempt: Attempt, report: dict[str, Any]) -> dict[str, Any]:
        """E4: a revert that was refused names the later landed stories on the same files."""
        if (report.get("gate") or {}).get("verdict") is Verdict.PASS:
            return report
        report.setdefault("land", {})["later"] = await self.run_off(self.find_later, attempt)
        return report

    def find_later(self, attempt: Attempt) -> list[str]:
        """The stories landed after the reverted merge that touched the same files."""
        git, merge = self.runtime.git, attempt.revert_of
        files = git.attempt("diff", "--name-only", f"{merge}^1", merge)[1].split()
        if not files:
            return []
        log = git.attempt("log", "--first-parent", "--format=%H %s", f"{merge}..HEAD", "--", *files)
        ids = (merge_id(line.partition(" ")[2]) for line in log[1].splitlines())
        return [i for i in dict.fromkeys(ids) if i]

    async def run_land(self, story: StoryState) -> dict[str, Any]:
        """Wait for the permission, resume a pushed landing, or merge and ship."""
        attempt = Attempt(story, self.sprint_entry, self.sprint_head)
        if story.landed is not None and story.landed.pushed:
            attempt.merge = story.landed.merge
            await self.check_resume(attempt)
        elif (waiting := self.find_wait(story)) is not None:
            return waiting
        return await self.run_attempts(attempt)

    async def check_resume(self, attempt: Attempt) -> None:
        """G1, C5: resume a pushed landing while the head is unmoved or the move can be carried."""
        move = await self.read_move(attempt)
        self.runtime.flags.landing_base = move.base
        if move.is_unmoved:
            return
        refusal = await self.run_off(carry.find_refusal, self.runtime.git, move)
        if refusal is not None:
            attempt.not_carried = refusal
            await self.give_up(attempt, GIVE_UP_MOVED)

    async def read_move(self, attempt: Attempt) -> carry.Move:
        """C1: the merge's first parent, the sprint head, the pushed record and the story forks."""
        code, out = await self.run_off(self.runtime.git.attempt, "rev-parse", f"{attempt.merge}^1")
        entry = self.sprint_entry
        pushed = entry.pushed if entry else ""
        base = out.strip() if code == 0 else ""
        return carry.Move(attempt.merge, base, self.sprint_head, pushed, self.forks)

    @property
    def forks(self) -> tuple[tuple[str, str], ...]:
        """C1: every story's base sha and queued rebase target, as (story id, sha) pairs."""
        pairs: list[tuple[str, str]] = []
        for story in self.runtime.state.stories.values():
            pairs.append((story.id, story.base_sha))
            if story.rebase is not None:
                pairs.append((story.id, story.rebase.onto))
        return tuple(pair for pair in pairs if pair[1])

    async def plan_carry(self, attempt: Attempt) -> carry.Carried | str:
        """C2, C3: the tip to move to and the carried copies, or why the move can't be carried."""
        move = await self.read_move(attempt)
        if move.is_unmoved:
            return carry.Carried(attempt.merge, move.head)
        refusal = await self.run_off(carry.find_refusal, self.runtime.git, move)
        return refusal if refusal is not None else await self.carry_in_tree(move)

    async def carry_in_tree(self, move: carry.Move) -> carry.Carried | str:
        """C3: cherry-pick the moved commits onto the merge in a fresh land worktree."""
        await self.clear_tree()
        try:
            args = ("worktree", "add", "--detach", str(self.scratch_path), move.merge)
            await self.run_off(self.runtime.git.run, *args)
            return await self.run_off(carry.carry_commits, Git(self.scratch_path), move)
        finally:
            await self.clear_tree()

    async def take_carry(self, attempt: Attempt) -> carry.Carried | None:
        """C4: plan the carry; on a refusal give up the merge and return None."""
        planned = await self.plan_carry(attempt)
        if isinstance(planned, str):
            attempt.not_carried = planned
            await self.give_up(attempt, GIVE_UP_MOVED)
            return None
        return planned

    async def move_checkout(self, attempt: Attempt, carried: carry.Carried) -> bool:
        """C4: fast-forward to the merge, or reset to the carried tip and remap the run's shas."""
        up = self.runtime.upstream
        assert up is not None
        if not carried.moved:
            return bool(await self.run_off(up.advance_to, carried.tip))
        try:
            await self.run_off(up.reset_team_branch, carried.head, carried.tip)
        except UpstreamError:
            return False
        attempt.carried = carried.moved
        rewrite.remap_state(self.runtime.state, carried.moved)
        return True

    async def give_up(self, attempt: Attempt, why: str) -> None:
        """G3, G5: forget the merge; its landing branch goes, and the story merges afresh."""
        rt, story, merge = self.runtime, attempt.story, attempt.merge
        data = await self.note_drop(attempt, why)
        if not attempt.revert_of:
            story.landed = None
        if not self.is_local:
            branch = format_landing_branch(rt.config.upstream.story_prefix, story.id)
            await self.run_off(rt.upstream.delete, Lease(branch, merge, ""))  # type: ignore[union-attr]
        rt.events.emit(Event(EventKind.LANDING_DROPPED, "runner", story.id, data))
        attempt.merge, attempt.not_carried = "", ""
        rt.flags.landing_base = ""
        rt.save()

    async def note_drop(self, attempt: Attempt, why: str) -> dict[str, Any]:
        """D1: the drop's event data, naming the commits that moved the head."""
        move = await self.read_move(attempt)
        moved = await self.run_off(carry.list_moved, self.runtime.git, move)
        attempt.dropped.append({"merge": attempt.merge, "why": why, "moved": moved})
        data = {"merge": attempt.merge, "why": why, "sprint_head": move.head}
        return data | {"moved": moved, "not_carried": attempt.not_carried}

    # ----- the state the land reads

    @property
    def sprint_entry(self) -> StackEntry | None:
        """The sprint's stack entry (its branch is where landings go), if the sprint has one."""
        state = self.runtime.state
        return find_current_entry(state.upstream.stack, state.sprint)

    @property
    def sprint_head(self) -> str:
        """The sprint head: the entry's, else the main checkout's."""
        entry = self.sprint_entry
        return entry.head if entry and entry.head else self.runtime.git.head()

    @property
    def is_local(self) -> bool:
        """P3: nothing is pushed with no PR service, no sprint branch, or permission ``no``."""
        rt = self.runtime
        return (
            bool(rt.prs.missing())
            or rt.state.upstream.push is Permission.NO
            or (self.sprint_entry is None)
        )

    def find_wait(self, story: StoryState) -> dict[str, Any] | None:
        """L3: while the push permission is unasked, a land waits before its first push."""
        state = self.runtime.state
        if self.is_local or state.upstream.push is not Permission.UNASKED:
            return None
        first = not state.permission_asked
        state.permission_asked = True
        entry = self.sprint_entry
        report: dict[str, Any] = {"role": "runner", "status": "waiting", "story": story.id}
        if first and entry is not None:
            report["boundary"] = {"waiting": PERMISSION_WAIT, "branches": [entry.branch]}
        return report

    # ----- one attempt after another

    async def run_attempts(self, attempt: Attempt) -> dict[str, Any]:
        """G2: run the attempt, or resume a pushed one; again after a restart, a few times."""
        for _ in range(MAX_RESTARTS):
            report = await (
                self.finish_pushed(attempt) if attempt.merge else self.run_attempt(attempt)
            )
            if report is not None:
                return self.add_drops(attempt, report)
            attempt.merge, attempt.head = "", self.sprint_head
        report = make_report(attempt.story, (Verdict.HOLD, "the sprint branch kept moving"))
        return self.add_drops(attempt, report)

    def add_drops(self, attempt: Attempt, report: dict[str, Any]) -> dict[str, Any]:
        """D2: the report with the attempt's drops under land.dropped, if any."""
        if attempt.dropped:
            report.setdefault("land", {})["dropped"] = list(attempt.dropped)
        return report

    async def run_attempt(self, attempt: Attempt) -> dict[str, Any] | None:
        """Merge, check, ship; the report, or ``None`` to start again."""
        stopped = await self.merge(attempt)
        if stopped is not None:
            return stopped
        self.runtime.flags.landing_base = attempt.head
        stopped = await self.check(attempt)
        if stopped is not None:
            return stopped
        return await self.deliver(attempt)

    async def run_off(self, call: Any, *args: Any) -> Any:
        """Run blocking work in a worker thread."""
        return await system.run_in_thread(call, *args)

    @property
    def scratch_path(self) -> Path:
        """The land worktree."""
        return self.runtime.config.run_dir / LAND

    async def clear_tree(self) -> None:
        """Remove the land worktree if there is one."""
        git = self.runtime.git
        await self.run_off(git.attempt, "worktree", "remove", "--force", str(self.scratch_path))
        if system.exists(self.scratch_path):
            system.remove_tree(self.scratch_path)

    # ----- the merge (L4 to L6)

    async def merge(self, attempt: Attempt) -> dict[str, Any] | None:
        """Make the merge (or the revert) in the land worktree; a report if it could not be made."""
        await self.clear_tree()
        git = self.runtime.git
        await self.run_off(
            git.run, "worktree", "add", "--detach", str(self.scratch_path), attempt.head
        )
        tree = Git(self.scratch_path)
        code, _ = await self.run_off(self.run_merge, tree, attempt)
        if code == 0:
            attempt.merge = await self.run_off(tree.head)
            return None
        return await self.settle_conflict(attempt, tree)

    def run_merge(self, tree: Git, attempt: Attempt) -> tuple[int, str]:
        """The git command of the attempt: a no-ff merge, or a revert of the landing merge."""
        if attempt.revert_of:
            return self.run_revert(tree, attempt)
        argv = ("merge", "--no-ff", "--no-edit", "-m", attempt.title, attempt.story.branch)
        return tree.attempt(*argv)

    def run_revert(self, tree: Git, attempt: Attempt) -> tuple[int, str]:
        """Revert the landing merge (``-m 1``) and commit it with the revert message."""
        code, out = tree.attempt("revert", "--no-commit", "-m", "1", attempt.revert_of)
        if code != 0:
            return code, out
        story = attempt.story
        subject = REVERT_SUBJECT.format(story=story.id, title=story.title)
        body = REVERT_BODY.format(commits=attempt.revert_of[:12], reason=attempt.reason)
        return tree.attempt("commit", "-m", f"{subject}\n\n{body}")

    async def settle_conflict(self, attempt: Attempt, tree: Git) -> dict[str, Any] | None:
        """L5, L6: a story-file clash holds the land, any other conflict queues a rebase."""
        names = (await self.run_off(tree.attempt, "diff", "--name-only", "--diff-filter=U"))[1]
        files = [n for n in names.splitlines() if n]
        story_file = story_spec.file_of(self.runtime.config, attempt.story.id)
        if attempt.revert_of:
            return await self.refuse_revert(attempt, tree, files)
        if files == [story_file]:
            return await self.merge_story_file_conflict(attempt, (tree, story_file))
        return await self.queue_rebase(attempt, tree, files)

    async def merge_story_file_conflict(
        self, attempt: Attempt, at: tuple[Git, str]
    ) -> dict[str, Any] | None:
        """L5: the story file is the branch copy plus the sprint's edits; a clash holds the land."""
        tree, file = at
        merged = await self.run_off(self.merge_copies, attempt, file)
        if merged.clean:
            return await self.complete_merge(attempt, tree, (file, merged.text))
        await self.drop_merge(tree)
        lines = LAND_STORY_CLASH.format(id=attempt.story.id, lines=file)
        return make_report(attempt.story, (Verdict.HOLD, lines))

    async def complete_merge(self, attempt: Attempt, tree: Git, written: tuple[str, str]) -> None:
        """Write the merged story file, add it and complete the merge commit."""
        file, text = written
        target = self.scratch_path / file
        system.make_dirs(target.parent)
        system.write_text(target, text)
        await self.run_off(tree.run, "add", file)
        await self.run_off(tree.run, "commit", "--no-edit")
        attempt.merge = await self.run_off(tree.head)

    def merge_copies(self, attempt: Attempt, file: str) -> Merged:
        """Write the three copies of the story file to the temp dir and merge them."""
        story, git = attempt.story, self.runtime.git
        token = system.token()
        system.make_dirs(system.get_temp_dir())
        sides = {"ours": story.branch, "base": story.base_sha, "theirs": attempt.head}
        paths = {}
        for side, rev in sides.items():
            paths[side] = system.get_temp_dir() / f"agile-team-{token}-{side}"
            system.write_text(paths[side], git.attempt("show", f"{rev}:{file}")[1])
        try:
            return merge_story_file(StoryFile(paths["ours"], paths["base"], paths["theirs"]))
        finally:
            for path in paths.values():
                system.remove(path)

    async def drop_merge(self, tree: Git) -> None:
        """Abort the merge and remove the land worktree."""
        await self.run_off(tree.attempt, "merge", "--abort")
        await self.clear_tree()

    async def queue_rebase(self, attempt: Attempt, tree: Git, files: list[str]) -> dict[str, Any]:
        """L6: abort, and queue a story rebase for the role that owns the files."""
        story, rt = attempt.story, self.runtime
        await self.drop_merge(tree)
        devops = story_rebase.is_for_devops(files, rt.owners(story))
        role = "devops" if devops else (story.developer or "developer")
        prefix = rt.config.upstream.story_prefix
        branch = format_story_branch(prefix, story.id, story.replays + 1)
        story.rebase = StoryRebase(attempt.head, story.base_sha, story.branch, branch, files, role)
        reason = CONFLICT_REASON.format(branch=story.branch, files=", ".join(files))
        conflict = {"files": files, "role": role}
        return make_report(story, (Verdict.BOUNCE, reason), bounce_to="land", conflict=conflict)

    async def refuse_revert(self, attempt: Attempt, tree: Git, files: list[str]) -> dict[str, Any]:
        """E4: a revert that conflicts is refused; the sprint branch is untouched."""
        await self.run_off(tree.attempt, "revert", "--abort")
        await self.clear_tree()
        why = f"conflicts in {', '.join(files)}"
        reason = REVERT_CONFLICT.format(story=attempt.story.id, why=why)
        return {"role": "runner", "status": "refused", "reason": reason, "story": attempt.story.id}

    # ----- the checks (L7)

    async def check(self, attempt: Attempt) -> dict[str, Any] | None:
        """Run the full checks on the merge; red bounces the story to implement."""
        rt, path = self.runtime, self.scratch_path
        config = rt.config.get_worktree_config(path)
        judging = fullcheck.Judging(rt.shell(path), rt.pipeline.checks.required_coverage())
        report = await self.run_off(
            fullcheck.run_checks,
            fullcheck.full_checks(config, test_reports.LANDING_FOLDER),
            judging,
        )
        await self.clear_tree()
        if report.passed:
            return None
        found = (Verdict.BOUNCE, report.reason())
        return make_report(attempt.story, found, bounce_to="implement", checks=report.summary())

    # ----- shipping (L8 to L10)

    async def deliver(self, attempt: Attempt) -> dict[str, Any] | None:
        """Local mode lands on green checks alone; otherwise CI decides."""
        if self.is_local:
            return await self.land_locally(attempt)
        refused = await self.push_landing(attempt)
        if refused is not None:
            return make_report(attempt.story, (Verdict.HOLD, PUSH_REFUSED.format(why=refused)))
        return await self.finish_pushed(attempt)

    async def land_locally(self, attempt: Attempt) -> dict[str, Any] | None:
        """P3, K3: fast-forward on green checks under the lock, with no push and no CI."""
        async with self.lock:
            carried = await self.take_carry(attempt)
            if carried is None:
                return None
            if not await self.move_checkout(attempt, carried):
                return await self.halt_diverged(attempt, "")
            self.runtime.record_checkout()
        return self.record_landed(attempt, Landed(attempt.merge), "none")

    async def push_landing(self, attempt: Attempt) -> str | None:
        """Push the merge to the landing branch and record it; the refusal text, or ``None``."""
        story, rt = attempt.story, self.runtime
        branch = format_landing_branch(rt.config.upstream.story_prefix, story.id)
        lease = Lease(branch, "", attempt.merge)
        refused = await self.push(lease)
        if refused is None and not attempt.revert_of:
            story.landed = Landed(attempt.merge, pushed=attempt.merge)
            rt.save()
        return refused

    async def push(self, lease: Lease) -> str | None:
        """Push in a worker thread; a guard refusal is the text."""
        try:
            return await self.run_off(self.runtime.upstream.push, lease)  # type: ignore[union-attr]
        except UpstreamError as error:
            return str(error)

    async def finish_pushed(self, attempt: Attempt) -> dict[str, Any] | None:
        """L8: wait for the landing CI, delete the landing branch, then act on the verdict."""
        story, rt, merge = attempt.story, self.runtime, attempt.merge
        result = await self.wait_ci(attempt)
        self.record_ci(attempt, result)
        try:
            return await OUTCOMES[result.verdict](self, attempt, result)
        finally:
            branch = format_landing_branch(rt.config.upstream.story_prefix, story.id)
            await self.run_off(rt.upstream.delete, Lease(branch, merge, ""))  # type: ignore[union-attr]

    async def wait_ci(self, attempt: Attempt) -> CiResult:
        """Wait for the checks of the merge; re-run an infra failure once per job."""
        story, rt = attempt.story, self.runtime
        watch = ShaWatch(rt.prs, rt.config.gates.ci_timeout_s)
        result = await watch.poll_result(attempt.merge, story.land_reran)
        due = self.find_reruns(attempt, result)
        if not due:
            return result
        await self.run_again(attempt, due)
        return await watch.poll_result(attempt.merge, story.land_reran)

    def find_reruns(self, attempt: Attempt, result: CiResult) -> list[Any]:
        """The infra checks whose one re-run at this head is not used yet."""
        reran = attempt.story.land_reran
        infra = [c for c in result.checks if c.kind is CheckKind.INFRA]
        return [c for c in infra if rerun_key(attempt.merge, label(c)) not in reran]

    async def run_again(self, attempt: Attempt, due: list[Any]) -> None:
        """Re-run each job once, then look until it shows a new attempt."""
        story, prs = attempt.story, self.runtime.prs
        for check in due:
            story.land_reran.append(rerun_key(attempt.merge, label(check)))
            await self.run_off(prs.rerun, check.link)
        self.runtime.save()
        for _ in range(CI_LOOKS):
            seen = await self.run_off(prs.list_checks, attempt.merge)
            if all(self.has_moved(seen, c) for c in due):
                return
            await system.async_sleep(CI_POLL_S)

    def has_moved(self, seen: list[Any], check: Any) -> bool:
        """True when the commit shows a check of the same job with another link."""
        return any(label(c) == label(check) and c.link != check.link for c in seen)

    def record_ci(self, attempt: Attempt, result: CiResult) -> None:
        """Remember the landing CI on the story and log it."""
        story = attempt.story
        found = StoryCi(attempt.merge, str(result.verdict), "landing")
        story.ci = found
        data = {**found.__dict__, "checks": check_lines([result]).splitlines()}
        self.runtime.events.emit(Event(EventKind.STORY_CI, None, story.id, data))

    # ----- the verdicts

    async def move_sprint(self, attempt: Attempt, result: CiResult) -> dict[str, Any] | None:
        """L9, K2: green; under the lock push the sprint branch and fast-forward the checkout."""
        async with self.lock:
            stopped = await self.push_and_follow(attempt)
        if stopped is not None or not attempt.merge:
            return stopped
        return await self.complete(attempt, result)

    async def push_and_follow(self, attempt: Attempt) -> dict[str, Any] | None:
        """K2 steps 1 to 5; ``None`` with a merge still set means the move was made."""
        entry = attempt.entry
        assert entry is not None
        carried = await self.take_carry(attempt)
        if carried is None:
            return None
        refused = await self.push(Lease(entry.branch, entry.pushed, attempt.merge))
        if refused is not None:
            return await self.follow_remote(attempt)
        entry.pushed = attempt.merge
        if not await self.move_checkout(attempt, carried):
            return await self.halt_diverged(attempt, "")
        self.runtime.record_checkout()
        return None

    async def complete(self, attempt: Attempt, result: CiResult) -> dict[str, Any]:
        """The sprint branch moved: open the sprint PR once, close the story PR, report."""
        entry, story = attempt.entry, attempt.story
        assert entry is not None
        await self.open_sprint_pr(entry)
        landed = Landed(attempt.merge, pushed=attempt.merge, pr=entry.pr)
        if story.pr is not None and not attempt.revert_of:
            note = LANDED_NOTE.format(branch=entry.branch, merge=attempt.merge)
            await self.run_off(self.runtime.prs.close, story.pr, note)
        return self.record_landed(attempt, landed, str(CiVerdict.GREEN))

    async def open_sprint_pr(self, entry: StackEntry) -> None:
        """The first landing opens the sprint PR as a draft; after that it is found by number."""
        if entry.pr is not None:
            return
        rt = self.runtime
        spec = BoundaryRunner(rt).make_spec(entry, PrMode.DRAFT)
        pr = await self.run_off(rt.prs.create, spec)
        entry.pr, entry.url, entry.base, entry.mode = pr.number, pr.url, spec.base, spec.mode

    def record_landed(self, attempt: Attempt, landed: Landed, ci: str) -> dict[str, Any]:
        """Record the landing, log it and return the passing report."""
        rt, story = self.runtime, attempt.story
        if not attempt.revert_of:
            story.landed = landed
        parents = rt.git.attempt("rev-list", "--parents", "-n", "1", attempt.merge)[1].split()[1:]
        entry = attempt.entry
        data = {"merge": attempt.merge, "parents": parents, "ci": ci}
        data |= {"sprint_branch": entry.branch if entry else "", "pushed": landed.pushed}
        data["carried"] = dict(attempt.carried)
        rt.events.emit(Event(EventKind.STORY_LANDED, None, story.id, data))
        land = {"merge": attempt.merge, "ci": ci}
        return make_report(story, (Verdict.PASS, "landed"), **land)

    async def bounce_red(self, attempt: Attempt, result: CiResult) -> dict[str, Any]:
        """Red landing CI sends the story to implement; the sprint branch was never touched."""
        if not attempt.revert_of:
            attempt.story.landed = None
        self.runtime.save()
        reason = check_lines([result]) or f"landing CI is {result.verdict}"
        land = {"ci": str(result.verdict)}
        return make_report(attempt.story, (Verdict.BOUNCE, reason), bounce_to="implement", **land)

    async def hold_ci(self, attempt: Attempt, result: CiResult) -> dict[str, Any]:
        """Infra that did not run twice, or no checks at the timeout: hold, never green."""
        reason = CI_HELD.format(sha=attempt.merge[:12], verdict=result.verdict)
        return make_report(attempt.story, (Verdict.HOLD, reason), ci=str(result.verdict))

    async def follow_remote(self, attempt: Attempt) -> dict[str, Any] | None:
        """G4, R2: give up the merge; follow a remote that descends from ours, else halt."""
        entry, up = attempt.entry, self.runtime.upstream
        assert entry is not None and up is not None
        await self.give_up(attempt, GIVE_UP_REFUSED)
        await self.run_off(up.git.attempt, "fetch", up.settings.remote, entry.branch)
        remote = await self.run_off(up.read_remote_head, entry.branch)
        follows = bool(remote) and await self.run_off(up.is_ancestor, entry.pushed, remote)
        if follows and await self.move_to_remote(remote):
            return None
        return await self.halt_diverged(attempt, remote)

    async def move_to_remote(self, remote: str) -> bool:
        """R2: bring the main checkout and the sprint entry to the remote head, if it can."""
        rt, up = self.runtime, self.runtime.upstream
        entry = self.sprint_entry
        assert entry is not None and up is not None
        if await self.run_off(up.is_ancestor, remote, "HEAD"):
            entry.pushed = remote
            return True
        if not await self.run_off(up.is_ancestor, "HEAD", remote):
            return False
        if not await self.run_off(up.advance_to, remote):
            return False
        rt.record_checkout()
        entry.head = entry.pushed = remote
        return True

    async def halt_diverged(self, attempt: Attempt, remote_sha: str) -> dict[str, Any]:
        """The sprint branch diverged: halt as checkout drift naming both heads."""
        rt, entry = self.runtime, attempt.entry
        branch, pushed = (entry.branch, entry.pushed) if entry else ("", "")
        text = SPRINT_BRANCH_DIVERGED.format(
            branch=branch,
            remote=rt.config.upstream.remote,
            remote_sha=remote_sha or "unknown",
            pushed=pushed,
        )
        return halted_report("runner", rt.halt_run(Halt(HaltKind.CHECKOUT, text)))


OUTCOMES = {
    CiVerdict.GREEN: Lander.move_sprint,
    CiVerdict.RED: Lander.bounce_red,
    CiVerdict.MAIN: Lander.bounce_red,
    CiVerdict.INFRA: Lander.hold_ci,
    CiVerdict.PENDING: Lander.hold_ci,
    CiVerdict.NONE: Lander.hold_ci,
}
