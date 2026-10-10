# ADR-0007: Data-driven halt handling for clean stops

**Date:** 2026-10-10  
**Status:** Accepted  
**Affected:** Clean stop on usage limit, crash, or SIGTERM (s8)

## Context

The runner can encounter three types of fatal events:
1. SDK usage/session limit (temporary, resumable)
2. Unexpected exception (internal error, needs debugging)
3. SIGTERM signal (human requested stop)

Previously, when the SDK raised a `ResultError` for a limit, the process would exit with a traceback and no indication of what happened or when to resume. The human operator had to dig through logs to understand the situation.

## Decision

Model halt handling as data, not branching:

1. **HALTS table** maps each `HaltKind` (limit, crash, sigterm) to a `HaltRule` containing:
   - Run status to save (`blocked`, `failed`, or `stopped`)
   - Relay note kind for the liaison
   - Exit code (75 for EX_TEMPFAIL limits, 70 for EX_SOFTWARE crashes, 143 for SIGTERM)
   - Advice text with recovery instructions

2. **LIMIT_PATTERNS table** detects limit text via regex matching:
   - First matching pattern's template extracts the kind (session, weekly, usage)
   - Reset time is copied from the error message, not computed
   - Pattern matching is case-insensitive; reset text ends at newline or semicolon
   - No code outside the tables makes assumptions about limit phrasing

3. **Exception classification** uses a detector chain:
   - `limit_halt()`: checks LIMIT_PATTERNS for any limit text
   - `sigterm_halt()`: checks for `CancelledError` (SIGTERM signal)
   - `crash_halt()`: fallback for any other exception
   - First non-None result is the classified halt

4. **First halt wins** in a single process:
   - `halt_run()` records the first halt found
   - Later calls re-assert it (same status, note posted only once)
   - This simplifies logic: no tracking which halt is "most important"

5. **No settle after halt** (H15):
   - When `runtime.halted_by` is set, the PO's `_settle()` is skipped
   - Partial edits from the halted step and PO remain uncommitted
   - The human can inspect what was in progress

## Consequences

- **Clear recovery path:** Status reason includes reset time. `start --resume` tells the human exactly when to retry.
- **Consistent behavior:** All halt kinds flow through the same code path. Status, reason, note and exit code are always consistent.
- **Debuggable:** Full traceback goes to `crash.log`, stderr shows one line, no spam.
- **Auditable:** The HALTS and LIMIT_PATTERNS tables are the truth; code follows them.
- **Resumable state:** Partial edits are visible; PO session is saved so `start --resume` continues where it left off.
- **Trade-off:** Resume does not auto-sleep. The human must manually run after the reset time (as decided in m3).

## Implementation

Module `halt.py` provides:
- `HALTS` table (kind → status, note_kind, exit_code, advice)
- `LIMIT_PATTERNS` table (regex, template) with rows for session, weekly, and usage limits
- `Halt` dataclass with `kind`, `reason`, and `rule` property
- `classify(exc)` returns the detected halt
- `log_traceback()` appends to `.team/run/crash.log`

Module changes:
- `dispatch.Runtime.halt_run()`: saves halt, posts note, re-asserts on later calls
- `dispatch._step_failed()`: catches role-step exceptions, classifies and halts
- `cli._halt_exit()`: catches top-level exceptions in the main event loop
- `po_tools.PoRun._settle()`: skips settle when `runtime.halted_by` is set
- `state.RunState.mark()`: sets status and reason atomically

Documentation:
- `reference/protocol.md`: Run statuses (blocked, failed, stopped), exit codes, crash.log location
- `SKILL.md`: Step 9 tells the liaison to check `status`, the outbox note, and `crash.log`
- Built-in `roles/product-owner.md`: Step 5 tells the PO not to make more tool calls on `halted`
