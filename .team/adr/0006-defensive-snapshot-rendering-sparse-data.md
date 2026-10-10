# ADR-0006: Defensive snapshot rendering for sparse and malformed data

**Date:** 2026-10-10  
**Status:** Accepted  
**Affected:** Dashboard rendering robustness (s5)

## Context

The snapshot schema defines expected fields, but real-world data can be incomplete, malformed, or empty. Examples:
- A `sprint-start` event arrives with missing `data.sprint`, `data.goal`, or empty `data.stories`
- A `step-end` event has no `data.status`
- A requirement's `covers` list is missing
- A story's `acceptance` list is empty

The dashboard must render gracefully despite incomplete data, so a single bad event does not crash the entire UI.

## Decision

Apply **defensive rendering** at three levels:

1. **Normalization:** `normalize(snap)` fills in defaults for missing list and object fields
2. **Per-row error handling:** Each timeline row, card, and table row is wrapped in `try/catch`; if it throws, that row is skipped and others render
3. **Graceful degradation:** Missing optional fields are either omitted from display or shown with a fallback value

**Key choices:**
- **Normalize on load:** The snapshot arrives from the server (well-formed by design), but test fixtures and older data may be sparse. `normalize()` adds defaults before rendering
- **Per-handler safety:** The timeline's `timelineRow()` catches errors per row; `safely()` wrapper around each render call logs but does not crash
- **Sparse event support:** Events may omit `data` or have incomplete `data`:
  - `sprint-start` with missing `sprint`: show "sprint" (no number)
  - `sprint-start` with empty `stories`: omit from display
  - `step-end` with no `status`: show "done" (the default success state)
- **Empty states:** When a list is empty (requirements, questions, messages), show a single `<p class="empty">` instead of an empty table

## Consequences

**Safe:**
- A bad event in `events.jsonl` loses only its own row; other events still render
- Mermaid's strict mode prevents label injection even if a label is rendered unescaped
- A missing snapshot field defaults to an empty list, not undefined

**Predictable:**
- Users see the UI even if some data is incomplete
- Error messages in the status row alert the viewer ("render error: …") without stopping the stream
- Timeline always shows at least the header, even with all-empty events

**Trade-offs:**
- Defensive checks add boilerplate (every renderer wrapped in `safely()`), but keep each renderer simple
- A test fixture with `data: {}` will lose some rows; the runner always writes `data`, so this is only a test artifact
- No audit trail of dropped rows (silent skip, except status pill for critical errors)

## Implementation

**U4 (normalization):**
- `normalize(snap)` fills each key from `D1` keys list:
  - `pipeline`, `roles`, `stories`, `requirements`, `events`, `ledger`, `messages`, `answers` default to `[]`
  - `run` defaults to `{status: "idle", sprint: 0, task: "", budget_usd: 0, manager_every_pct: 25, round_cap: 3, manager_due: []}`
  - `story.acceptance`, `requirement.covers`, `requirement.history` each default to `[]`
- Nested missing fields:
  - `story.delivery` → `""`
  - `step-end.data.commit`, `step-end.data.tokens`, `step-end.data.cost_usd` → omitted (only rendered if non-empty)
  - `requirement.history[].sha` → omitted (only rendered if non-empty, since it is `""` until s2)

**U4a (sparse events):**
- `sprint-start` data fields:
  - `data.sprint`: check `!= null` (so `0` still renders). Fall back to omit number.
  - `data.goal`: render only if present and non-empty
  - `data.stories`: render only if present and non-empty. `replayStories()` uses `sprint?.data?.stories ?? []`
- `step-end.data.status`: if missing, the default is `"done"` (shown in the pill)
- `message.data` and `answer.data`: missing data loses the whole row (caught by `timelineRow()` catch)

**U3 (per-row error handling):**
- `renderFlowTab(view)`: `safely(fn, "flow")` catches any throw and returns `<p class="pill critical">render error: …</p>` in the status row
- `timelineRow(event)`: wrapped in `try/catch` at the row level. A bad event logs to console but does not crash the timeline.
- `renderBoard()`, `renderTokens()`, `renderQuestions()`, `renderRequirements()`: each wrapped in `safely()`
- `safely(fn, view)` = `try { return fn() } catch (e) { if (view) addPill("render error: "+e.message); }`

**Empty-state UI (U5):**
- Requirements tab: show a single card "No requirements yet. The Architect writes them as `<docs>/requirements/REQ-NNN.md`." when `view.requirements.length === 0`
  - Hide tiles, matrix, gap pills
  - Tab badge shows 0
  - Story cards hide "AC x/y traced"
- Questions tab: show "No open questions yet." when both open and raised lists are empty
- Board: show "No stories yet." when `view.stories.length === 0` and backlog is empty
- Token chart: show "No ledger entries yet." when `view.ledger.length === 0`

**Testing implications:**
- Test fixtures may include `data: {}` events (e.g., `test_dashboard_e2e.py:41`). These are skipped with no error.
- The runner always writes complete `data` objects, so production runs never hit sparse paths
- A test that asserts "this event renders correctly" must check the row exists, not just that the page loads
