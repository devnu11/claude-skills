# Manager: Current context and conventions

**Last updated:** 2026-10-10 (s19 done)

## s19: Runner calls you automatically at gates (s19)

The runner now automatically calls you at sprint start, model overrides, and budget checkpoints—no PO mediation. Your step is story-less and gets a standard brief listing the reason (e.g., "Manager review due: sprint start"). You are called before any sprint story steps, so you set up budget and model decisions before the pipeline runs.

See ADR-0009 for the routing architecture.

## Backlog and sprints

The Product Owner must call `start_sprint(goal, stories)` to move stories from the backlog into work. Manager runs after `start_sprint` and at other gates. Stories in the backlog cannot proceed; ensure the PO has explicitly committed them to a sprint before they reach critical steps.

On resume, check which sprint is active and which stories are still pending.
