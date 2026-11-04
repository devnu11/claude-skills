# ADR-0093: A landing carries the runner's unpushed commits onto its merge

Story: s180. Design: `agile-team/docs/design/s180.md` (C1 to C11).
Amends ADR-0084's s163 amendment ("A landing never pushes a stale merge").

## Context

s163 made a pushed landing give up its merge whenever the merge's first
parent was no longer the sprint head. The runner's own bookkeeping commits on
the main checkout move that head too: story-file commits from the intake,
shares, the PO's story-admin edits, and storyless steps such as a
DevOps config change. Each one made during a landing's CI wait cost the
landing a fresh merge, full checks and CI run (sprint 51: s165 after the
liaison's q20, and after the DevOps config commits for s161). With parallel
stories the landings run back to back, so this happened to almost every
landing.

The story asked to choose between deferring those commits and moving the
landing on top of them.

## Decision

1. **Carry, don't defer.** When a landing's CI is green and the sprint head
   moved past the merge's first parent `B`, the runner replays `B..head` onto
   the merge `M` in the land worktree (`cherry-pick
   --keep-redundant-commits`). It pushes the sprint branch to `M`, moves the
   main checkout to the replayed tip with `reset --keep` while HEAD is still
   the old head, and remaps the moved shas in `state.json`
   (`rewrite.remap_state`). One `landing-carried` event pairs old and new.
2. **Only safe commits are carried.** The carry is refused, and the landing
   gives up as before, when the merge's first parent `B` can't be read
   (the drop then names no commits), when the head doesn't descend from `B`, when a
   carried commit is a merge or is already on the remote, when an open story
   was forked from (or is queued to rebase onto) a carried commit, or when
   the replay conflicts.
3. **The remote only gets CI-checked merges.** The sprint push sends `M`, not
   the replayed tip. The carried commits stay local until the next landing
   or the sprint end, as the bookkeeping commits always were.
4. **No new fork while a landing runs.** The scheduler doesn't fork or
   replay a story branch from the sprint head while a land or landing revert
   runs. That would base the story on a commit the carry may replace.
5. **A drop says what moved the head.** `landing-dropped` and the land
   report list every commit of `B..head` (short sha, subject) and the carry's
   refusal. A non-holding `landing_dropped` hand-over shows them to the PO.

## Consequences

- The runner now rewrites commits it made itself, but only unpushed ones on
  the sprint branch. A story-file or share commit made during a CI
  wait can get a new sha when the landing completes. `file_commits` and
  the other remapped fields follow it, and messages or tells already sent
  keep the old sha. The `landing-carried` event is the map.
- The old sha of a carried commit is still in the `requirement-changed`
  events a step logged before the carry. `requirements log` reads the
  trailers from git and isn't affected.
- A story ready to start its first step waits for the running landing. That
  delay is at most one landing CI run, against a whole extra round per
  waiting landing before.
- Deferring was rejected. Many writers would have to wait, one already
  running could still move the head, and back-to-back landings could starve
  the intake.
