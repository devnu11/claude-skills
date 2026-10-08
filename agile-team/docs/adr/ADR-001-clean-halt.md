# ADR-001: The runner halts cleanly on a usage limit, a crash or SIGTERM

Status: accepted (s8). Date: 2026-10-08.

## Context

A run on the human's Claude login died with a `claude_agent_sdk.ResultError`
("You've hit your session limit · resets 2:20pm (America/Edmonton)"). It left
only a traceback, `state.json` still said `running`, and the liaison had no
note to relay. The human chose (m3) to **stop cleanly only**: no sleeping
until the reset and no automatic resume.

What the SDK (0.2.163) actually does:

- When the CLI ends a run with an error result, the SDK first yields that
  result as a `ResultMessage` with `is_error=True`. That message carries
  `total_cost_usd`, `usage` and `session_id`. The SDK then raises
  `ResultError(ProcessError)`. `str(exc)` is
  `"Claude Code returned an error result: <errors[] joined, else result text>"`.
  The exception also has `.result`, `.errors`, `.subtype`,
  `.api_error_status`, `.terminal_reason`, `.session_id` and `.data` (the raw
  result payload, including `total_cost_usd` and `usage`).
- The SDK has no dedicated limit exception and no limit error code. A limit
  is recognized only by its prose. `RateLimitEvent` is a stream message that
  says when a window resets. It is not an error.
- An exception raised inside an SDK MCP tool handler (our `run_role`) is
  caught by the SDK (`create_sdk_mcp_server.run_tool`). The PO receives it as
  an `isError` tool result. It **never** reaches the top level. So a limit hit
  inside a role step must be handled by the runner itself.

## Decision

1. A new module `halt.py` turns any exception into a `Halt(kind, reason)`.
   The kinds are `limit`, `crash` and `sigterm`. Classification is data: an
   ordered tuple of detectors, plus a `LIMIT_PATTERNS` table of
   `(regex, reason template)`. The reset text is copied out of the message.
   It is never computed.
2. A table `HALTS` maps each kind to its run status, relay note kind, exit
   code and advice:
   - `limit`: status `blocked`, exit 75 (`EX_TEMPFAIL`).
   - `crash`: new status `failed`, exit 70 (`EX_SOFTWARE`).
   - `sigterm`: new status `stopped`, exit 143 (128 + SIGTERM).
3. The reason is stored in a new `RunState.status_reason`. `status` shows it.
   Every traceback the runner handles is appended to `.team/run/crash.log`.
4. Halts are caught in two places: around a role step's query
   (`Runtime._run_planned`) for limits, and around `asyncio.run` in
   `cli._run` for everything else. `Runtime.halt_run` is the single place
   that records a halt. The first halt in a process wins.
5. SIGTERM is turned into a cancellation of the PO's main task through
   `loop.add_signal_handler`. Cleanup (`finally` blocks, the pid file, the
   SDK's subprocess shutdown) runs as it does for any other exception.
6. `start --resume` resets the status to `running` and clears the reason
   before the PO's query starts. A `blocked` limit stop therefore never
   refuses the resumed PO.

## Alternatives rejected

- **Sleep until the reset and resume.** The human ruled it out (m3). Parsing
  "2:20pm (America/Edmonton)" into a time would also break the rule that the
  reset text is copied, not computed.
- **Match `ResultError` fields (`api_error_status == 429`,
  `terminal_reason`).** The SDK does not document a value that means
  "subscription limit". A 429 is also sent for short, transient rate limits,
  which the CLI already retries. The prose is the only reliable signal. A
  pattern table keeps it to one row per phrasing.
- **Reuse `blocked` for crashes and SIGTERM.** `blocked` means "waiting on
  the human or a reset". A crash needs a look at the log, and `stop --now` was
  the human's own choice. Separate statuses let `status`, the dashboard and
  the liaison tell them apart without parsing the reason.
- **Let a role-step limit propagate to the top level.** This cannot work,
  because the SDK swallows tool-handler exceptions (see Context).
- **Default SIGTERM handling (process dies at once).** `finally` blocks never
  run, so the pid file is left behind and the status stays `running`.

## Consequences

- Two new `RunStatus` values (`failed`, `stopped`) and two new relay kinds of
  the same names. The PO's `notify_user` schema text does not offer them, so
  the PO keeps using `update`, `sprint-end`, `blocked` and `done`.
- Non-limit exceptions inside a role step behave as before: the PO sees the
  error text and decides what to do. Their tracebacks now also go to
  `crash.log`.
- Ctrl-C (`KeyboardInterrupt`) is unchanged: exit 130, no halt record.
- A new phrasing of the limit message is a new row in `LIMIT_PATTERNS`. Until
  that row exists, the stop is recorded as `failed`, and the full text is in
  the reason and `crash.log`.
- `Runtime.halt_run` and `PoRun._collect` are the seams that s9 (saving an
  interrupted step's edits) and s10 (keeping the PO's spend) build on.
