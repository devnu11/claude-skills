# Manager: Current context and conventions

**Last updated:** 2026-10-12 (s68 done)

## s68: Implement gate cycle time reduced to ~4 minutes (no new Manager context)

Gate now runs coverage command once instead of test then coverage. Cycle time improves from 7–9 minutes to ~4 minutes. Test failure detection is now pattern-based from coverage output instead of a separate run. No impact on escalation, ruling, or your decision-making logic. See ADR-0033.

## s43: Gate command timeouts (no new Manager context)

When a gate times out, it bounces the story like any other failure. No escalation to you unless the same timeout repeats (s27 logic). The bounce reason names the hung test if found, so the developer and tester know what to fix. See ADR-0030, design `agile-team/docs/design/s43.md` (AC1–AC2).

## s47: Waiting status shows what run waits on (no new Manager context)

While the router waits on open questions, `status_reason` shows `"waiting on answers: s40 waits on m42; the run waits on m43"` (W3). When a run halts while waiting, the halt note includes this context (W5). The wake logic is unchanged; polling picks up answers within 5 seconds (W1–W2). This is a visibility feature only; no change to Manager's escalation or ruling logic. See ADR-0025, design `agile-team/docs/design/s47.md`.

## s46: Code facts in context; advance ruling moves stories forward

Your context now carries `repeated_setback.code: {implemented, code_commits, code_in}`, showing whether the story's implementation is already in the branch (K6). New ruling: `advance` moves a story one enabled step forward, clearing loops and setting it active (A1). On a story with both fault and ruling, fault applies first; advance then moves it from the new step (A2). Advance is refused at the last step: `applied: false, why: "story {id} is at {step}, its last step; advance cannot mark it done"` (A3). Handoffs may carry `ruling_reason` (string, defaults to summary); ruling events log `{ruling, reason, now_at}` (A4). See ADR-0024, design `agile-team/docs/design/s46.md` (K6, A1–A4).

## s45: Fault rulings work on any story; report shows applied/unapplied

Your fault rulings now work on any story that needs a fault (not just repeated bounces). Report shows whether each fault/ruling was applied and why if not. New hand-over: `fault_not_applied` for missing/unknown faults.

**Fault path (M1):** Taken when `handoff.fault` is named OR `story.repeated` is set. Otherwise only `ruling` considered.

**Applied fault (M3):** On any story, moves `step` to named role (or `runner`), sets `status` from fault kind, clears hold/rounds/disputes/dispute/streak/run/repeated/escalated_by.

**Reason read early (M4):** Fault reason = repeated reason (if set), else last gate reason, else empty. Read before clearing repeated.

**Ruling after fault (M5):** Only applied if fault applied; otherwise reported unapplied with `reason: "the fault was not applied, so the ruling was not either"`.

**Report (M6):** `"fault": {applied, why, ...}` and/or `"ruling": {applied, why, ...}` show all decisions. Report goes in `run_role` result and hand-over lines.

Example: s29 was escalated with `repeated` set. Without `repeated`, it is blocked from a runner fault escalated by unit-tester. Now you can rule on either: fault to a role moves it; fault to runner keeps it blocked; ruling wins if fault applied.

See ADR-0023, design `agile-team/docs/design/s45.md` (rules M1–M7).

## s38: Corrected cost accounting and budget ceiling

Your context now carries corrected spend totals and the ceiling that halts the run. The PO's old entries (before s25) held running totals and overcounted by ~$1,025 in this repo. They are corrected on read; the ledger file is never rewritten.

**Budget context:** `budget.spent_usd` (corrected), `budget_usd` (the ceiling), `remaining_usd`, `pct_used`, `by_role` (corrected per role), `po_overcount_usd` (the correction just applied). When corrected spend reaches the ceiling, the runner halts the run (status `blocked`, exit 77) and only the human can raise `budget_usd` in `.agile-team.toml` and resume. See ADR-007, design `agile-team/docs/design/s38.md` (rule M1).

## s11: Test disputes and rulings at any step

Rulings now apply at any step, not just at round cap. Developers can hand off disputes (test contradicts design rule) and the story goes to `tests` instead of bouncing to `implement`. Free disputes: first `round_cap` per story cost no round; later disputes count rounds. Your context now includes `test_disputes_since_last_review` listing disputes since your last step. See ADR-0018, design `agile-team/docs/design/s11.md` (T10–T13).

## s29: Boundary escalation context

In addition to story escalations (s27), the runner's own boundary failures (sync conflict, check failure, review rebuild conflict, push reject) can escalate. You receive `repeated_boundary` in the context when the same failure repeats after a DevOps fix, with `edge` (start/end), `sprint`, `stage` (sync/check/review/push), `reason` (the failure output), `key` (normalised), `count` (repeats), `history` (earlier failures), and `events` (all logs). Decide whether to hold the human's answer or ask them for input, then the PO clears the hold with `continue_boundary(note)`.

See ADR-0015, design `agile-team/docs/design/s29.md` (rule U13).

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
