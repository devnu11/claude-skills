# ADR-009: Signal only what you started (s41)

Status: accepted (2026-10-11)

## Context

s29's first implement step ended with the CLI's exit code 143 after 23
minutes, and the work was quarantined (`ff1f1ad`). The investigation is in
`docs/notes/s41-sigterm-cause.md`. The developer agent ran
`ps aux | grep "[p]ytest"`, and the hit was its own Claude CLI. The SDK puts
the role's system prompt on the CLI's argv, and that prompt mentions pytest.
The agent then ran `kill <pid>` on it. The suspected cause, the sandbox
signalling the caller's process group, was not involved. The runner was not
signalled and carried on. Still, that code could signal a group it did not
create: `killpg(getpgid(pid))` on a process that is not a group leader, or a
pid reused after it was recorded.

## Decision

1. **Role Bash may not signal the runner's process group, and may not kill by
   name or by run-time target.** The PreToolUse hook, which runs in the
   runner, denies `pkill` and `killall`, `kill $(…)`, `xargs kill`, and any
   `kill` target that resolves to the runner's group. That group holds the
   runner and the agent CLIs, because the SDK starts them without a new
   session. Over-deny, as with s7.
2. **The runner signals only groups it created.** One module
   (`process_groups.py`) sends every group signal. It sends to a child only
   when the pgid is the child's pid and is not the runner's own group. It
   sends to a group read from a pid file only when that process still leads
   its group and started no later than the file was written (`ps -o etime=`).
   A stale or reused pid is ignored.

## Options considered

- **Pass the system prompt in a file (`--system-prompt-file`)** so that `ps`
  does not show it. Rejected as the fix. It is fragile, because other argv
  words (`--settings`, `--add-dir`, tool names) can still match. It adds a
  file whose lifecycle someone must manage, and it does not stop a role
  killing the runner or another team process by pid. It may still be worth
  doing later to cut the noise in `ps`.
- **Prompt rule only.** Rejected. The charter says process is enforced in
  code, and prompts only state the rule. The prompt rule is still added (K5).
- **Keep the pid-file format and trust `_group_leader`.** Rejected. A reused
  pid that leads some other group passes that check. Comparing the start time
  with the file's mtime fixes this without changing the file format.

## Consequences

- A role stops its own background work with `cmd & PID=$!` … `kill $PID`.
  A variable target cannot be resolved by the hook (residual risk, documented
  in protocol.md).
- A legacy service whose leader died while other members of its group live on
  is no longer killed by group. Its port stays busy and the trial holds
  (`PortBusy`, s26), so the human sees it.
- `ps` runs once per stale pid file. It is bounded by a 5 s timeout and only
  runs when a pid file exists.
