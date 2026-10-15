# ADR-0078: A start ledgers the spend a crash cut off, from turns.jsonl

**Date:** 2026-10-15 · **Story:** s10 · **Design:** `agile-team/docs/design/s10.md`
· **Amends:** ADR-004 (`agile-team/docs/adr/ADR-004-po-cost-deltas.md`), rule 4

## Context

The ledger gets a row only when a query returns. A PO query can run for hours,
because the PO runs role steps inside its tool calls, so a crash before
`PoRun._record` drops all of its cost. In the last run the ledger showed $7.36,
which covered role steps only. The live meter already writes every turn's tokens
and estimated cost to `turns.jsonl` as the turn arrives (ADR-0032).

ADR-004 rule 4 assumed an unrecorded PO query is paid for by the next query's
running total. That holds only when a later query resumes the same session, and
only if Claude Code carried the cut-off cost into that total. Nobody can check
this from the runner, because it depends on how the CLI child was stopped.

## Decision

- Every `start` reconciles the ledger from `turns.jsonl` before the run begins,
  unless a runner is alive. Turns and rows are matched by `(role, story)`. A
  key's turns after its latest ledger row become one row, with the sum of their
  estimated cost and tokens, stamped with the start time. Unparseable lines are
  skipped.
- The reconciled amount for the PO is stored on the session baseline
  (`SessionCost.reconciled`). The next query that resumes that session takes
  `min(reconciled, delta)` off its delta. A new baseline starts at 0.
- The row is an ordinary `Entry`, with no new field, event kind or snapshot key.
  The start prints one stderr line per reconciled row.

## Consequences

- A crash no longer drops a query's spend. The reconciled cost is the per-family
  estimate, not Claude Code's figure.
- The same spend never counts twice: a reconciled row is later than the turns it
  covers, and a resumed session nets out what was reconciled. If the CLI did
  not carry the cut-off cost, that next query is under-counted by at most the
  reconciled amount, which is the smaller error.
- On the first start after s10 ships, a key whose last query was never ledgered
  is reconciled too, so the human may see one such line. Older gaps, followed
  by a ledgered query of the same key, stay lost (out of scope).
- A reconciled row fires no Manager budget checkpoint. The ceiling still applies
  at the next PO query.
- Readers cannot tell a reconciled row from a normal one in the ledger.
  `events.jsonl` has nothing either. The stderr line is the only trace.
