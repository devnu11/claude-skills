# ADR-006: An interrupted step's edits go into a reverted commit

Status: accepted (s9). Date: 2026-10-11.

## Context

A role step can be cut off by an error, a usage limit, `stop --now`, or a
kill (`kill -9`, power loss, Ctrl-C). Before s9 its edits stayed
uncommitted. Preflight then refused the dirty tree, the liaison stashed the
files by hand (s7, `stash@{0}`), and the next step on the story started from
scratch: s29's ~1,650 lines ended up in a quarantine commit that no brief
mentioned. The human (m3) asked to keep the edits either as a commit that is
reverted at once or as a named stash. The Architect picks.

## Decision

1. The runner commits **every** changed path as
   `chore(team): interrupted step by <role> on <story>`, then reverts that
   commit at once, as quarantine does. The sha is stored in `state.json`, on
   the story and in the run's pending list.
2. This happens wherever a step ends without settling: in `halt_run`
   (limit, crash, SIGTERM), in `_step_failed` (any other error), and on
   `start --resume` when `state.json` says `running` but no live process
   holds `runner.pid` (killed).
3. The next brief on that story offers the work back
   (`git cherry-pick -n <sha>`), and the PO's next opening prompt lists the
   interrupted steps.
4. `running` with no live pid is shown as `interrupted`. That status is
   derived and never stored.

## Alternatives rejected

- **Named stash.** Roles' Bash allows `git cherry-pick -n` but not
  `git stash`, so no role could reuse a stash itself. Stashes are shared
  across worktrees (the review worktree, s29), are easy to drop, and leave
  no trace in `git log`.
- **Split the edits into in-scope (commit) and out-of-scope (quarantine).**
  Half-done work should not land on the story as if a step had finished, and
  it must not pass any gate. One reverted commit keeps all of it together.
- **Leave the edits for the human (s8's H15).** That is the problem this
  story fixes.

## Consequences

- Each interruption with edits adds two commits (save and revert) to the
  team branch, like quarantine. The human squashes as usual.
- `status` and the dashboard never show `running` without a process.
- A pid reused by another process looks alive. The run is then treated as
  live, and resume refuses the dirty tree.
