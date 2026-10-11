# ADR-0020: Unattended wake time and reason sources

**Date:** 2026-10-11 (s37 done)  
**Status:** Accepted  
**Relates to:** ADR-0013 (liveness), ADR-0007 (clean halt), s26 (service lifecycle), s8 (halt handling)

## Context

**Story s37:** Two bugs in the unattended service after a resume or offline wait:

1. **Stale `next_wake` (AC2):** After a resume and an offline wait, `status` showed the old reset time. `_mark_waiting` set `next_wake`, and only `_finish` cleared it. `_cycle` marks the job `running` and `_reconnect` marks it `waiting`, and neither cleared it.

2. **Reset read from PO text (AC3, AC4):** For exit 75, the supervisor looked for "resets" patterns in the last 50 lines of output. When agile-team's halt line was followed by the PO's flushed stdout saying "resets the count", the PO's text matched last, not agile-team's halt line. No readable time was found, so the supervisor used a 5-hour fallback instead of the stated 9:00 PM reset, and the team sat idle for 1.5 hours.

Both bugs involved incomplete state clearing and reading from the wrong text source. The fix centralizes state clearing and establishes a priority order for reset sources.

## Decision

### 1. Single place to clear wake state (N1, S1)

`JobState.mark(status, reason="")` now sets `next_wake = None` and `wake_on = None` after storing the status and reason. Every status change that is not a timed wait calls `mark` (running, waiting, done, blocked, failed, stopped, etc.), which clears both wake fields.

A timed wait (limit or rate-limit wait) calls `mark` first, then sets both `next_wake` and `wake_on` to define when the wait ends. This is the single place these fields are written; every other path clears them.

**Consequence:** After a resume (which calls `_cycle` → `mark(RUNNING)`), `next_wake` is `None`. After an offline wait (which calls `_reconnect` → `mark(WAITING, reason)` → sets `wake_on = NETWORK`), `next_wake` is `None` and `wake_on = NETWORK`. No stale values persist.

### 2. Wake metadata (WakeOn enum and Wake dataclass)

`WakeOn` is a `StrEnum` with four values:
- `RESET`: the stated reset time plus grace period (usually 5 minutes)
- `FALLBACK`: no readable reset time was found; the job's fallback wait
- `BACKOFF`: a rate-limit backoff (retry wait)
- `NETWORK`: offline wait; no wake time

`Wake` is a frozen dataclass with `at: float` (epoch seconds) and `on: WakeOn`. It pairs the wake time with the reason it was chosen.

**Consequence:** Every wake decision is explicit and auditable. Status and list commands report why the team is waiting.

### 3. Reason sources in priority order (R1)

For a command that exits 75 (limit), the reason comes from the first of these sources that gives one (in order; later sources are not read if an earlier one succeeds):

1. **Halt line:** The last line in the tail that matches `^agile-team start: (?P<reason>[^\n]+?); run `agile-team start --resume`` (multiline regex). If present, this source wins and the PO's output is never read.
2. **Status file:** `<spec.cwd>/.team/run/state.json`, when it parses as a JSON object with `status == "blocked"` and `status_reason` is a non-empty string. Covers the case where agile-team's stdout is block-buffered and flushed after the halt line to stderr.
3. **Free text:** `find_reason(COMMAND_LIMIT_PATTERNS, text)` as before, but with tightened `RESET_NOTE` pattern (R2 below).
4. **Default:** `DEFAULT_LIMIT_REASON` if no source matched.

**Consequence:** The halt line (written by agile-team to stderr) is the authoritative source; PO text is read only as a fallback. The status file (also written by the same halt) provides a fallback for cases where stdout buffering breaks the halt line match.

### 4. Readable reset time required (R2, R3)

`RESET_NOTE` now matches only `resets ` followed by a time that `RESET_TIME` can parse: an optional date (`Mon D,` or `at`), then `H[:MM]am|pm`, then optional `(Zone)`.

Patterns like `resets the count`, `resets soon`, `resets tomorrow` do no longer match. A reason with no readable time is not treated as a stated reset.

The time grammar is split from `RESET_TIME` into a shared `RESET_CLOCK` fragment so both patterns are built from one definition (DRY).

**Consequence:** A reason without a parseable time falls back to `wake_on: FALLBACK` (now + default wait), and status says the team is waiting for fallback, not a reset. Users see that the team is not waiting for a specific stated time.

### 5. Offline wait has no wake time (N2, S1)

An offline wait (marked by `_reconnect` calling `_mark_offline`) sets:
- `status = WAITING`
- `next_wake = None` (via `mark`, N1)
- `wake_on = NETWORK` (set after `mark`)

The event includes `"until": null` and `"on": "network"`, telling the human the team is waiting for the network, not a time.

After the network returns and the runner completes, `_cycle` marks the job `running` again, which clears both wake fields (N1).

**Consequence:** Offline waits and their resumes are unambiguous: no wake time is reported, and the status change to running clears any old wake state.

### 6. Wake state in the job snapshot (S1)

Status, list, and wait commands report `"wake_on"` (one of `reset`, `fallback`, `backoff`, `network`, or null) right after `"next_wake"` in the response. The wait event carries `"on"` next to `"until"`.

Legacy state.json files with no `wake_on` key load the field as `None` (L1).

**Consequence:** Every status report is self-describing. The human can read why the team is waiting and when (or that it's waiting for a time-less event like the network).

## Consistency rules

- **Always via mark:** `next_wake` and `wake_on` are cleared by `mark`, set by wait methods, never by any other code path.
- **Halt line wins:** When present, the halt line's reason is used as-is; PO text is never read (R1).
- **Status file covers buffering:** If the halt line does not match (stdout flushed after halt to stderr), the status file written by the same halt provides the reason.
- **Time required for reset:** `RESET_NOTE` requires a readable time; otherwise, reason falls back to `FALLBACK` (R3).
- **Offline is not timed:** An offline wait reports `wake_on: NETWORK` and `next_wake: null`; no time is guessed.
- **Clean resume:** After a resume, `_cycle` marks running, which clears wake fields. After an offline wait's online event, the same rule applies.

## Tradeoffs

- **Halt line not anchored at start of buffer:** The regex is anchored at `^`, so a partial line from block-buffered stdout just before it breaks the match. R1's second source (status file, also written by the halt) covers this case, but it requires the status file to be readable and JSON. Tests verify both sources work.
- **Fallback wait is explicit, not silent:** A reason with no readable time now reports `wake_on: FALLBACK` instead of silently using the fallback. This is user-visible but necessary to avoid the 1.5-hour idle bug.
- **No time estimation:** The supervisor never tries to parse free text without a time (e.g., `resets after s39` or `resets when merged`). Users must give a time for it to be trusted.

## References

- Story: `.team/stories/s37.md`
- Design: `agile-team/docs/design/s37.md` (rules N1–N2, R1–R3, S1, L1; modules and test checklist)
- Review: `.team/reviews/s37.md` (round 1, no defects, shipped)
- Related: ADR-0013 (service liveness), ADR-0007 (halt handling), s26 (service lifecycle)
