# ADR-0038: Heartbeat resilience, sleep detection, and excuse logic for active work

**Decision date:** 2026-10-12  
**Status:** Accepted  
**Story:** s78

## Context

Story s44 introduced the health check and heartbeat. Subsequent runs revealed two false-red cases:

1. **Tool calls:** While a role made a long tool call (e.g., 4-minute Bash run), the heartbeat became stale and `agile-team watch` reported red ("heartbeat 4 min old"), even though the runner was alive and working.
2. **Gate runs:** While the implement gate was running (90+ seconds into a CPU-heavy pytest run), the heartbeat was silent for over 1 minute, triggering a false red.

Root cause analysis of `turns.jsonl` and the code revealed two issues:

- **Beat thread silenced:** The beat thread can die silently on any exception in the `write()` call (non-`OSError` exceptions are not caught). During a CPU-heavy task, the OS may stall the beat thread, or a transient I/O error may crash it.
- **No sleep detection:** When a Mac sleeps and wakes, wall time jumps but monotonic time does not. The old health code treats all late beats as death, with no way to distinguish sleep from delay.
- **Activity not declared:** Tool calls are visible in the `step.tool` field, but gates run inside the runner's own work and had no marker. A beat without a declared tool or chore looks idle, even though the runner is actively testing.

## Decision

The runner now makes four changes to distinguish real stalls from legitimate delays and sleep:

### D1: Beat thread resilience (H7)

The beat thread can no longer die silently. `Pulse._beat()` catches any `Exception` from `write()`. The first failure is logged via `halt.log_traceback(run_dir, exc)` to `crash.log`; later failures are silent (beat keeps running). An `OSError` from the log write itself is swallowed. The thread loop in `Pulse.beats()` is unchanged; a failed beat does not break the loop.

**Why:** The beat is heartbeats; it must keep beating. If a write fails transiently, the next beat will retry. If it fails permanently, the first failure is logged so a crash analysis can find it. The thread dying silently left no evidence.

### D2: Monotonic time stamps (H8)

The heartbeat dict now includes `"mono": self.pace.mono()` (monotonic time) right after `"at"` (wall time). The `Pace` dataclass gains `mono: Callable[[], float] = time.monotonic`. When a reader (watch or snapshot builder) checks health, it reads both its wall and monotonic time via a new `Clock` class. The health rules use the difference to detect sleep.

**Why:** Monotonic time stops during sleep; wall time continues. A reader can compare the writer's monotonic progress with its own to detect sleep vs. a stalled beat. This is more reliable than guessing based on beat age alone.

### D3: Excuse logic for active work (R17, R19)

A stale beat (older than `stale_s`) is *excused* (shown as amber instead of red) when all of these hold:

- **Work is declared:** Either a `tool` is open in the step, or a `chore` is set (showing the runner is doing something).
- **Machine is awake:** The `slept` value (computed from wall vs. monotonic time) is known and not above `stale_s`.
- **Beat is not too old:** `beat_age <= red_quiet_s` (10 minutes; beyond that, something real went wrong).

If any condition fails, the beat is red (or red for sleep, via D4 below). A chore wins over a tool (since it represents the runner's own work, not a role's).

**Why:** A tool call or gate run is legitimate work; the beat being late during work is not a failure. Amber signals "work in progress; don't alert yet" instead of red "something is broken".

### D4: Sleep detection (R16)

When `slept > stale_s` (the machine was asleep longer than the beat threshold), the verdict is red with reason `"the machine slept for {age(slept)}"`. The reader's monotonic clock is checked first; if it is unknown or the beat has no numeric `mono`, sleep cannot be ruled out, so the beat stays red under the normal rules (R18).

**Why:** A sleeping Mac is a real stall—nothing is running. The human should know. The monotonic comparison is reliable; when it is not available (old heartbeat version or reader clock unknown), we stay safe and color it red.

### D5: Gate runs are a chore (H9)

`Runtime.gate()` now wraps the call to `pipeline.evaluate()` inside `self.pulse.doing(GATE_CHORE.format(step=story.step, story=story.id))`, where `GATE_CHORE = "gate: {step} on {story}"`. The chore is set on entry and restored (to the outer chore) on exit. Boundary stages and quality checks already run as chores; they are unchanged.

