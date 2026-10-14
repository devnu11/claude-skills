# ADR-0055: Stories join the running sprint with add_to_sprint; restarts need a reason

Story: s122. Design: `agile-team/docs/design/s122.md`.

## Context

Since s3 (B3, B5), `start_sprint` was the only way into a sprint. To add one story
mid-sprint, the PO had to start sprint N+1 listing the old stories plus the new one.
That ran the start boundary (fetch and sync) and queued a Manager turn and a PO
session renewal, and the sprint got a new review branch. The human asked (t79,
recommendation 9) for adding work without any of that. Sprints were also being
restarted only to add work.

## Decision

- A new PO tool, `add_to_sprint(stories, reason)`, sets `sprint = N` on open
  stories. The sprint number, goal, status, boundary and upstream state stay as
  they are. No Manager or PO renewal is queued. The stories are placed the way
  `prioritise` places them (listed first, never pulled), recorded as a
  `Change.SPRINT` reorder.
- It is refused, with nothing changed, for: a pending boundary; no open sprint
  (`sprint == 0` or `upstream.closed >= sprint`, because a closed sprint's review entry
  is already built); unknown, done or cancelled ids; a story already in the
  sprint; a `depends_on` that is not done and not in the sprint after the add;
  a blank reason.
- A new event kind, `sprint-add`, records `{sprint, stories, reason}`.
- `start_sprint` needs a `reason` while the current sprint has unfinished
  stories. The reason goes into the `sprint-start` event.
- The Board and the review PR need no change, because both already select
  stories by `sprint == N` at the time they are read or built.

This supersedes s3 B3 ("the only way into a sprint") and B5 ("adding mid-sprint
means a new start_sprint … intended").

## Consequences

- Adding scope mid-sprint no longer gets a Manager review. The reason in the
  `sprint-add` and `priority` events is the audit trail, and the next
  scheduled Manager turn sees the sprint's stories.
- Tests and callers that restart a sprint with unfinished stories must pass a
  reason.
- An added story's dependencies come from state, not from a reload of the files.
  A file edit takes effect at the next start or `start_sprint` (as in ADR-0046).
