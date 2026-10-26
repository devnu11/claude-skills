# ADR-0048: Runner stages as named, timed data

**Date:** 2026-10-13 (s99 done)

**Status:** Accepted

## Problem

The runner does many internal stages (quality checks, boundary syncs, service starts, etc.). These were unnamed and untimed—invisible to observability. The team needed to see what the runner itself spends time on, similar to how agent steps are visible. The A6 sprint requires stage data for timeline and performance views.

## Decision

Stages are first-class, ordered data. Each stage has:
- **Name** (e.g., `gate.tests+coverage`, `env.prepare`, `boundary.sync`)
- **Metadata:** description, when (before/after/during), attach (step/story/boundary)
- **Timing:** wall-clock and monotonic start times, duration in awake seconds, sleep count
- **Events:** one `runner-stage` event per run, with stage name, timing, command detail, exit code, and exception name if raised

Stages are **opened by callers** (not inferred from commands). Commands are **noted at choke points** (Git._exec, CommandShell.run, upstream.run, sandbox.run_shell, Preparer._serve) where exit codes are known. One event per stage per run, logged to events.jsonl alongside agent events.

Repo tools (`[[tool]]` entries in `.agile-team.toml`) are defined as data (owned by DevOps), validated on load, and listed by `agile-team tools`, but not executed in s99.

## Consequences

### Positive
- **Visible runner work:** Agent steps and runner stages are both data, both timed, both in the event stream.
- **Observability foundation:** A6c and A6e views can render stage timelines and performance charts. Cost accounting can include runner time.
- **Data-driven:** 21 stages in one table (STAGES); no branching. New stages can be added by row.
- **Auditable:** Every stage run writes one event with command detail (masked), exit code, and exception. Gateway to runner performance analysis.
- **DevOps-owned tools:** `[[tool]]` format settles tool ownership in config; future stories can execute repo tools by name without ambiguity.

### Technical
- New modules `stages.py` (pure) and `stage_log.py` (I/O) with ~600 LOC total.
- New event kind `runner-stage` with 11 data keys (stage, when, attach, step, detail, code, raised, started_at, started_mono, started_slept, seconds).
- Changes to 8 modules (commands, git_ops, upstream, sandbox, gates, dispatch, boundary_runner, runner_tools, po_tools) to open/note stages.
- No new external dependency (stdlib contextvars, contextlib only).
- New CLI command `agile-team tools` lists built-in and repo tools as JSON.

### Risks and Mitigations
- **Missed stages:** A test pins that every stage the code runs is in STAGES; unlisted stages fail tests (RS2).
- **Duplicate events:** Closing a stage writes exactly one event, inside finally blocks (RS4).
- **Cost of logging:** Event emission suppresses OSError like turns.jsonl (RS10); lost events don't halt the run.

## Amended by s119 (2026-10-13)

The heartbeat's open stage row (`stage_log.open_row`, shown in
`heartbeat.stages`) gains `description`, the stage's description from
`STAGES`, right after `attach`. Why: the dashboard's live panel must say
what the running stage does, and the description table lives only in
Python; copying it into the page would duplicate it. The closing
`runner-stage` event is unchanged (11 data keys), and the heartbeat version
stays 2 because the key is additive. A row from an older runner has no
`description`; the page shows an empty line for it.

## Amended by s118 (2026-10-13)

The open stage row gains a last key, `tests`: `null`, or the live test
counts of the command running in the stage (`passed`, `warned`, `failed`,
`total`, `points`, `fail_at`; ADR-0053). The key is there from the start so
the row never changes size while the heartbeat serialises it. `StageBoard`
gains `refresh()` (rewrite the listing now; `Hidden` does nothing, `Pulse`
writes). `stages.Run` gains `listeners` and `hear(line)`, and `stages`
gains `current()`; it stays pure. Why: the Flow chart shows a running test
command's counts live (s118 AC6). The closing `runner-stage` event is
unchanged and the heartbeat version stays 2.

## Amended by s127 (2026-10-14)

A stage row gains a `label`, its second field: what the stage runs, in at
most `stages.LABEL_MAX` (24) characters, unique across the table
(`stages.LABELS`). A test pins the table and fails on a missing, long or
repeated label. A repo `[[tool]]` row may give an optional `label`.
Without one, its name is its label (`config.Tool.chart_label`). Loading
refuses a label over 24 characters, and one that repeats another row's or
a built-in's. The `tools` command prints `label` in both lists. Why: the
Flow chart's tool boxes must be one line (ADR-0052, amended by s127), and
the stage name is not a description. Like the description, the label lives
in Python only, and the page reads it from the snapshot. Events don't
change.

## Amended by s126 (2026-10-14)

The table gains a `stop` namespace: `stop.handoff`, `stop.lint`, `stop.suite`,
`stop.red` and `stop.presentation`, all `after`/`step`. They are a role's Stop
hook checks (ADR-0056). They run inside the step but are drawn as the role's
after tool boxes. A run gains an optional `stages.Attempt(n, of)`, which
`StageLog.trying(attempt)` sets for every stage opened inside it. The
heartbeat's open stage row and the `runner-stage` event both gain the key
`attempt` (`{"n", "of"}`, or `null` outside a stop hook). Why: the Flow chart
captions a running stop check `attempt n of 3`. A new event kind, `stop-check`,
records each refused check. The page counts those events per role and stage
for `· n refused`.

## Amended by s175 (2026-10-25)

When a stage raises, the RS5 rule (the first failing command, else the
latest) no longer sets `detail` and `code`. The stage takes them from the
exception: an error raised because one command failed carries a
`stages.Invocation(command, code)` on `stages.CommandFailed`, the new base of
`GitError` and `UpstreamError`. An exception without one gives `detail ""`
and `code null`. The `runner-stage` event gains `error` after `raised`: the
exception's first non-blank line, masked, at most 500 characters, and `null`
when the stage returned. A stage that returns is unchanged. `stages` stays
pure. Why: s165's land raised after a tolerated `git worktree remove` failure,
and the event named that command and kept no message, so nobody could tell
what failed. Carrying the call on the exception holds across the worker
threads the land runs gh in, and it names the right call when a check runs
after the failure (`GhPrs.close` runs `pr view` before it raises).

## References

- Design: `agile-team/docs/design/s99.md` (RS1–RS14, stage table, test checklist)
- Review: `.team/reviews/s99.md` (round 2, verdict ship)
- Builds on: ADR-0032 (s44 chore/meter), ADR-?? (s98 span timing)

## Related Decisions

- **ADR-0032 (s44):** Event logging to events.jsonl; runner stages extend this pattern.
- **s98:** Tool spans (tool calls) are timed similarly; stages extend the timing pattern to runner work.
- **A6 sprint:** Stages are foundational for A6c Timeline view and A6e Stage Performance chart.
