# ADR-0031: Signal only process groups the runner created

**Date:** 2026-10-12  
**Status:** Accepted  
**Story:** s41

## Context

Story s29 had a developer step killed by SIGTERM at 01:13 UTC. The cause was unclear, but s41's investigation found it: the agent's own `ps aux | grep "[p]ytest"` matched its CLI (which holds the system prompt on `argv`), so the agent ran `kill <pid>` on itself.

Additionally, the sandbox's signal code (`_signal_group` and `_end_group`) used `os.killpg(os.getpgid(process.pid))`, which sends the signal to the process's group, not necessarily the group it created. A test or code path that hands these a process that is not its own session leader, or a stale pid, would signal the caller's own group—including the agent CLI's group in the runner step.

Two separate but related risks:
1. **Role side:** A role's Bash can kill the runner or agent by name (`pkill`, `ps | grep`) or at runtime (`kill $(...)`, `xargs kill`).
2. **Runner side:** The sandbox signals groups it did not create (via `getpgid` on non-leaders or reused pids).

## Decision

Split the fix into two layers, both enforced in code:

### Runner side (Process group safety)

**New module:** `agile_team/process_groups.py` (stdlib only) exports:
- `leads_own_group(pid)`: true if `pid > 1`, `pid != os.getpgrp()`, and `os.getpgid(pid) == pid`
- `may_signal_child_group(pid)`: gate check for G2 (no `killpg` on the runner's own group, on a non-leader, or on stale pids; only on children that lead their own group or whose leader has exited)
- `signal_child_group(pid, sig)`: send the signal via `os.killpg(pid, sig)` only when `may_signal_child_group(pid)` holds; suppress lookup and permission errors
- `in_runner_group(pid)`: check if a pid is in the runner's own process group (for kill guard checks)
- `parse_etime(text)`: parse `[[dd-]hh:]mm:ss` elapsed time
- `started_at(pid)`: get a process's start time from `ps -o etime=`
- `Recorded`: dataclass holding a pid from a pid file and its mtime; `is_ours()` checks both `leads_own_group` and `started_at` to reject reused pids

**Sandbox changes:**
- `_signal_group(process, sig)` now calls `signal_child_group(process.pid, sig)` (G6)
- `_recorded(pid_file)` reads and returns `Recorded`, handling OSError and ValueError
- `_ends_within(pgid, seconds)` polls `os.killpg(pgid, 0)` with a monotonic deadline; any OSError counts as "gone"
- `_end_group(recorded)` sends SIGTERM, waits, then re-checks `recorded.is_ours()` before SIGKILL (G5: re-check before escalating)
- `stop_stale()` signals only when `recorded.is_ours()`, always deletes the file (G3)

**Commands change:**
- `kill_group(proc)` now calls `signal_child_group(proc.pid, signal.SIGKILL)` (G6)

**Rules (G1–G6):**
- G1: One module (`process_groups`) decides all group signals; no other module calls `os.killpg`
- G2: A child's group is signalled only when `may_signal_child_group(pid)` holds: `pid > 1`, `pid != os.getpgrp()` (runner's own group), and either `os.getpgid(pid) == pid` (child leads its own group) or the lookup raises `ProcessLookupError` (leader exited, no other process reused it)
- G3: A pid from a pid file is signalled only if `Recorded(pid, written).is_ours()` holds: the pid must lead its own group AND have started before the file was written (avoiding reused pids)
- G4: Start time from `ps -o etime=` (stdlib `subprocess.run`) parsed as elapsed time; non-zero exit, empty output, timeout, or `OSError` returns `None`
- G5: Before escalating to SIGKILL, `_end_group` re-checks `recorded.is_ours()` (in case the group exited between SIGTERM and the deadline)
- G6: `Prepared.stop` and `commands.kill_group` use `signal_child_group`

### Role side (Guard against accidental self-kill)

**New module:** `agile_team/kill_check.py` (stdlib only) exports:
- `kill_denial(words)`: check one segment's words against K1, K2, K4; return denial reason or None
- `kill_targets(args)`: drop one signal option and one `--`, return remaining targets
- `target_denial(target)`: check one target against K4; return denial reason or None

**Guard change:**
- In `guard.py` `_check_view`, add `_check_kills(segments)` last (after all other checks)
- `_check_kills` maps `kill_denial` over segments; returns the first non-None denial

**Rules (K1–K5):**
- K1: Commands with `pkill` or `killall` are denied ("picks by name"; agent's argv holds its whole prompt)
- K2: Find the first word whose basename is `kill` in each segment; arguments are later words
- K3: `kill_targets(args)` drops signal option (`-9`, `-TERM`, `-l`, or `-s X` / `-n X`), then `--` if present, then returns rest
- K4: Deny numeric targets:
  - `0` (shell's group)
  - `-1` (every process)
  - `-<runner pgid>` (the runner's own group)
  - `pid > 0` where `in_runner_group(pid)` (alive and in runner's group)
  - Also deny: `$(…)` or backticks in target (run-time chosen), `xargs` before kill (run-time chosen)
  - Pass: `$PID`, `$!`, `%1`, pid outside runner's group, stale pid
- K5: Role file `roles/_shared.md` "Never wait without a deadline" adds: "Stop only what you started, by the pid you saved (`cmd & PID=$!` … `kill $PID`). `pkill`, `killall`, `kill $(…)`, `xargs kill` and a pid in the runner's process group are denied."

**Residual risk (documented in protocol.md):** A variable target (`kill $p` where `p` comes from `pgrep` or `$PPID`) cannot be resolved at parse time and passes. K1 and K4 block the common forms. The rule stops mistakes, not hostile roles.

## Consequences

### Positive

- **Runner stops killing itself:** The sandbox never signals the runner's own group. Stale or reused pids are detected and rejected.
- **Roles cannot self-kill:** K1–K4 block the common forms (by-name, runtime-chosen, same-group pids). Developers see clear, actionable error messages.
- **Escalation is safe:** SIGKILL is sent only after re-checking that the group is still ours (G5).
- **Code-driven:** Two new modules + guard hook enforce the rules in code. The rules appear in tests, config, and prompt as reinforcement, not the only enforcement.
- **Legacy pid files work:** `Recorded` reads bare pid (unchanged format); mtime check dates the file, so reused pids after a long time are rejected.

### Negative

- **No catch for `$PPID`:** The target `kill $PPID` (parent of the agent CLI) is not detected. This is a variable reference and cannot be resolved at parse time. A follow-up story can add K4 rule to deny `$PPID` if it becomes a problem.
- **Over-deny `ps | grep`:** Commands like `grep -rn kill $(git ls-files)` are denied as run-time targets, even though `git ls-files` is not `pgrep`. Roles can rephrase: `grep -rn kill .` or similar. The over-deny is intentional (s7 policy).

## Implementation

Two new modules (process_groups.py, kill_check.py), changes to sandbox.py, commands.py, guard.py, roles/_shared.md.

Documentation: `docs/notes/s41-sigterm-cause.md` (investigation), protocol.md (rules G1–G6, K1–K5), architecture index.

Tests: 19 areas from design checklist (process_groups, sandbox, commands, guard/kill_check, guard order, coverage, ruff).

## References

- Story: `.team/stories/s41.md`
- Design: `agile-team/docs/design/s41.md` (rules, exact strings, test checklist)
- Review: `.team/reviews/s41.md` (all ACs met, three non-blocking follow-ups)
