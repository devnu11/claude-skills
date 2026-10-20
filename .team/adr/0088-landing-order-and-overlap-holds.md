# ADR-0088: Landings go in the PO's order, smallest first, and overlapping designs wait

Story: s163. Design: `agile-team/docs/design/s163.md` (Q1 to Q8, F1 to F8).
Amends ADR-0084 decision 2 (the landing order).

## Context

s159 landed stories one at a time, in the order they passed acceptance. The
human's direction (2026-10-19): there is no parallelism in integration, the
PO orders it, and small stories go first, because the team of a larger story
has more context to resolve a merge conflict. The PO must also avoid running
stories whose work conflicts, by looking at the designs for overlap before
work goes on.

## Decision

1. **One landing queue.** Landings stay one at a time. Stories waiting
   behind the one landing go in the PO's order (`order_landings`), then the
   rest smallest first (lines added plus deleted since the story's base,
   ties by story id in number order). A landing revert takes its turn in the
   same queue, so a revert and a land never share the land worktree at once.
   An order that departs from smallest first needs a reason, which goes in a
   `landing-order` event.
2. **Leaving the queue drops the placement.** A story whose landing holds or
   bounces leaves, and rejoins by size when it is ready again. The one now
   landing is saved (`RunState.landing`), so after a crash it goes first.
3. **A design names its files.** Every design has a `## Files` section, one
   path or glob per line, and the design gate checks it is there.
4. **Overlap holds a design, not a landing.** When a story passes design
   while another open story in the sprint is past design, the runner
   compares the two Files lists and the other branch's changed files. An
   overlap holds the story at design (`overlap`, a per-story hand-over). The
   runner lifts the hold when the other stories have landed, left or been
   cancelled. The PO can lift it earlier with `release_story` and a reason.
   The lift drops the worktree, so the next step replays the branch onto the
   current sprint head.
5. **Design-step docs don't count.** `.team/**`, the architecture index, the
   design and requirement folders are left out of the comparison: every
   design writes them, and their clashes go through the story rebase.

## Consequences

- Before a sprint with parallel stories, the architect lists each story's
  files. The PO sees each overlap as it happens and decides whether to let
  the story wait or release it.
- Glob matching is `fnmatch` on the lists. Two globs that cover the same file
  without matching each other aren't caught, and the landing conflict path
  still catches the real clash.
- A held design still keeps its worktree until the lift, so it counts toward
  `max_open_stories` while it waits.
