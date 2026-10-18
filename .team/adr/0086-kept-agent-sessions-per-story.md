# ADR-0086: Each role's agent session on a story is kept and resumed

Story: s159. Design: `agile-team/docs/design/s159.md` (K1 to K4). Extends
ADR-0010's session rules from the PO to the story roles.

## Context

Every role step started a fresh agent session. It re-read the story, the
design and the code, even when the same role had worked on the same story an
hour before. The PO's session is already resumed, and its cost is ledgered
as the session's delta.

## Decision

1. `StoryState.sessions[role]` keeps the session id, model, effort, provider
   and the SDK's running cost. The next step of that role on that story
   resumes it when the model, effort and provider are the same.
2. A kept session ends:
   - when the story is done or cancelled;
   - when `revert_story` runs;
   - on any bounce or return to an earlier step, because the earlier context
     now misleads;
   - when an `override` changes the role's model.

   A query that fails because the context is too long drops that session,
   and the next step starts fresh.
3. A resumed step's cost is the delta, as for the PO. The ledger entry and
   the step event say `resumed`, and the step event records cache-write
   tokens. The budget reserve uses fresh steps only.

## Consequences

- Repeat steps get cheaper, and their costs are no longer comparable with
  fresh ones. That is why they are flagged and kept out of the reserve
  statistics.
- An interrupted step's session survives (`in_flight.session`), so the
  next step continues where the cut-off one stopped.
