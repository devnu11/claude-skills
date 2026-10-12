# ADR-0030: Gate command timeout and hung test naming

**Status:** Accepted  
**Date:** 2026-10-12  
**Story:** s43

## Context

The runner's gate commands (tests, coverage, git operations, boundary checks) used `subprocess.run` with no timeout or a timeout that did not work: when a test hung, the timeout killed only the shell, then called `communicate()` again **without a deadline**, so child processes still holding the output pipe would hang the runner indefinitely. A hung test in s29 sat idle for over 5 minutes, and the suite could have waited 10 minutes or more.

The problem revealed two gaps:
1. Gate timeouts did not work because the read after the kill had no deadline.
2. A hung test left no trace of which test was stuck—the developer and tester had to guess.

The design (s43) fixes both: each gate command runs in its own process group, and when the time limit is reached, the runner kills **only that group** (not the runner itself). If a test hangs, the runner extracts its name from faulthandler output or traceback and includes it in the bounce reason.

## Decision

**Gate commands have a timeout**, set in `.agile-team.toml` under `[gates]`, field `command_timeout_s` (seconds, float, default `300.0`). The timeout applies to all gate commands: tests, coverage, git operations, and boundary checks. The limit is human-owned; any role edit is quarantined and cannot be bypassed.

**Each command runs in its own process group** (`start_new_session=True`). When the timeout fires:
1. The runner signals only that group with `SIGKILL` (via `os.killpg(pid, signal.SIGKILL)`), not the runner itself.
2. The runner then reads remaining output with a 5-second deadline (`communicate(timeout=5.0)`), preventing escaped processes from hanging the read.
3. If output shows a hung test, the runner extracts the test name (e.g., `test_a.py::test_hangs`) and includes it in the bounce reason.
4. The command returns exit code 124 (GNU `timeout`'s convention) and the bounce reason with the test name as the last line, so `gates.tail` keeps it.

**The bounce reason names the hung test** by trying patterns that match stack frames. A faulthandler-style frame (`File "…", line N in test_x`) and a traceback-style frame (`File "…", line N, in test_x`) are both recognized. The last match (latest dump) wins. If no test is named, the reason falls back to a line saying `"no test is named; a per-test timeout or pytest's faulthandler_timeout would name it"`.

**Bash commands that wait without a deadline are denied** at dispatch. An `until` or `while` loop is blocked unless some command in the same multiline starts with `timeout` or `gtimeout`. This catches the s29 accident (`until grep -q "passed" /tmp/run.log; do sleep 5; done` with no deadline).

**Per-test timeout is configured** via `pytest-timeout>=2.4.0` in the dev dependencies with `timeout = 30` in `pyproject.toml`. A test that hangs fails on its own instead of waiting for the gate's timeout.

## Consequences

**Hung tests cost a minute, not an hour.** When a test hangs, the gate kills it, names it, and bounces within a minute. The developer sees which test hung and can fix it. No role sits idle waiting on a subprocess.

**Process group isolation is reliable.** The runner never signals its own group. Escaped processes (via `setsid`) are not chased. The rule is enforced in code, not just described.

**Drain deadline prevents output hangs.** The 5-second read after the kill ensures that even an escaped process holding the pipe will not hang the runner longer than necessary. Captured output is complete (Python keeps what was read before the timeout).

**Guard rules are data-driven.** The `WAIT_LOOPS` and `DEADLINES` sets define what the guard checks. Adding a timeout variant (e.g., `ntimeout`) is one-line change (add to `DEADLINES`).

**Exact timeout values are auditable.** The default (300 seconds) applies to all commands. Different limits can be set in `.agile-team.toml`, and the history is in git. No hardcoded delays hidden in code.

## Implementation notes

- New module `commands.py` handles shell command execution with timeouts. It imports `signal_child_group` from `process_groups.py` (s41), so the rule for signaling is centralized.
- The `CommandShell` class and `shell_runner` factory replace the inline `subprocess.run` call in `dispatch.py`.
- `hung_test(output)` is extensible: new `HungPattern` rows can recognize other stack formats without changing logic.
- Guard checks are in `guard.py` and run on every bash command, enforced in every view (shell continuations, comment-aware).
- Role rule added to `roles/_shared.md`: "Never wait without a deadline."

## Related ADRs

- **ADR-0041:** Process groups and signal safety (s41) — defines `signal_child_group` and its guards.
- **ADR-0027:** Dashboard snapshot raw data contract (s4) — snapshot has no aggregation.
- **ADR-0007:** Clean halt on limits, crashes, SIGTERM (s8) — halt handling strategy.
