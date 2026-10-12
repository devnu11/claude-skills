# ADR-0032: Live spend meter, heartbeat, and health rules

**Decision date:** 2026-10-12  
**Status:** Accepted  
**Story:** s44  

## Context

The human watched a run for hours without seeing tokens being spent, then discovered it had halted 23 minutes earlier. Another step was killed silently. The dashboard showed no spend rate, no heartbeat, no alert. The PO had no visibility into whether the team was working.

The runner already measured turns in the SDK stream. The challenge was to make that visible, trustworthy, and alarming when something goes wrong.

## Decision

The runner itself measures every turn from the model stream, keeps a heartbeat file fresh, and judges health from one rule table. Three new modules (`live.py`, `health.py`) and updates to dispatch, po_tools, and the dashboard enable the human to see at a glance whether the team is working.

### D1: Turns go to `turns.jsonl`, not `events.jsonl`

A step makes tens to hundreds of turns. The event log stays one line per step, gate, and ruling (sparse, auditable). Turns are written to `turns.jsonl` so the snapshot can include a 10-minute tail without bloating the log. This keeps the event log small and fast to read.

### D2: Heartbeat written by daemon thread, not asyncio task

The runner's gate and check commands block the event loop for up to `command_timeout_s` (default 300s). An asyncio task would stop beating during a long test suite and falsely turn the run red. A daemon thread keeps beating regardless of what the event loop does—through runner-side work and through tools. It stops only when the process dies (kill, crash), which is the signal we need to catch.

### D3: One health judgement, in Python

A single rule table (`health.RULES`, R2–R11) judges health from the heartbeat and run status. The verdict (level + reason) lives in the snapshot. The server pushes a new snapshot when the verdict changes, even if no file changed (e.g., a killed runner writes nothing but the heartbeat goes stale). This is the only source of truth for health; the UI only ticks ages between pushes.

### D4: A halted run is red; a graceful stop is neutral (PO ruling)

When a step ends with `stop --now`, a limit, a crash, a budget halt, or a killed process, the human wants to see red "from across the room". But when the human asks the runner to stop gracefully with `agile-team stop`, that is the human's own request, not an error. So a graceful stop is **idle**, not red: `● stopped` with no alert, no notification, no watch trigger.

The runner records which halts are which via `state.halt_kind`. A graceful stop leaves it `None`. `stop --now`, limits, and crashes set it. Health judges `resting` (status is `stopped` and `halt_kind is None`) and skips red rules when resting, leaving only the neutral `idle` verdict.

### D5: Box totals come from the ledger only

Live tokens and estimated dollars show on the active step's flow-chart box and pill, but they are never added to the box totals. Totals always match the ledger exactly. This keeps the UI honest: what you see in the Tokens tab (ledger-only) matches the flow-chart boxes.

### D6: Live dollars are an estimate

Each turn is priced using rate tables (`live.RATES`, $/Mtok by model family). A provider with `billing = "free"` estimates 0; an unknown family estimates `null` (shown `—`). These are live approximations. The ledger's `ResultMessage` cost stays the truth.

### D7: The PO's queries are metered too

When the PO runs a `run_role` tool call, the dispatcher opens a meter for the PO just as it opens one for a role step. Meters nest: the role step's meter is inside the PO's. The heartbeat shows the innermost open meter. This way the live pill shows who is actually thinking, even when the PO is asking the runner to work.

### D8: The quiet clock restarts when control comes back to the model

"Quiet" measures how long the model has had the floor without answering (no turn, no tool closing, no inner step ending). It does not measure time since the last turn. A meter whose model is waiting on a tool or an inner step is not quiet. Each reading keeps `quiet_since`, which is moved to `now` when:
- A turn is made (model answered)
- A tool closes (model regained the floor)
- An inner meter closes (model had delegated)
- A chore ends (runner was doing something)

Without this rule, the PO meter would go red for a moment after every role step longer than 10 minutes, which is not useful.

### D9: Waiting for the human is a chore

`po_tools.wait_for_answers` runs inside a chore context. Chores silence the quiet rules, so the PO's polling for answers does not turn red. But `run_role` is not a chore: a chore would hide a hung inner step. The rules still apply: a dead runner is still red, a heartbeat older than 90s is still red.

## Consequences

### Snapshot and server
- New sections in the snapshot: `turns`, `heartbeat`, `health`.
- Server pushes on verdict change even when files don't change.
- Dashboard URLs printed on two lines (localhost, LAN).

### UI and alerts
- New smart pill: health colour, tokens per minute, sparkline, turn age, with hover details.
- Flow-chart boxes show per-role live stats and are coloured by health.
- Tab title gets `⚠ ` on red; desktop notification on change (secure context).
- Graceful stop shows neutral `● stopped` with no alert.

### Modules and wiring
- `live.py`: Meter, Pulse, Reading, Turn, Heartbeat file format, estimate pricing.
- `health.py`: Rules table, judge function, age formatting, model note.
- `dispatch.py`: Step meter lifecycle, pulse thread start/end, interrupted step emission.
- `po_tools.py`: PO meter open/close, wait chore context.
- `boundary_runner.py` and `recovery.py`: Chore contexts for boundary and kill recovery.

### Config
- `[health]` section with thresholds: `beat_s`, `stale_s`, `amber_tool_s`, `amber_quiet_s`, `red_quiet_s`.
- Defaults: 20s heartbeat, 90s stale, 3min amber with tool, 5min amber without tool, 10min red.

### Testing
- Unit tests: every rule row, nested meters, quiet clock, chores, interrupted steps, config parsing.
- UI tests (node): pill text and details, flow stats, health colour, scope toggle, alerts.
- E2E tests: fake step process silence, SIGKILL, graceful stop, scope ledger match (open).
- Manual: pill and flow during real step, `stop --now` turns red, graceful `stop` is neutral.

### Not changed
- Event log stays sparse (one line per step, gate, ruling).
- Ledger cost and tokens are never live estimates.
- No new runtime dependencies (stdlib, bundled SDK only).
