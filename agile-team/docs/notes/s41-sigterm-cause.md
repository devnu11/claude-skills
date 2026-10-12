# s41: What SIGTERMed s29's first implement step

**Finding:** the developer agent killed itself. It ran
`ps aux | grep "[p]ytest" | head -3 | cut -c1-200`, took the first hit for a
stray pytest, and ran `kill 83692`. Pid 83692 was its own Claude CLI. That
process matched `pytest` because the Agent SDK puts the role's whole system
prompt on the CLI's command line, and the prompt mentions pytest. The CLI
traps SIGTERM and exits 143. The sandbox's group signalling was not involved.

The fix is in [design/s41.md](../design/s41.md) (rules K1–K5). Hardening the
sandbox (AC2, rules G1–G6) is still done, because the lead was a real risk,
even though it was not the cause.

## Evidence

| # | Source | What it shows |
|---|---|---|
| 1 | `.team/run/crash.log`, entry `2026-10-11 01:13:12 ProcessError` | `Command failed with exit code 143`, raised in `subprocess_cli._read_messages_impl` while `dispatch.collect` read the step's messages. A positive 143 (128 + 15) means the CLI caught SIGTERM and exited by itself. It was not killed outright, which would give `-15`. |
| 2 | `.team/run/events.jsonl` e899 → e900 → e903 | The step started at 1791697820.6 (00:50:20 CDT). The handover `error` came at 1791699192.2 (01:13:12). The **same runner** then quarantined `ff1f1ad` (e901) and re-ran the step (e903). The runner was not signalled. Its SIGTERM handler (`cli._po_until_sigterm`) cancels the PO task, which would have logged a `CancelledError` and halted. |
| 3 | `claude_agent_sdk/_internal/transport/subprocess_cli.py:873` | The SDK starts the CLI with `anyio.open_process(...)` and no new session, so the CLI shares the runner's process group. A signal to that group would have hit the runner too (row 2). So this was not a group signal, which rules out the `_signal_group` / `_end_group` lead. |
| 4 | `subprocess_cli.py:579` | `cmd.extend(["--system-prompt", self._options.system_prompt])`: the role's prompt is on the CLI's argv, and `ps`, `pgrep -f` and `pkill -f` all see it. |
| 5 | Step transcript `~/.claude/projects/-Users-devans-code-claude-skills/191037c8-e17a-4167-a0d1-5a46958771e4.jsonl`, line 433 (06:12:59Z) | `head -c 3000 /tmp/o2.out; ps aux \| grep "[p]ytest" \| head -3 \| cut -c1-200` |
| 6 | same, line 434 | First hit: `devans 83692 2.5 1.2 … ?? S 12:50AM 0:17.50 /private/tmp/claude-501/…/scratchpad/runner-pin/.ven`. It started at 12:50AM, the minute the step started, and runs from the runner pin's venv: the SDK's bundled CLI. `cut -c1-200` cut the line off before it could show that this was not pytest. |
| 7 | same, line 437 (06:13:11.996Z) | `kill 83692 2>/dev/null; cd …/agile-team/runner && python3 - <<'EOF' …` |
| 8 | same, line 443 (06:13:12.055Z) | The tool result is `Exit code 137`: the Bash tool's shell was torn down with the CLI. The transcript ends there, and the runner logged entry 1 at 01:13:12. |
| 9 | same session, lines 141, 339, 413 | Earlier `pkill -f pytest` and `pkill -f test_dbg_tmp` calls did **not** kill the CLI. BSD/macOS `pkill` skips its own ancestors by default, and the CLI is the shell's parent. Linux procps `pkill` skips only itself, so there the same command would have killed the CLI. On both systems it can hit any team process that is not an ancestor (another CLI, the runner, the dashboard, the liaison). `SKILL.md` already records one such hit on a liaison command line. |
| 10 | quarantine `ff1f1ad`, `tests/test_tmp_dbg.py` | A scratch test for `boundary` that the developer was debugging (transcript line 425). It plays no part in the kill. |

## The earlier exit -11 (SIGSEGV)

`crash.log` entry `2026-10-10 03:18:27 ProcessError` (`exit code -11`) is
**unrelated**. That step's transcript
(`72b2bd6b-e37f-4ae7-b245-e76ab4ae1c12.jsonl`, a presentation step for s5)
records its last tool result at 09:16:40Z, an e2e test run. It issues no kill
command, and the CLI died about 107 s later while the model was working. A
negative code means the process was killed by signal 11 and did not trap it.
No runner or test code sends SIGSEGV, and no source file names it. The likely
cause is a native crash in the CLI binary. There is no team action. If it
recurs, s44's interrupted-step display will show it, and the step re-runs as
usual.

## The sandbox lead (not the cause, fixed anyway)

`sandbox._signal_group` sent `os.killpg(os.getpgid(process.pid), sig)`. If a
process does not lead its own group, `getpgid` returns its parent's group, and
in a test that group is the test runner's. `_end_group(pid)` signals a pgid
read from a pid file, so a pid reused by another group leader since the file
was written would be killed. No test hit either case on macOS. The fake pid
`4_000_001` is above macOS's `pid_max` (99998), but it can be live on Linux
(`pid_max` up to 4194304). Rules G1–G6 in the design close both cases.
