---
name: unattended
description: Run a long or expensive prompt or command unattended as a background job that waits out Claude usage limits and resumes itself, within a deadline, a resume count and a cost cap; can bill an API key instead of the login. Use when the user says "run this overnight", "keep going after the limit resets", "resume when the limit resets", "run this on the API key", "spin up a prompt on an API thread", or wants to wrap a long command such as `agile-team start` so it survives session limits.
---

# unattended

Runs a **prompt** (through the Agent SDK) or a **command** as a job. When the
job hits a usage limit, it saves its session, waits until the reset plus 3
minutes (5 h if no reset time is given), then resumes. A deadline, a maximum
number of resumes and a cost cap stop it.

```sh
UN="uv run --quiet --project ~/.claude/skills/unattended/runner unattended"
```

Every flag, the job files, limit detection and the command contract are in
`reference/protocol.md` next to this file. Read it before wrapping a command.

## Steps

1. **Agree the job with the human.** Pick a name. Ask for the deadline
   (`--until 'tomorrow 9am'` or `--for 24h`), the most resumes (default 10)
   and, for prompts or `--auth api-key`, a cost cap (`--max-cost`). Then state
   all of them back, with the auth (login or API key) and the cwd, before
   starting.
2. **Start it:**
   ```sh
   $UN start NAME --prompt-file task.md --for 24h --max-cost 20
   $UN start NAME --command "agile-team start --task '…'" --resume-command "agile-team start --resume" --until 'tomorrow 9am'
   ```
   It prints the job as JSON and returns; the supervisor runs detached.
3. **Get notified:** run `$UN wait NAME` with `run_in_background`. You are
   re-invoked when the job ends.
4. **Report:** `$UN status NAME`, and the output (`output.md` for prompts,
   `output.log` for commands, in the job's `dir`). `$UN log NAME` shows the
   events: each run, wait and resume.

`$UN stop NAME` stops a job. `$UN resume NAME [--max-resumes N] [--until …]
[--max-cost …]` restarts a stopped or limit-reached job. It also restarts one
whose supervisor died, for example after a reboot; `status` warns about those.
`$UN resume NAME --now` wakes a job that is waiting for a reset, for when the
limit has reset sooner than the message said.

## Rules

- **Don't poll.** Use `wait` with `run_in_background`, not repeated `status`.
- **Never print, log or echo the API key.** Only name its file.
- **State the limits back before starting.** A prompt run stops itself when
  it reaches `--max-cost`. The job then ends `limit-reached` with its session
  saved, and `resume NAME --max-cost <higher>` continues it. Commands report
  no cost to `unattended`, so they must enforce their own budget. The deadline
  never cuts a run short: it is checked before each wait.
- Prompt jobs use the user's Claude Code settings. Headless, a tool those
  settings don't allow can't be approved by anyone, so allow what the job
  needs first, or pass `--permission-mode`.
- **The machine stays awake** while a job runs or waits (`caffeinate` on
  macOS, `systemd-inhibit` on Linux; none on Windows). Closing a laptop lid
  still sleeps it. Pass `--allow-sleep` to let it idle-sleep.
- Login auth refuses to start while `ANTHROPIC_API_KEY` is set; don't unset it
  for the user without asking.
