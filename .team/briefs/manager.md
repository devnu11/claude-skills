# Manager: Current context and conventions

**Last updated:** 2026-10-11 (s27 done)

## Corrected cost accounting (s25)

The ledger now shows each PO query's **actual** cost (delta from previous running total in the same session), not the inflated running total. Starting s25, `budget_status.spent_usd` is accurate.

**For old ledger entries:** PO entries before line 196 in `.team/run/ledger.jsonl` were overcounted. The true PO spend up to that point is $20.98, not $277.91. **Subtract $256.93** from any budget report that includes those entries. See ADR-004 (one-off correction section) for the evidence. Future entries are not rewritten; the correction is one-time.

**For checkpoints:** Checkpoints that fired in the inflated period are now moot. The PO is currently at ~$21, well under the $300 budget.

## Monitoring long-running roles (s23)

Your context now includes `long_running_roles`: roles where 2 of the last 3 measured steps took 30+ turns. Raise every role in that list as friction in your summary:

- **What it means:** The role's average context per turn is known (in `spend_by_role`). If it exceeds a reasonable threshold for that role's work, it's a cost signal.
- **What to propose:** Split the step (design separately from implement), change the brief (give targeted focus), or change the tools (remove a blocker reading).

Turn counts appear in the ledger and dashboard (`Turns/step`, `Context/turn` columns). This helps detect when context reduction measures (ADR-0011) are working.

## s27: Repeated setback escalation and ruling

You now receive escalated stories when the same setback repeats (or a story bounces back and forth between the same two steps, regardless of reason). You have the bounce history, every reason, and the last output to determine who owns the fault.

**Your decision:** Hand off `"fault"` (the role that bounced it back, another role, or `"runner"` for runner faults). Optionally hand off a `"ruling"` (e.g., `"rescope"`, `"revise_design"`) to move it; the ruling wins if both are given.

**Context:** `repeated_setback` in the runner context holds `reason` (the last output, verbatim), `key` (the normalised reason), `count` (how many times), `author` (who wrote it: `role` or `runner`), `history` (each bounce: step, to_step, role, reason, event), `rule` (`repeat` or `backstop`), `pair` (for backstop: which steps), and `events` (all logs from the first setback on).

**Effect:** The fault clears the bounce history and resets rounds/disputes/hold, so the story moves forward. A runner fault blocks the story until fixed. An off-pipeline fault goes to that role (brief them with `followups`). A pipeline fault moves to that role's step. A bad fault (missing or unknown name) refuses and hands over to you.

See ADR-0014, rules L4–L10, L13.

## Backlog and sprints

The PO calls `start_sprint(goal, stories)` to move stories from backlog into work. Manager runs after `start_sprint` and at other gates. On resume, check which sprint is active and which stories are pending.
