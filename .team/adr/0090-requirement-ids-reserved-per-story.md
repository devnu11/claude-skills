# ADR-0090: Requirement ids are reserved per story

Story: s178. Design: `agile-team/docs/design/s178.md` (R1 to R9).

## Context

With story branches (ADR-0084) several architects work at once, each in a
worktree forked from the sprint head. The brief's "next free id" was one above
the highest `REQ-NNN.md` in that worktree, so every story forked from one head
got the same id. In sprint 51 s164, s165 and s166 all wrote REQ-174 and
REQ-175, their landings conflicted in `docs/requirements`, and the ids were
renumbered by hand. Reading other branches alone doesn't fix it: two
architects briefed before either writes a file see the same files.

## Decision

- The runner reserves a block of five ids for a story when it writes the
  architect's brief, and stores the block's first number in `state.json` as
  `StoryState.req_block` (0 = none).
- A new block starts one above every id held by the sprint head and by the
  other open stories of the sprint: their branches (`git ls-tree`), their
  worktrees (files not yet committed) and their blocks. A clean block is
  kept across briefs; a clashing one is replaced.
- The design gate (story branches only) bounces a design that adds an id held
  on the sprint head, or outside its own block by another open story's files
  or block, naming the id and the holder.
- Nothing is reserved without story branches: one checkout runs one step at a
  time.

## Consequences

- Parallel stories get distinct ids, and the first claim wins: the story that
  writes into someone else's block is the one bounced, never both.
- A story that uses fewer than five ids leaves gaps in the numbering. Ids are
  labels; gaps already exist (REQ-051 to REQ-055) and cost nothing.
- A cancelled story's ids, or those of a story that left the sprint, stop
  counting at once. A fresh reservation reuses them when they are the top.
  A kept block is never moved down to fill a gap.
- Each architect brief and design gate in branch mode runs a few `git
  ls-tree` calls per open story.