**Why:** The gate runs inside the `settling …` chore, so a late beat during a gate shows green or amber: `runner: gate: implement on s71 for 1 min`. The gate's activity is now visible to health.

### D6: Tool calls already refresh the beat (H10)

Tool calls are already tracked; every tool use and result refreshes the heartbeat. This is unchanged and tested.

## Consequences

### Health verdicts now distinguish activity from death

| Case | Before | After | Why |
|---|---|---|---|
| Tool call, stale beat | red | amber | tool is open; work is running |
| Gate run, stale beat | red | amber | chore set; runner is working |
| Machine asleep, stale beat | red (no sleep signal) | red (with "slept for…") | monotonic time detects sleep |
| Real stall (no activity, stale beat) | red | red | unchanged; caught by R18 |
| Beat thread crash | silent failure, stale beat accumulates | logged once, beat continues | first failure in crash.log |

### Code changes per module

**`agile_team/live.py`:**
- `HEARTBEAT_VERSION = 2`
- `Pace` gains `mono: Callable[[], float] = time.monotonic`
- `Pulse._beat()` added; `Pulse.beats()` calls it in the loop
- `Pulse._report()` added; logs first failure to crash.log
- `Pulse.heartbeat()` adds `"mono": self.pace.mono()` in key order: `version, pid, beat, at, mono, started_at, chore, step`

**`agile_team/health.py`:**
- `Clock` class added (wall and monotonic time, read through the system seam)
- `Vitals.read(config, clock: Clock)` signature changed from `now: float`
- `Vitals.slept` property added; returns sleep duration or `None`
- `Vitals.slept_over(limit)` property added
- `Vitals.stale`, `Vitals.busy`, `Vitals.excused` properties added
- Helper functions `_sleep_words()`, `_doing()`, `_late_words()`
- `RULES` updated: R16 (sleep), R18 (stale not excused), R19 (stale excused)
- `current(config)` uses `Clock.read()`

**`agile_team/dispatch.py`:**
- `GATE_CHORE = "gate: {step} on {story}"`
- `Runtime.gate()` wraps `pipeline.evaluate()` in `self.pulse.doing(GATE_CHORE.format(...))`

**`agile_team/dashboard/snapshot.py`:**
- `RunFiles` gains `mono: float | None = None` after `now`
- `load()` passes both `time.time()` and `time.monotonic()`
- `_health()` builds `Clock(now, mono)` for health judgment

**Fixture:**
- `agile-team/dashboard/fixtures/snapshot.json`: `version: 2`, `mono` field after `at`

**Docs:**
- `reference/protocol.md`: Heartbeat v2 shape, health table (R16–R20)
- `docs/customer/dashboard.md`: Health colour rules
- `architecture.md`: Gate chore mechanism

### Test coverage

All new rules (R16–R19) are covered. Tool-call activity, gate activity, sleep, dead runner, stale no-activity, and version-1 beat cases are pinned. Pulse tests cover beat thread resilience, monotonic stamps, and fault logging.

### No changes

- Health decision logic for other cases (R2, R3, R4, R5, R7–R11)
- Gate timeout or process isolation (s43)
- Ledger, cost, or budget enforcement
- Boundary stages or quality check chores
- Config thresholds

## Rationale

This decision refines ADR-0032's health meter by making it accurate in three dimensions:

1. **Activity detection:** Legitimate work (tools, gates) is now visible, so beating while working is amber or green, not red.
2. **Sleep vs. delay:** Monotonic time lets us know when a stall is real (the machine slept) vs. when it is just a late beat during work.
3. **Thread resilience:** A failed beat is logged, not silenced. The beat thread outlives transient I/O errors and continues to run.

Together, these changes ensure that red health means something: the runner is stuck or dead, not just busy. The human can trust red alerts and plan leadership responses around them.

## Risks and mitigations

**Monotonic clock assumption:** This decision assumes the monotonic clock stops during sleep (true on macOS `mach_absolute_time` and Linux `CLOCK_MONOTONIC`, false on some platforms). If a future Python switched macOS to a clock that runs during sleep, `slept` would read ~0, and a sleep would show as R18 red "heartbeat N old" (softer, not false) or be excused if work is running.

**Old heartbeat versions:** Readers can only detect sleep if the writer includes `mono`. Version-1 heartbeats (or readers with unknown monotonic time) fall back to R18: no sleep signal, just red on a stale beat. This is safe (stays red when unsure).
