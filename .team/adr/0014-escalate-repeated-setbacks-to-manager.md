# ADR-0014: Escalate repeated setbacks to the Manager, not looping

**Date:** 2026-10-11 (s27 done)  
**Status:** Accepted  
**Relates to:** ADR-0009 (routing in code), ADR-0012 (gate and hold clearing), s11 (disputes), s19 (hand-overs), s26 (liveness)

## Context

**Sprint 8, events e451–e458:** Story s4 bounced back and forth between acceptance (Integration Tester) and e2e (Customer Proxy) four times over the same failure: no service running on 127.0.0.1:8799. The root cause was the runner's own failed start (s26), but neither role could see that or fix it. The loop ran until the round cap because:

1. Nothing compared one setback with the last one—only the round cap stopped loops.
2. A `return` verdict counts no round; a loop of returns never reaches the cap.
3. A malformed handoff bounced without a gate event, so its reason was never logged alongside others.

**Outcome:** The team needed the runner to detect identical or reworded repeated reasons and hand the story to the Manager instead of looping endlessly.

## Decision

### 1. Setback detection and recording (L1)

Every gate outcome with verdict `bounce`, `return`, or `hold` on a story is recorded as a `Setback(step, to_step, role, verdict, author, reason, event)` in `story.streak`. This includes a gated role's malformed handoff, which now goes through `Runtime._advance_and_log` (already used by every gate outcome), so it is logged and recorded like any other bounce.

**Consequence:** Every setback is visible for comparison; no reason is hidden.

### 2. Reason normalisation as data (L2)

`loops.normalise(reason)` applies a table of regex substitutions (`NORMALISE`) to lowercase the reason and strip timestamps, URLs, host:port pairs, paths, story/event ids, SHAs, and counts. A `Setback.key` is `f"{step}>{to_step} {normalise(reason)}"`, set in `__post_init__` and always recomputed on load.

Example: `"nothing is listening at 127.0.0.1:8799 (connection refused)"` normalises to `"nothing is listening at <host> (connection refused)"`.

**Consequence:** Different runs with the same issue (different times, ports, paths) produce the same key. Adding a new pattern to strip requires one table row, not code changes (AC4).

### 3. Streak extension logic (L3)

After each setback, `loops.extend(streak, setback)` appends when the last streak's key equals the new setback's key, else restarts the streak at `[setback]`. A pass, dispute, hand-over, or `continue_story` leave the streak unchanged. A Manager ruling or fault clears it.

**Consequence:** A different reason resets the count; a repeated pass-through a step still counts as ping-pong (not resetting the count).

### 4. Repeat rule and escalation (L4, L5)

`Pipeline.repeat: int` (default 2, minimum 2). Before the story moves, `Pipeline.screen(story, setback)` returns `Outcome(ESCALATE, reason, step, author)` when `len(streak_with_same_key) + 1 >= repeat`, else `None`.

`Pipeline.advance` on `ESCALATE`: `status = NEEDS_MANAGER`, `repeated = outcome.reason`, step and rounds unchanged, no move. The story is not sent round again; it is logged as an `escalation` event instead of a `gate` event. The setback is added to the streak with this event's id.

**Consequence:** The second setback in a row with the same key escalates; no looping. Escalating adds no round to anyone.

### 5. Manager escalation and repeated-setback context (L7)

The router runs `manager` **on that story** with `REPEAT_HEADING` and a `repeated_setback` entry in the runner context: `{"story", "reason" (verbatim last output), "key", "count", "author", "history" (earlier streak setbacks as dicts: step, to_step, role, verdict, author, reason, event), "events"}`. Events are all gate, step-end, test-dispute, escalation, ruling, or fault events from the first setback on.

**Consequence:** The Manager sees the pattern (how many times, which roles, which steps, the reasons) and the evidence (logs).

### 6. Fault decision and application (L8)

A Manager handoff may carry `"fault": "<role name>" | "runner"`. The fault is required on a repeated story; missing is malformed. Its effect goes by `Pipeline.fault_kind(fault)`:

- `"runner"` → `RUNNER`: status `BLOCKED`, step kept. Posts `RUNNER_FAULT_NOTE` to outbox (for the liaison to relay).
- A role with an enabled step → `PIPELINE`: step = that role's step, status `ACTIVE`.
- Any other known role → `OFF_PIPELINE`: status `ACTIVE`, step kept.

`apply_fault` clears `rounds`, `disputes`, `dispute`, `streak`, `run`, `repeated`, and `escalated_by`, resetting the loop's state so the story moves forward without hanging.

**Consequence:** A runner fault is flagged and held for human decision. A role fault sends the story to that role to fix it. An off-pipeline role is briefed and continues.

### 7. Fault refusals and events (L9, L11)

