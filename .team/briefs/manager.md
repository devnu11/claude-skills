# Manager: Current context and conventions

**Last updated:** 2026-10-10 (s23 done)

## Monitoring long-running roles (s23)

Your context now includes `long_running_roles`: roles where 2 of the last 3 measured steps took 30+ turns. Raise every role in that list as friction in your summary:

- **What it means:** The role's average context per turn is known (in `spend_by_role`). If it exceeds a reasonable threshold for that role's work, it's a cost signal.
- **What to propose:** Split the step (design separately from implement), change the brief (give targeted focus), or change the tools (remove a blocker reading).

Turn counts appear in the ledger and dashboard (`Turns/step`, `Context/turn` columns). This helps detect when context reduction measures (ADR-0011) are working.

## Backlog and sprints

The PO calls `start_sprint(goal, stories)` to move stories from backlog into work. Manager runs after `start_sprint` and at other gates. On resume, check which sprint is active and which stories are pending.
