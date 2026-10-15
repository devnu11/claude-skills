# ADR-0077: The sprint start rebases once more, and a failing start check is recorded as known failures

**Date:** 2026-10-15 (s152 design)
**Status:** Accepted
**Amends:** ADR-0041 (R12: the start sync changed nothing since s108), ADR-0075 (its "follow-up start rebase" consequence)

## Context

Since s108 the start boundary's `sync` only counted how far main moved and
changed nothing, so a team stopped while main moved (a PR merged between
sprints) worked a whole sprint behind it. The start `check` ran the full
checks, and a failure became a DevOps fix step that held the sprint's
stories until it passed, and escalated when it repeated.

The human asked (2026-10-14, restated at the sprint 44 end) for the start
to rebase once more (the end already rebased, but the team may have been
stopped since), to run the tests and capture the known failures, and for
each failure to become a story through the liaison, who places it at the
top of the sprint or later. A failure must never halt the run.

## Decision

1. **The start `sync` rebases.** After the fetch, when nothing is pinned
   (`b.sync_from` empty) and the target is an ancestor of HEAD (`behind()
   == 0`), it emits `current` and runs no git rebase: a branch already on
   the target is left alone. Otherwise it pins `sync_from`, calls the same
   `Upstream.rebase_onto` as the end, and settles a `rebased` result the
   same way (`rewrite.remap_state`, `record_checkout`, `rebased` event,
   unpin). A pinned `sync_from` always goes through `rebase_onto`, so a
   crash after the rebase still remaps.
2. **A start conflict holds nothing.** `rebase_onto` already aborts it.
   The start emits `conflict` (no hold), posts `START_CONFLICT` to the
   liaison, unpins and goes on to `check` on the unchanged branch. It is not
   sent to DevOps: the end's DevOps path (ADR-0076) is tied to the `rebase`
   stage and its CI gate. Routing a start conflict to DevOps is a possible
   follow-up once s151 AC6 is in.
3. **A failing start check holds nothing.** Only at the start, a failed
   full check makes no fix step and no setback. The runner posts
   `KNOWN_FAILURES_NOTE` to the liaison and finishes the start boundary with
   one `done` event that carries `known_failures` (the failing test ids),
   `sha`, `reason` (the failed checks' text) and `checks`. The end check is
   unchanged (DevOps fix step, escalation).
4. **The ids.** `CheckResult` keeps the JUnit ids of its failed cases. The
   known failures are, for each failed check in order, those ids, or the
   check's name (`lint`, `coverage`, `e2e:<env>`) when it has none (no
   report, a lint failure, a coverage shortfall). Duplicates go.
5. **The hand-over.** A boundary report whose event has `known_failures`
   raises the PO trigger `known_failures`: ask the liaison for a story with
   `request_story`, unless an open story covers them. The liaison places
   the story with the existing `story new --sprint current|next|backlog
   [--after <id>]`; `current` puts it at the top of the running sprint. No
   new placement mechanism is added.
6. **Where the ids are recorded.** They are recorded on the start
   boundary's closing `boundary` event, not on the `sprint-start` event.
   `start_sprint` writes `sprint-start` before the start boundary runs, the
   event log is append-only, and the dashboard reads `sprint-start` as the
   sprint's window and goal, so a second `sprint-start` event would split
   the sprint. (Open question to the liaison: s152/AC2.2 names the
   `sprint-start` event.)

## Consequences

- A team stopped across a merge to main starts the next sprint on it, and
  every recorded hash is remapped as at the end.
- Hashes now change at both edges, still never within a sprint.
- A red start no longer blocks the sprint's stories or reaches the
  Manager. The same failures at the next start raise the hand-over again;
  the PO doesn't ask twice for a story already open.
- A start conflict leaves the team branch behind main. The sprint end's
  as-built PR then conflicts with main, GitHub runs no `pull_request`
  workflow on it (verdict `none`), and nothing rebases until the human does
  it by hand. That is the state before s152 too; the liaison is now told at
  every start.
- `START_NOTES` and the "nothing changes until the next sprint end" note
  go.