Missing `fault` or unknown name gives `FAULT_MISSING` or `FAULT_UNKNOWN`. The story stays `needs_manager` with `repeated`. The report carries `"fault": {"applied": false, "why": …}`, and any `ruling` is **not** applied. An applied fault adds `"fault": {"fault", "kind", "applied": true, "reason", "now_at"}` and emits a `fault` event with `{fault, kind, reason, now_at}`.

**Consequence:** Bad faults are refused cleanly; good ones are logged.

### 8. Fault and ruling together (L10)

When a fault is applied and the handoff also has `ruling`, the ruling is applied after the fault, so the ruling's move wins (`rescope`, `revise_design`, `escalate`; `upgrade_model` keeps the step). Both are in the report. A story without `repeated` ignores `fault`.

**Consequence:** The Manager can reset the loop and direct the story in one decision.

### 9. Hand-overs (L13)

Three new rows after `ruling_not_applied`:
- `runner_fault` (applied, kind `runner`): PO tells human, opens a story for the runner fix, runs manager again with a ruling once fixed.
- `off_pipeline_fault` (applied, kind `off_pipeline`): PO runs the fault role, then `continue_story`.
- `fault_not_applied` (applied false): PO runs manager again.

The `round_cap` row no longer matches a gate whose verdict is `escalate`. An escalation itself is **not** a hand-over; the runner goes straight to the Manager.

**Consequence:** The PO has clear actions for each fault type.

### 10. Refusal while escalated (L14)

`dispatch_refusal` checks `_repeat_refusal` before `_status_refusal`. A story with `repeated` refuses every gated role with `"story {id} repeated a setback ({key}); the manager rules on it first"`.

**Consequence:** Roles cannot work on a story that is looping; the Manager gets first shot.

### 11. Brief update (L15)

`router._history_lines` reads a `SENT_BACK_LINES` table by verdict. For `escalate`, it returns `"- The same setback repeated, so the manager ruled on it: {reason}"`. The Manager tells the fault role what to fix through `followups` (an existing mechanism).

**Consequence:** The next role knows the loop was broken by the Manager.

### 12. State and dashboard (L16, L17)

`StoryState.streak: list[Setback]` and `repeated: str | None` are saved in `state.json`. The snapshot gains `"repeated": story.repeated`. The board shows `⚑ needs manager · repeat` and the repeated reason (max 140 chars, full reason in title). The flow timeline shows `escalation` and `fault` events.

**Consequence:** Escalated stories are visible and persist across sessions.

### 13. Backstop: back-and-forth escalation (AC4b, B1–B9)

A backstop rule catches a story bouncing between the same two steps (default 4 times), regardless of reason. A counted bounce crosses between two steps; a hold or in-place bounce does not count. A pass of the upper step resets the run. With the default, the fourth bounce in a row escalates with `rule: BACKSTOP`, listing every reason. The repeat rule wins if both fire on the same setback.

**Consequence:** A role reworded the same issue multiple times (e.g., e451/e457) and is still caught.

## Consistency rules

- **Precedence (L4, B5):** Repeat rule (same-key) fires first; backstop (back-and-forth) fires second. An escalation rule wins over a move.
- **Never trusted:** A stored setback's key is recomputed on load; old keys are not trusted.
- **Streak vs. run (B5):** Every setback extends both the streak (for repeat detection) and the run (for backstop detection). A pass resets the run but not the streak.
- **Fault clears both (L8, B3):** `Pipeline._clear` empties `streak`, `run`, `repeated`, and `escalated_by`.
- **Manager context (L7):** `repeated_setback` is built from the trail (streak for repeat, run for backstop), so the Manager sees the right history.

## Tradeoffs

- **Over-merging:** Normalisation can over-merge (e.g., two different `/`-paths in one reason). An over-merge costs at most one Manager step; the fault ruling clears the streak.
- **Prose variance:** A role that rewords the same complaint gives two keys (e.g., "nothing is listening" vs. "Dashboard is not running"). The backstop catches them; the round cap applies to both.
- **Trust the claim:** The normalisation table is code; adding a new pattern requires an ADR to make sure it's intentional. The PO is handed the story if the count is wrong.
- **Zero cost on escalation:** Escalating and ruling consume no rounds, so stories spend no budget on loops. The budget covers the work that fixes it, not the loop itself.

## References

- Story: `.team/stories/s27.md`
- Design: `agile-team/docs/design/s27.md` (rules L1–L18 + B1–B9, modules, test checklist, reason strings, normalisation table)
- Review: `.team/reviews/s27.md` (round 0: e2e trial confirms AC1–AC5)
- Related: ADR-0009 (routing in code), ADR-0012 (gate clearing), s11 (disputes), s19 (hand-overs), s26 (liveness trial)
