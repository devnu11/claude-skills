# ADR-0082: A stuck Sprint Backlog is reported, not refilled from the Product Backlog

Story: s156. Design: `agile-team/docs/design/s156.md`. Amends ADR-0057 and ADR-0065.

## Context

s124 (ADR-0057) gave a stuck sprint a `ready_backlog` hand-over: the runner listed
ready Product Backlog stories and told the PO to `add_to_sprint` them, even while
a question was open. s128 (ADR-0065) made it repeat on every idle pass under
`until-blocker`. It also refused `done` and `blocked` while Product Backlog
stories were ready, and ended the run after 3 hand-overs with no `start_sprint` or
`add_to_sprint`. In sprint 45 the human kept only s151–s153 in the sprint. A test
cascade then held every gate, and the PO was pushed to refill the sprint from the
Product Backlog on every idle pass (s150, s10, s12, s138, s144). The run halted
twice with "the PO did not start a sprint or add ready stories". The human meant
the rule to pull from the Sprint Backlog: the sprint they chose is the sprint the
team works on, and a blocker should reach them.

## Decision

1. **No refill offer.** The `ready_backlog` trigger, `Router._offer` and
   `RunState.offered` go. While the Sprint Backlog has unfinished stories, no
   idle pass lists Product Backlog stories.
2. **A stuck Sprint Backlog is a hand-over that is never quiet.** With no
   boundary pending and no question open, the runner hands over
   `sprint_backlog_stuck`: each story's stall reason, and the actions the PO may
   take on those stories. While a question is open the run waits, as before s124.
   A held boundary and an empty sprint still give the quiet `stalled`.
3. **A cap reports the blocker.** `RunState.stuck_asks` counts these hand-overs.
   A step, a PO call that isn't refused to a tool in `po_tools.STUCK_RESETS`,
   `start_sprint` or `add_to_sprint` resets the count. At 3, the runner sets the
   run `blocked` ("the Sprint Backlog is stuck" plus each reason) and posts it to
   the liaison. This holds under both cadences.
4. **`until-blocker` ends on the Sprint Backlog.** `done` and `blocked` are
   refused only while a Sprint Backlog story can move (`sprint_end.can_move`,
   which the router's step test also uses, plus the relay's blocked stories). A
   ready Product Backlog story never causes the refusal.
5. **The next-sprint hand-over stays.** At a complete sprint under `until-blocker`
   the ready Product Backlog list and its cap (`keep_going_asks`) are unchanged.
6. **`add_to_sprint` stays a deliberate PO action**, never runner advice for a
   stuck sprint.
7. **Names say which backlog.** The runner's names and PO-facing texts on these
   paths say Product Backlog or Sprint Backlog. The dashboard's Backlog view
   and the liaison's `--place backlog` keep their names. They are interfaces, and
   the charter records them.

## Consequences

- A sprint cadence run with a stuck Sprint Backlog no longer ends `idle` after
  one quiet pass. It costs up to 3 PO turns, then ends `blocked` with a note the
  liaison relays. `idle` with "Nothing in sprint N can move." is now only for a
  held boundary or an empty sprint.
- The team no longer keeps busy on Product Backlog stories while the human
  hasn't answered. It waits, and the open question is the report.
- A PO that calls `request_story` on every turn never reaches the cap. Each call
  reaches the liaison, so the human still sees the blocker.
- `KIND_REFUSALS` now takes the runtime rather than the state, because "can
  move" needs the relay's blocked stories.
- `state.json` files with `offered` still load (`RUN_DROPPED`).
