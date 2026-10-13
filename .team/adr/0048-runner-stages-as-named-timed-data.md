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

## References

- Design: `agile-team/docs/design/s99.md` (RS1–RS14, stage table, test checklist)
- Review: `.team/reviews/s99.md` (round 2, verdict ship)
- Builds on: ADR-0032 (s44 chore/meter), ADR-?? (s98 span timing)

## Related Decisions

- **ADR-0032 (s44):** Event logging to events.jsonl; runner stages extend this pattern.
- **s98:** Tool spans (tool calls) are timed similarly; stages extend the timing pattern to runner work.
- **A6 sprint:** Stages are foundational for A6c Timeline view and A6e Stage Performance chart.
