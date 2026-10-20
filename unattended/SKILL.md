---
name: unattended
description: Run a long or expensive prompt or command unattended as a background job that waits out Claude usage limits and resumes itself, within a deadline, a resume count and a cost cap; can bill an API key instead of the login. Use when the user says "run this overnight", "keep going after the limit resets", "resume when the limit resets", "run this on the API key", "spin up a prompt on an API thread", or wants to wrap a long command such as `agile-team start` so it survives session limits. Also "stop it hard at 6pm", "extend the deadline", "tell me if it stalls or goes idle".
---

# unattended

Runs a **prompt** (through the Agent SDK) or a **command** as a job. When the
job hits a usage limit, it saves its session, waits until the reset plus 3
minutes (5 h if no reset time is given), then resumes. A deadline, a maximum
number of resumes and a cost cap stop it.

```sh
UN="uv run --frozen --quiet --project ~/.claude/skills/unattended/runner unattended"
```

`--frozen` runs the skill's tested `uv.lock` as it is; never drop it.

Every flag, the job files, limit detection and the command contract are in
`reference/protocol.md` next to this file. Read it before wrapping a command.

## Steps

1. **Agree the job with the human.** Pick a name. Ask for:
   - the deadline (`--until 'tomorrow 9am'` or `--for 24h`);
   - a hard stop: whether a run still going at the deadline is ended by
     force, and how long after it (`--hardstop 20m`; optional). A command job
     can also get a `--stop-command` that asks it to stop at the deadline;
   - the idle notice: how long without progress before they are told
     (`--idle`, default 20m, `off` to disable);
   - an idle stop: whether a job idle that long is stopped (`--idle-stop 1h`;
     optional; it uses the same stop command and hard stop);
   - the most resumes (default 10) and, for prompts or `--auth api-key`, a
     cost cap (`--max-cost`).

   Then state all of them back, with the auth (login or API key) and the cwd,
   before starting.
2. **Start it:**
   ```sh
   $UN start NAME --prompt-file task.md --for 24h --max-cost 20
   $UN start NAME --command "agile-team start --task '…'" --resume-command "agile-team start --resume" --until 'tomorrow 9am'
   $UN start NAME --command "make soak" --until 18:00 --hardstop 20m --idle-stop 1h
   ```
   `--progress KIND[:ARG]` picks what counts as progress (default: output and
   CPU for a command, SDK messages for a prompt); see the probe table in the
   protocol.
   It prints the job as JSON and returns; the supervisor runs detached.
3. **Get notified:** run `$UN wait NAME --until-notice` with
   `run_in_background`. You are re-invoked on the job's end and on any notice
   (ended early, idle, hung, waiting, deadline stop, idle stop, limit
   reached). `waiting` means the job waits on purpose, e.g. agile-team
   waiting on the human's answer; an idle stop never fires then. Tell
   the human what the notice says, then wait again. Notices also reach the
   OS notification centre (`--notify CMD` replaces it, `--notify none`
   turns it off).
4. **Report:** `$UN status NAME` (for an `agile-team` job, its `reason` says
   why the run stopped, e.g. `agile-team blocked: …`; its `time_left`
   says how long is left before the deadline, e.g. `23h41m` or `overdue`), and the output (`output.md` for prompts,
   `output.log` for commands, in the job's `dir`). `$UN log NAME` shows the
   events: each run, wait and resume.

`$UN stop NAME` stops a job. `$UN resume NAME [--max-resumes N] [--until …]
[--max-cost …]` reruns any ended job (`done` and `failed` too), with the
resume prompt or resume command. It also restarts one whose supervisor died,
for example after a reboot; `status` warns about those.
`$UN resume NAME --now` wakes a job that is waiting for a reset, for when the
limit has reset sooner than the message said.
`$UN extend NAME [--until … | --for …] [--hardstop …] [--idle-stop …]
[--max-resumes N] [--max-cost …]` changes the limits of a job that has not
ended, without stopping it; a running job sees them within 30 s.

A network failure doesn't end a job: the supervisor probes the API with a
plain TCP connect every 30 s, which costs no tokens, and reruns once it
answers.

## Rules

- **Don't poll.** Use `wait` with `run_in_background`, not repeated `status`.
- **Never print, log or echo the API key.** Only name its file.
- **State the limits back before starting.** A prompt run stops itself when
  it reaches `--max-cost`. The job then ends `limit-reached` with its session
  saved, and `resume NAME --max-cost <higher>` continues it. Commands report
  no cost to `unattended`, so they must enforce their own budget.
- **The deadline has phases.** Before it, the job runs as usual. From it, no
  new run, resume or wait starts, and a command job's `--stop-command` is run
  once; a run that ends after that ends the job `limit-reached`, "deadline
  (graceful)". From the deadline plus `--hardstop`, the run is ended
  (SIGTERM to its process group, SIGKILL 30 s later; a prompt run is
  cancelled): "deadline (hard stop after 20m)". Without `--hardstop` a run
  in progress is never cut short. An early end only notifies; nothing
  resumes on its own.
- Prompt jobs use the user's Claude Code settings. Headless, a tool those
  settings don't allow can't be approved by anyone, so allow what the job
  needs first, or pass `--permission-mode`.
- **The machine stays awake** while a job runs or waits (`caffeinate` on
  macOS, `systemd-inhibit` on Linux; none on Windows). Closing a laptop lid
  still sleeps it. Pass `--allow-sleep` to let it idle-sleep.
- Login auth refuses to start while `ANTHROPIC_API_KEY` is set; don't unset it
  for the user without asking.
