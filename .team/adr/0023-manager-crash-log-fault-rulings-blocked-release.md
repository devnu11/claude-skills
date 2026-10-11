# ADR-0023: Manager crash log, fault rulings on any story, and blocked release

**Decision:** Fix the manager step crash in `Runtime.emit()`, add crash logging to `.team/run/crash.log`, extend fault rulings to apply on any story (not just repeated ones), and refuse `continue_story` on blocked stories.

**Date:** 2026-10-11

## Context

Sprint 16 left s29 stuck due to four issues in sequence:

1. The manager step crashed with `TypeError: Runtime.emit() got multiple values for argument 'kind'`. The cause: `Runtime._fault` calls `self.emit(EventKind.FAULT, plan, **report)`, where `report` contains a `kind` key. This clashed with emit's parameter (the error is at HEAD in dispatch.py:335, already fixed by making both parameters positional-only).

2. The crash happened in `settle`, which is outside the try-block that wraps execution, so nothing logged it to `.team/run/crash.log`. The router's error hand-over said "details in crash.log" but there was nothing there.

3. The PO ran the manager on s29, but the story was not `repeated`. The fault path ignored `handoff.fault` without saying so, and the story stayed unchanged.

4. The PO called `continue_story` on s29 (status `blocked`, hold already cleared). Nothing stopped this; the story stayed blocked and the sprint stalled.

The fix requires:
- Catching and logging every role-step exception exactly once (C1).
- Moving settle inside the try so settle crashes are saved like execute crashes (C2).
- Extending fault rulings to any story with a fault or a repeated setback (M1).
- Refusing blocked-story release to prevent silent stalls (B1).

## Decision

### Crash logging (AC3)

1. **Single logging point (C1, C4):** `Runtime.run_role` wraps `_run_step` in try/except. Every exception after `refusal` is passed to `halt.log_traceback()`, which appends it to `.team/run/crash.log` exactly once (one entry per call), then the exception is re-raised unchanged. The router and PO loop's top-level handler do not log (they are outside the scope). A role-step crash never escapes `run_role`'s handler.

2. **Settle inside the try (C2):** The try-block in `_run_planned` now wraps both `_execute` and `settle`. Any settle crash goes through `_step_failed`, which saves the edits (Cause.ERROR) the same way as an execute crash. Settle therefore runs inside the try-except boundary.

3. **Limits still caught locally (C3):** A limit error detected in `_step_failed` is logged there by `halt.log_traceback()`, then turned into a halted report and returned (not re-raised). It does not reach `run_role`'s handler, so it is logged once.

4. **Router and PO stay unchanged (C4):** The router's error hand-over and the PO loop's top-level exception handler do not log. They remain as designed.

### Manager fault rulings (AC5, AC6)

1. **Fault path rule (M1):** The Manager takes the fault path when `handoff.fault` is non-empty OR `story.repeated` is set. Otherwise, only `ruling` is considered (unchanged).

2. **Refusal checks (M2):** In order, first match wins:
   - No story: `a fault needs a story; run the manager on that story`
   - Done story: `story {id} is done; a fault cannot move it`
   - No fault (only when repeated): `FAULT_MISSING`
   - Unknown role: `FAULT_UNKNOWN`

   Checks 1 and 2 reuse `gates.ruling_refusal(story, "a fault")`.

3. **Applied fault state (M3):** On any story (repeated or not), an applied fault:
   - Sets `step` to the named role's step (kept for off-pipeline roles or `runner`).
   - Sets `status` from `FAULT_STATUS` (`runner` → `blocked`, a role → `active`).
   - Clears `hold`, `rounds`, `disputes`, `dispute`, `streak`, `run`, `repeated`, `escalated_by`.

   `note_step` then sets `hold` again from the report, so a runner fault ends up held with `runner_fault`.

4. **Reason before clearing (M4):** The fault's `reason` is read before `apply_fault` clears `repeated`, via `gates.setback_reason(story)` (repeated if set, else last gate's reason, else empty string).

