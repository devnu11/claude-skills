# ADR-0037: Dashboard graceful vs forced stop display

**Decision date:** 2026-10-12  
**Status:** Accepted  
**Story:** s74  

## Context

Story s44 introduced the health meter and established (D4) that graceful stops (user-requested `agile-team stop`) are neutral (`idle`) while forced halts are red. The implementation left two visual defects on the dashboard:

1. **N1 (regression):** Fallback step pill text lost the space after `▶` when no heartbeat is present.
2. **Resting pill (yellow):** The run-status pill for `stopped` status showed yellow warning tone instead of plain, even for graceful stops.

These defects undermined the design: users saw warnings and could not tell graceful stops from forced halts at a glance.

## Decision

The dashboard now visually distinguishes graceful and forced stops through two refactored components:

### S1: Run-status pill tone is neutral for `stopped`

The run-status pill (`● <status>`) shows the run's status alone, without health interpretation. Its tone (`STATUS_TONE[status]`) is static per status:

- `stopped` → tone `""` (plain, no color)
- `blocked`, `failed`, `interrupted` → tone `"serious"` or `"critical"` (red)
- `active`, `idle` → tone `""` (plain)

A graceful stop leaves `halt_kind = None`, so the run stays at health level `idle` (from ADR-0032 D4). The smart pill (which shows health) is not rendered when the run is at rest (status `stopped`, no open step, health `idle`). So only the plain run-status pill appears, with no alert.

A forced halt sets `halt_kind` (e.g., `"sigterm"` for `stop --now`), health jumps to `red`, and the smart pill appears showing `● <reason>` in red.

### S2: Fallback text has the required space

The `pillText` function's fallback branch (when no live step, heartbeat is `null`, but a step is open) now returns:
```
▶ <role> on <story> · <ago>
```
with exactly one space after the arrow. This matches the design intention: a waiting step is shown in a human-readable form while we wait for the step to update.

### S3: Pure `statusPills` function for testability

The status row's pill construction is extracted into a pure function `statusPills(view, now)`, which returns an array of HTML strings (connection, status, smart, questions, manager due, mock). The function is called by `renderStatusRow`, which writes the result and renders details. This separation allows unit tests to verify each pill independently without DOM side effects.

## Consequences

### Visual semantics
- **Graceful stop:** Plain `● stopped` pill (no color, no alert, no notification). The human sees it is idle on request, not an error.
- **Forced halt (stop --now, limit, crash, dead runner):** Plain run-status pill + red smart pill with the reason. The human sees red from across the room and clicks for details.
- **Resting with no halt:** Status `stopped`, health `idle`, no open step → only run-status pill (plain), no smart pill (design P2/R15).

### Tests
- **N1:** Fallback text pinned with exact string and space.
- **S1:** Resting stopped pill is plain (no `tone-warning`, no `h-amber`/`h-red`, no `⚠`).
- **S2:** Forced halts (`stop --now`, `blocked`, `failed`, `interrupted`) show red on smart pill; their run-status pills may be plain (stopped) or red (blocked/failed).

### Code changes (minimal)
- `STATUS_TONE.stopped: "warning"` → `STATUS_TONE.stopped: ""` (one line)
- `pillText` fallback: `▶${who}` → `▶ ${who}` (one space added)
- New function `statusPills(view, now)` extracted from `renderStatusRow` body (refactoring for testability, no behaviour change)
- `reference/protocol.md` § Health updated to describe the pill tones and health levels

### No changes
- CSS, smart pill logic, snapshot contract, Python health rules, `applyAlert`, or other dashboard functions
- Halted status meanings or health judgement rules
- Config thresholds or ledger tracking

## Rationale

This decision refines how ADR-0032's D4 (graceful ≠ forced) is displayed. The run-status pill is a status indicator only; health colour belongs to the smart pill (which is hidden at rest). By making `stopped` plain and rendering the smart pill only when health is not idle, we ensure:

1. Graceful stops look calm (no warning, no red).
2. Forced halts are visible at a glance (red smart pill).
3. The human can tell them apart instantly.

The fallback text fix restores the design's clarity for waiting steps. The `statusPills` extraction is a structural improvement that makes the visual contract testable in isolation.
