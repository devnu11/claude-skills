# ADR-0068: A Flow chart box counts the running step until the ledger has it

**Date:** 2026-10-14 · **Story:** s137 · **Design:** `agile-team/docs/design/s137.md`

## Context

The Flow chart's role boxes showed the scope's totals from the ledger and the
finished steps only (`scopeTotals`, D5/ST10). A ledger row is written when a
step ends, so a running role on its first step of a story read
`0 · $0.00 · 0s` in Story scope. The running step's tokens and cost are in the
heartbeat (`heartbeat.step.tokens`, `cost_usd`, summed from the same turns as
its rate), and its awake time comes from its open `steps` row.

The runner settles a step in this order: ledger row, then the tree settle
(git, may take a while), then the meter closes and `step-end` is emitted. For
a while the ledger already holds the step while the heartbeat still shows it.

## Decision

The Flow chart reads `flowTotals(view)`: `scopeTotals(view)` plus the live
step's numbers on its role, when the live step is in scope.

- Tokens and cost come from `heartbeat.step` until a ledger row of the same
  role and story written at or after the step's `started_at` exists.
- Awake seconds come from the role's open `steps` row (`awakeSoFar`) while it
  is open; once `step-end` closes it, the finished step's own `seconds` count.
- `scopeTotals` keeps its ledger-only meaning.

No snapshot field, runner change or dependency is added.

## Consequences

- A running role's numbers grow on each snapshot in every scope, and a step
  is never counted twice across the settle window.
- The live cost is the runner's estimate; the box switches to the ledger's
  cost when the step is recorded, so the dollar figure may move a little at
  that moment.
- A running role always has a totals entry, so it is neither `idle` nor
  dimmed.
- Totals elsewhere (Cost tab, `scopeTotals`) still count finished work only.