5. **Ruling conditional on fault (M5):** A ruling in the same handoff applies only after the fault. If the fault was not applied, the ruling is reported unapplied with reason `"the fault was not applied, so the ruling was not either"`. Both `fault_not_applied` and `ruling_not_applied` hand over; neither change the story.

6. **Report structure (M6):** Every fault or ruling the Manager names appears in the report as `"fault": {...}` and/or `"ruling": {...}` with `applied: true|false` and `why` when false. The PO gets it in `run_role`'s result; the router gets the hand-over lines (same dict path, `_apply`).

7. **New wording (M7):**
   - `RUNNER_FAULT_NOTE`: `"Runner fault on {story}: no role can fix this setback: {reason}. The manager says: {summary} The story is blocked until the runner is fixed."`
   - `OFF_PIPELINE_FAULT`: `"{story}: the manager puts the setback ({fault_reason}) on {fault}, which owns no pipeline step; brief {fault} yourself, then continue_story"`
   - `FAULT_NOT_APPLIED`: `"{story}: the manager's fault ruling was not applied: {fault_why}; run the manager on {story} again"`

### Releasing blocked stories (AC7)

1. **Block all blocked release (B1):** `continue_story` on a story whose `status` is `blocked` is refused whether or not it has a hold. Nothing changes. Reason: `"story {id} is blocked (escalated to the human); continue_story would leave it stalled. Run the manager on {id} with a ruling or a fault to move it"`.

2. **Other statuses unchanged (B2):** Done and active stories behave as before.

## Implementation

### Modules affected

- **`dispatch.py`** (`Runtime`): `run_role` wraps `_run_step`; `_run_step` lifts body; `_run_planned` wraps settle; `_step_failed` handles non-limit errors; `_rulings` takes fault path; `_rule_after_fault` applies fault then ruling; `_fault_refusal` checks in M2 order; `_fault` reads reason before clear. Module helpers: `_names_fault`, `_unapplied_ruling`.
- **`gates.py`**: `ruling_refusal(story, what)` parametrized (M2); `setback_reason(story)` (M4); `CONTINUE_BLOCKED` and `continue_refusal(story)` (B1); `Pipeline.apply_fault` now clears hold (M3).
- **`po_tools.py`** (`Tools.continue_story`): Apply `continue_refusal` after `_story_for`.
- **`handover.py`**: Update two lines per M7; triggers and predicates unchanged.
- **`roles/manager.md`** and **`roles/product-owner.md`**: Brief updates on fault naming and blocked-story release.
- **`reference/protocol.md`**: Coverage for crash log (C1), faults on any story (M1–M6), and continue_story (B1).

### Signatures (unchanged)

`Runtime.emit(self, kind, plan=None, /, **data)` stays positional-only; this is the root cause fix from HEAD (commit 2dd5b0c).

## Consequences

**Positive:**
- Crashes are now logged, unblocking diagnosis of future exceptions in role steps.
- Fault rulings work on any stuck story, not just those with `repeated` set. This handles escalations from round cap, unit-tester's `escalate`, or runner faults that are not bounces.
- Blocked stories cannot be silently released; the PO must engage the Manager to unblock them.
- All fault/ruling decisions are transparent in the report and hand-over.

**Tradeoffs:**
- `continue_story` on a blocked story now fails. This is intentional: the story cannot move while blocked, so releasing the hold would stall the work. The message directs the PO to the Manager.
- Fault naming is optional but strongly encouraged (M1 allows repeated without a named fault); unknown names are rejected (M2). This leaves `FAULT_MISSING` as a safety valve for escalations that are not repeats.

**Future:**
- s45 does not change the old `_rule_repeat` path; it replaces it with `_rule_after_fault` (which handles both fault and ruling).
- The crash log grows with every crash; a follow-up story may add truncation or rotation.

## References

- Story: `.team/stories/s45.md`
- Design: `agile-team/docs/design/s45.md`
- ADR-0014: Escalate repeated setbacks to the Manager (fault intro)
- ADR-0017: Interrupted steps saved in commits (settle crash → edits saved)
- ADR-0007: Clean halt on limits, crashes, SIGTERM (logging strategy)
