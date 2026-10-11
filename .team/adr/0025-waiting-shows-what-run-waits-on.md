# ADR-0025: Show waiting status—what the run waits on

**Decision:** When the router waits on open questions with no PO session running, show in `status_reason` what stories and open questions it waits on. Include this context in halt notes when the run halts while waiting.

**Date:** 2026-10-11

## Context

Sprint 16 logs revealed a two-hour idle in the run after the PO posted a question. Analysis (s47 design) found:

1. **The wake logic works:** The router woke on the answer within 4 seconds (one poll cycle), as designed. The answer was successfully handed over to the PO.

2. **Visibility gap:** While waiting, the run's `status_reason` was `null` and `status` was `running`. The human saw no indication of what the run was waiting on, so they restarted the runner thinking it was hung.

3. **Half the problem solved:** When a run halts (e.g., `stop --now`), the halt note goes to the human but does not mention open questions, so the human knows the run is waiting but not what to answer.

The solution adds two visibility points: `status_reason` while waiting (W3), and halt notes that name the waiting context (W5).

## Decision

### Rules for waiting status (W1–W6)

- **W1 Wake (unchanged):** Router polls every 5 seconds (`POLL_S`) and reads the inbox first. When a new answer arrives, the wait ends with a `human_message` hand-over to the PO. This holds whether the wait started after a PO turn or on a `start --resume`.

- **W2 Wait lines:** `Relay.waits()` returns one line per story an open question names:
  ```
  "s40 waits on m42, m43"
  "s41 waits on m43"
  ```
  Followed by one line for unnamed questions:
  ```
  "the run waits on m44"
  ```
  Stories come in outbox order (first seen). Ids come in outbox order with no duplicates. Questions that name no story come last. With no open question the list is empty.

- **W3 Waiting reason:** While the router waits (`_tick` reaches `_wait`), `status_reason` is set to:
  ```
  "waiting on answers: s40 waits on m42; the run waits on m43"
  ```
  `status` does not change; only the reason is set. State is saved only when the reason changes, not on every poll.

- **W4 Reason cleared on end:** When the wait ends (`_deliver` with news or `_step` with a role step), a `status_reason` starting with `"waiting on answers: "` is cleared (status unchanged) and saved. Other reasons are left alone. A halt replaces any reason. Graceful stop ends as `idle` and clears the reason.

- **W5 Halt note suffix:** When the run halts while a question is open, the posted note becomes:
  ```
  <original halt note>; waiting on answers: s40 waits on m42; the run waits on m43
  ```
  With no open question the note is unchanged. The stored `status_reason` on a halt is the halt reason alone (unchanged from current practice). The stderr line does not change.

- **W6 Stall message unchanged:** A `stalled` pass cannot coincide with an open question, because the router waits instead (`_idle`). The stall lines do not change. For a run that waits on the human, W3 is its stall message.

### Implementation

**New constants and methods in `relay.py`:**
```python
WAIT_LINE = "{story} waits on {ids}"
RUN_WAIT_LINE = "the run waits on {ids}"
WAITING_HEAD = "waiting on answers: "

def waits(self) -> list[str]:
    """One line per story an open question names, then one for questions naming none (W2)."""

def waiting(self) -> str:
    """WAITING_HEAD + the waits joined by "; ", or "" when no question is open (W3, W5)."""
```

**In `router.py`:**
- Rename `_wait()` to show status while sleeping: set reason via `_show_wait()`, then sleep.
- New `_show_wait()`: sets `status_reason` to `relay.waiting()`. If it changed, save state (W3).
- New `_clear_wait()`: clears a reason starting with `WAITING_HEAD`, returns whether it did (W4).
- New `_end_wait()`: calls `_clear_wait()`, saves if it cleared anything. First call in `_step` (W4).
- Modified `_deliver()`: calls `_clear_wait()` first; existing save persists it (avoiding double save).
- Import: `from .relay import WAITING_HEAD, Answer`.

**In `dispatch.py`:**
- Modified `Runtime.halt_run`: note becomes `halt_note(self.halted_by, saved) + _waits_suffix(self.relay)` (W5).
- New module function:
  ```python
  def _waits_suffix(relay: Relay) -> str:
      """"; " + the run's waiting reason when a question is open, else "" (W5)."""
  ```

**Docs update (in same story):**
- `reference/protocol.md`: `status_reason` while waiting (W3/W4), halt-note suffix (W5), wait bullet in "Routing" (W1–W3).
- `SKILL.md` step 6: when a run waits, `status_reason` names what it waits on.
- `docs/customer/routing.md`: "The runner waits for your answers" section.

**No changes to:**
- `po_tools.wait_for_answers`, `Router._news`/`_idle`/`_stall_lines`, `halt.Halt.message`, `cli.status_report` (already shows `status_reason`), snapshot contract, unattended.

## Consequences

**Positive:**
- Human can see what the run is waiting on without running `agile-team status` or reading logs.
- Halt notes show waiting context, so if a user stops the runner while it waits, they know what to answer.
- Waits are transient (poll cycle updates them); saves only on change, not every poll.

**Tradeoffs:**
- `waits()` builds a string on each poll (no caching). This is cheap: one traversal of open questions.
- `_show_wait()` saves state only on change, so two consecutive polls with the same open question save once.
- Halt reason is the halt itself, not the waiting reason (W5). The stderr line and status file hold only the halt reason, unchanged.

**Implementation notes:**
- `Relay.waiting()` and `_waits_suffix()` both call `waits()` but produce different strings; no duplication.
- `_deliver` calls `_clear_wait` (first), then the existing save persists. `_step` calls `_end_wait` (first), which saves if needed. Double save avoided.

## References

- Story: `.team/stories/s47.md`
- Design: `agile-team/docs/design/s47.md`
- Review: `.team/reviews/s47.md`
- ADR-0009: Routing in code (s19)
