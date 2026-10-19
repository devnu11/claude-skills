# unattended: protocol

Runner: `unattended/runner` (Python ≥ 3.12, `uv`, `claude-agent-sdk`). Run it
as `uv run --frozen --quiet --project ~/.claude/skills/unattended/runner unattended`
(`--frozen`: install the tested `uv.lock` as it is, never re-resolve or
rewrite it).

## Commands

| Command | What it does |
|---|---|
| `start NAME SOURCE [options]` | Create the job and start a detached supervisor (new session, pid file). Prints the job as JSON. |
| `status [NAME]` | The job as JSON; every job without `NAME`. |
| `list` | Every job as JSON. |
| `wait NAME [--until-notice]` | Block until the job ends or its supervisor is gone, print it, and exit with its code. With `--until-notice`, also return on the next [notice](#notices): the report then carries `notice` (the `notify` event), and the exit code is 10 while the job still runs. |
| `log NAME [-f]` | Print `events.jsonl` and the output; `-f` keeps printing until the job ends. |
| `stop NAME` | Write the stop file and SIGTERM the supervisor (on Windows, the stop file alone, seen within 30 s; see [Windows](#windows)). With no supervisor alive, mark the job stopped. |
| `resume NAME [--max-resumes N] [--until T \| --for D] [--max-cost USD] [--hardstop D] [--idle-stop D] [--now] [--foreground]` | Rerun an ended job (`done`, `failed`, `stopped` or `limit-reached`) with the resume prompt or command, or restart an orphaned one (not ended, no supervisor alive); the retry count resets. Limits given replace the old ones; the rest are kept. With `--now`, a `waiting` job whose supervisor is alive is woken instead: the wake file cuts its wait short within 30 s, and the resume counts as usual. |
| `extend NAME [--until T \| --for D] [--hardstop D] [--idle-stop D] [--max-resumes N] [--max-cost USD]` | Change the limits of a job that has not ended (`running` or `waiting`, with or without a live supervisor); logs `extend`. A running job's watch re-reads them within 30 s, so a deadline moved into the future returns the run to the open phase. A stop command already sent is not undone. An ended job is refused: use `resume`. |

`supervise DIR` is internal: it is what the detached process runs.

### `start` options

| Option | Meaning |
|---|---|
| `--prompt T` \| `--prompt-file F` \| `--command C` | What to run; exactly one. |
| `--resume-prompt T` | Prompt for resumes. Default: "Continue where you left off. If you are done, say so." Prompt jobs only. |
| `--resume-command C2` | Command for resumes; default the command. Command jobs only. |
| `--cwd D` | Directory the job runs in; default the current one. |
| `--auth login\|api-key` | Default `login`. See [Auth](#auth). |
| `--key-file F` | API key file for `api-key`; default `~/secrets/anthropic-api-key`. |
| `--allow-sleep` | Let the machine idle-sleep. By default the supervisor keeps it awake; see [Keeping awake](#keeping-awake). |
| `--model M`, `--permission-mode P` | Passed to the Agent SDK. Prompt jobs only. With no `--permission-mode`, the user's settings decide. |
| `--until T` \| `--for D` | Deadline: `21:00`, `9pm`, `tomorrow 9am`, `today 18:15`, ISO (`2026-10-10T09:00`), or a duration (`24h`, `90m`, `1h30m`, `2d`). |
| `--max-resumes N` | Most automatic resumes; default 10. On `resume` it is the new total, not an increment. |
| `--max-cost USD` | Cost cap on the summed `total_cost_usd`. Each prompt run gets what is left as the SDK's `max_budget_usd`, so the run stops itself at the cap. On `resume` it must leave room above what is spent. Command jobs report no cost. |
| `--fallback-wait D` | Wait after a limit with no readable reset time; default `5h`. |
| `--hardstop D` | End a run by force `D` after the deadline (or an idle stop). Optional; without it the deadline only bounds waits. See [Stop phases](#stop-phases). Also on `resume` and `extend`. |
| `--stop-command C` | Run once, in `--cwd` with a 60 s timeout, when a stop sequence reaches its graceful phase (for example `agile-team stop`); its output goes to `output.log`. Command jobs only. |
| `--idle D` \| `--idle off` | Post an `idle` notice after `D` without progress, and `hung` for a heartbeat older than `D`. Default `20m`. |
| `--idle-stop D` | Start the stop sequence once a run has been idle or hung for `D`. Optional. Also on `resume` and `extend`. |
| `--progress KIND[:ARG]` | A progress probe, repeatable; replaces the defaults. See [Progress probes](#progress-probes). Checked at `start`. |
| `--notify CMD` \| `--notify none` | A shell command run on each notice instead of the OS notification; `none` keeps only the event. See [Notices](#notices). |
| `--foreground` | Supervise in this process instead of detaching; for `run_in_background`. |

### Exit codes (`wait`, and `start`/`resume --foreground`)

| Status | Code |
|---|---|
| `done` | 0 |
| `failed` | 1 (also: an orphaned job when `wait` returns) |
| a notice while the job runs (`wait --until-notice`) | 10 |
| `limit-reached` | 75 |
| `stopped` | 143 |

Errors print `unattended <cmd>: <message>` and return 1.

## Job home and files

Jobs live in `<git root>/.claude/jobs/<name>/` when that directory exists, else
`~/.claude/jobs/<name>/`. The git root is that of the directory `unattended`
runs in, not `--cwd`. Names are letters, digits, `.`, `_`, `-` (at most 64) and
unique within a home.

| File | Holds |
|---|---|
| `state.json` | The job (written atomically): `spec` (with `sleep`: `prevent` or `allow`), `bounds`, `status`, `reason`, `runs`, `resumes`, `retries`, `cost`, `session_id`, `next_wake`, `wake_on`. |
| `events.jsonl` | One line per event: `start`, `keep-awake` (by: the inhibitor, or null), `run` (outcome, reason, cost, turns, tokens), `wait` (until, on: the `wake_on` value), `offline` (reason), `online`, `resume`, `extend` (by, deadline, hardstop, idle_stop), `deadline` and `idle-stop` (phase: `graceful` or `hard`, reason), `notify` (trigger, status, reason, by: the notifier, `command`, or null), `end` (status, reason). |
| `heartbeat.json` | The run's heartbeat, written by the job; see [Heartbeat contract](#heartbeat-contract). Removed before each run. |
| `output.md` | A prompt job's latest result text. |
| `output.log` | A command job's output, one `--- run N: <command>` header per run. |
| `supervisor.log` | The detached supervisor's own stderr (tracebacks). |
| `supervisor.pid`, `stop`, `wake` | The live supervisor; a stop request; a request to end the wait now. |

**Is the supervisor alive?** `status`, `wait`, `stop` and `resume` read `supervisor.pid` and probe the process, by platform (`store.ALIVE_PROBES`):

| Platform | Probe |
|---|---|
| macOS, Linux | `os.kill(pid, 0)`: no such process means not alive; a permission error means alive. |
| Windows | `OpenProcess` and then `GetExitCodeProcess` (`STILL_ACTIVE`) through `ctypes`. Access denied means alive. `os.kill` isn't used, because on Windows it terminates the process instead of probing it. See [Windows](#windows). |

### Statuses

`running`, `waiting` (until `next_wake`), and the final ones: `done`, `failed`,
`stopped` (by the user), `limit-reached` (deadline, resumes, cost, a hard or
graceful stop, or an idle stop; a mid-run cost stop keeps the session, so
`resume --max-cost` continues it). Each comes with a `reason`; `limit-reached`
gives the last limit and the bound, e.g. `session limit, resets 7pm; used all
10 resumes`. Stop reasons:

| Reason | When |
|---|---|
| `deadline (graceful)` | the stop command was sent at the deadline and the run then ended, or the deadline passed between runs |
| `deadline (hard stop after 20m)` | the run was ended at the deadline plus `--hardstop` |
| `idle (no progress for 1h; graceful)` | the idle stop sent the stop command and the run then ended |
| `idle (no progress for 1h; hard stop)` | the idle stop ended the run |

`next_wake` is set only while a timed wait is under way; every other status
(including `running` and an offline `waiting`) has it null. `wake_on` says
what a `waiting` job waits for:

| `wake_on` | `next_wake` |
|---|---|
| `reset` | the stated reset plus 3 min |
| `fallback` | now plus `--fallback-wait`: no readable reset time was stated |
| `backoff` | now plus the rate-limit backoff |
| `network` | null: offline, waiting for the API to answer |

## Supervisor loop

```
loop:
  stop file? -> stopped
  deadline passed? -> limit-reached "deadline (graceful)"     # no new run, resume or wait
  remove heartbeat.json; run once, watched:
    every 30 s: re-read state.json; sample the probes
                post idle / hung notices as they become true (each once, re-armed)
                idle or hung for --idle-stop -> start the idle stop sequence
                each stop sequence (deadline, idle stop), each phase once:
                  graceful: log it, notify, run --stop-command (command jobs)
                  hard:     log it, notify, end the run (SIGTERM, SIGKILL after 30 s; cancel)
  a stop was sent -> outcome = HALTED with its reason
  outcome                     # DONE | LIMIT | RATE_LIMITED | OFFLINE | BUDGET | FAILED | HALTED
  runs += 1, cost += run cost, append a run event
  DONE / FAILED -> finish (ended-early notice before the deadline); BUDGET / HALTED -> limit-reached
  next_wake = reset + 3 min   # LIMIT; the fallback wait when no reset is readable
            = now + 1, 2, 4… min (cap 30)   # RATE_LIMITED, consecutive
  OFFLINE -> status waiting (no next_wake); every 30 s probe api.anthropic.com:443 (TCP, no tokens)
             until it answers, then run again (not a resume); more than 10
             in a row -> failed; deadline passes first -> limit-reached
  deadline <= next_wake, resumes >= max, or cost >= max -> limit-reached
  status waiting; sleep in 30 s slices, checking the stop and wake files and the deadline
  resumes += 1; run again as a resume
```

The first run uses the prompt or command. Later runs resume: a prompt job
resumes its saved session with the resume prompt, and a command job runs the
resume command. A prompt job with no saved session yet runs its prompt again.

`limit-reached` posts a `limit-reached` notice.

SIGTERM (`stop`) and Ctrl-C unwind the current run. A command's process group
gets SIGTERM, then SIGKILL after 30 s. The job ends `stopped`. An unexpected
supervisor error ends it `failed` with the traceback in `supervisor.log`.

## Stop phases

A stop sequence starts at the deadline, or when the idle stop fires. It acts
during a run, not only before a wait: each run is waited on in 30 s slices,
and each slice re-reads `state.json` (so `extend` takes effect live).

| Phase | From | What happens |
|---|---|---|
| open | before the start | as usual |
| graceful | the start | No new run, resume or wait. The command job's `--stop-command` runs once; a `deadline` (or `idle-stop`) event and a notice are logged. A prompt job has no stop command, so its run continues. A run that ends on its own here keeps its outcome but is never resumed, unless the stop command was sent: then it ends `limit-reached` with the graceful reason. |
| hard | the start plus `--hardstop` | The run is ended: SIGTERM to the command's process group, SIGKILL after 30 s; a prompt run's query is cancelled (an anyio cancel, so the SDK ends its CLI). |

- A deadline without `--hardstop` has no hard phase, and without a stop
  command its graceful phase does nothing mid-run: the soft deadline of old.
- An idle stop always has a hard phase: `--hardstop` after it starts, or at
  once without `--hardstop` (the stop command, if any, is sent first).
- Each phase acts once per run. Once the idle stop starts, progress no
  longer cancels it.

## Progress probes

A probe reports whether the job has moved since the last slice. The run's
last progress is the last time any probe's reading changed. No change for
`--idle` posts an `idle` notice once, re-armed when progress resumes.

| Kind | Progress means | Jobs |
|---|---|---|
| `output` (command default) | `output.log` changed size or mtime; stdout and stderr both go there | command |
| `spend` (prompt default) | an SDK message arrived (each message, cost included, ticks a counter) | prompt |
| `file:PATH` | the file's size or mtime changed | both |
| `json:PATH:KEY[,KEY…]` | a value at a dotted key changed, e.g. agile-team: `json:.team/run/heartbeat.json:step.turn,step.tokens,chore` | both |
| `heartbeat:PATH` | its `progress` changed; its `at` older than `--idle` means hung | both |
| `cpu` (command default) | the process group's total CPU time changed (`ps -A -o pgid= -o pid= -o time=`) | command |
| `children` | the set of live pids in the process group changed | command |
| `command:CMD` | CMD exited 0 printing nothing, or its stdout changed (10 s timeout; a non-zero exit reads nothing) | both |

Paths are relative to `--cwd`. `--progress` replaces the defaults; the job's
own heartbeat probe is always added. An unknown kind, a bad argument or a
kind that does not fit the job is a usage error at `start`.

A process that sleeps uses no CPU, so `sleep 600` is idle even with `cpu`;
a busy loop or a silent 4-minute test run is not.

## Heartbeat contract

Each run gets `UNATTENDED_HEARTBEAT=<job dir>/heartbeat.json` in its
environment, and unattended always reads it as a `heartbeat:` probe.

- **The job** that wants reliable idle detection rewrites the file
  atomically as `{"at": <epoch seconds>, "progress": <any JSON>}`: `at` at
  least every `--idle`/2, and `progress` changed only when real work happens.
- **Hung:** a file written once whose `at` is then older than `--idle`
  posts a `hung` notice; idle or hung for `--idle-stop` starts the idle
  stop. A job that never writes the file is not hung.
- **Waiting:** a job that is idle on purpose (agile-team waiting on the
  human, s159) adds `"waiting": "<why>"` to the file and keeps `at` fresh.
  While `waiting` is set, the idle stop never starts, and one `waiting`
  notice is posted per wait. It is posted again only after `progress`
  moved. A non-string `waiting` is ignored.
- The file is removed before each run, so a resume does not start hung.

## Notices

| Trigger | Fires when |
|---|---|
| `ended-early` | the job ends `done` or `failed` before its deadline, or it has no deadline |
| `idle` | no probe has moved for `--idle`; once, re-armed when progress resumes |
| `hung` | the heartbeat is stale; once, re-armed when it is fresh |
| `waiting` | the heartbeat says the job waits on purpose (`is waiting: <why>`); once per wait, again only after progress moved |
| `deadline` | the deadline's graceful or hard phase acted |
| `idle-stop` | the idle stop's graceful or hard phase acted |
| `limit-reached` | the bounds ended the job |

Each notice is a `notify` event in `events.jsonl` (the chat: a session in
`wait --until-notice` wakes on it) and, unless `--notify none`, a
notification:

| Platform | Notifier |
|---|---|
| macOS | `osascript -e 'display notification … with title "unattended: <job>"'` |
| Linux | `notify-send "unattended: <job>" …`, when on `PATH` |
| Windows | `powershell -NoProfile -Command …`: a toast through the built-in WinRT `ToastNotificationManager` under PowerShell's app id (`{1AC14E77-…}\WindowsPowerShell\v1.0\powershell.exe`), falling back to a `WScript.Shell` `Popup` that closes after 60 s. Text is passed in the environment. Not run on Windows yet; see [Windows](#windows). |
| others, or the tool missing | none; the event says `"by": null` |

`--notify CMD` runs `sh -c CMD` (the platform shell) instead, with
`UNATTENDED_JOB`, `UNATTENDED_TRIGGER`, `UNATTENDED_REASON`,
`UNATTENDED_TITLE` and `UNATTENDED_BODY` set. Notifiers start detached; the
supervisor never waits on them.

## Windows

Each platform difference is a table row, and CI runs the Windows rows on `windows-latest`:

| What | macOS, Linux | Windows |
|---|---|---|
| Is the supervisor alive? (`store.ALIVE_PROBES`) | `os.kill(pid, 0)` | `OpenProcess` + `GetExitCodeProcess` through `ctypes`. `os.kill` would terminate the process. |
| The command's group (`process_group.GROUPS`) | a new session (`start_new_session`) | a new process group (`CREATE_NEW_PROCESS_GROUP`) |
| Graceful end of the command | SIGTERM to the group | none from the runner: use the job's `--stop-command`. A CTRL_BREAK can end the group's leader first, and `taskkill /T` then can't find the children it left (CI caught this). |
| Hard end of the command | SIGKILL to the group, after a 30 s grace | `taskkill /T /F /PID <pid>` at once: the process and every process it started |
| `stop` (`cli.SUPERVISOR_STOPS`) | SIGTERM to the supervisor, which unwinds at once | the stop file only: the supervisor sees it within one slice (30 s), ends the command's group and marks the job stopped. Any signal would terminate the supervisor. |

Still POSIX only: the `cpu` and `children` progress probes, which read `ps` by process group. The Windows notifier branch is unit-tested but hasn't run on Windows.

## Keeping awake

Unless the job was started with `--allow-sleep`, each supervisor starts an
inhibitor on its own pid, which exits with the supervisor even after a crash,
and logs a `keep-awake` event naming it:

| Platform | Inhibitor |
|---|---|
| macOS | `caffeinate -i -w <pid>` (blocks idle sleep, not lid-close sleep) |
| Linux | `systemd-inhibit --what=idle:sleep … tail --pid=<pid> -f /dev/null` |
| Windows, or the tool not on `PATH` | none; the event says `"by": null` and the job runs anyway |

A job asleep mid-run pauses; one asleep mid-wait resumes late, when the
machine wakes.

## Limit detection

The reason text is matched against these patterns, last match wins:

- `hit your <kind> limit … resets <time>` gives `<kind> limit, resets <time>`;
- `hit your <kind> limit`;
- `usage limit reached`.

The SDK's trailing ` (exit code: N)` is stripped first. A rate limit is an API
error or HTTP status `429` or `529`, `rate limit` or `overloaded`. A network
failure (`OFFLINE`) is `Can't reach the API server`, `ENOTFOUND`, `EAI_AGAIN`,
`ECONNREFUSED`, `ECONNRESET`, `ETIMEDOUT`, `ENETUNREACH` or `connection
error`. Reset times read are `resets 7:20pm
(America/Edmonton)`, `resets 2am` and `resets Oct 10, 5pm`. The zone defaults
to the local one, and the next occurrence after now is used.

## Prompt jobs

- **SDK call:** `claude_agent_sdk.query` with `setting_sources=["user",
  "project", "local"]`, so the job inherits the user's permissions and hooks.
  It also gets `cwd`, `model`, `permission_mode`, `resume=<session_id>`, the
  auth environment, and `max_budget_usd` set to `--max-cost` minus the cost so
  far.
- **Headless permissions:** no one can approve a tool, so the user's settings
  must already allow what the job needs. Use `--permission-mode` to override.
- **Session id:** saved to `state.json` from the first message that carries
  one (the init message's `data["session_id"]`, or any message's
  `session_id`).
- **Cost cap:** a result or `ResultError` with subtype `error_max_budget_usd`
  is a `BUDGET` outcome. The CLI ends the run there; when exactly it checks
  the budget (between turns or mid-response) is not verified.
- **Limits:** a `ResultError` or `ProcessError`, or an error `ResultMessage`,
  whose text matches a limit pattern is a `LIMIT`. One matching a rate limit is
  `RATE_LIMITED`, and one matching a network failure is `OFFLINE`. Anything else is `FAILED` (`crashed: <Type>: <first line>`).
- **Output:** the result text goes to `output.md`. `total_cost_usd`, `usage`
  and `num_turns` go into the run event; cost is summed into `state.cost`. The
  cost of a login run is priced at API rates.

## Command contract

- **Exit codes:** 0 means done. 75 (`EX_TEMPFAIL`, what `agile-team start`
  exits with on a usage limit) means a usage limit. Any other code means
  failed, unless the output's last 50 lines name a network failure: then it
  is `OFFLINE` (agile-team exits 70 on such a crash).
- **Reset time:** on exit 75 the limit reason comes from the first of these
  sources that gives one:
  1. the last `agile-team start: <reason>; run `agile-team start --resume``
     line in the last 50 output lines, taken as is;
  2. `.team/run/state.json` in `--cwd`, when its `status` is `limit`
     (agile-team since s159) or `blocked` (older runs): its
     `status_reason`;
  3. the last 50 output lines, matched against the limit patterns. A bare
     `resets <time>` counts only when the time is readable (`resets 7pm`),
     so prose such as `resets the count` is never a reset.

  When a reason has no readable time, the fallback wait applies and
  `wake_on` is `fallback`.
- **Stop reason (s128):** when `--cwd` holds an agile-team run
  (`.team/run/state.json`), the job records why the run stopped. On exit 0
  the `done` reason is `agile-team <status>: <status_reason>`, or
  `agile-team <status>` when the reason is empty (for example
  `agile-team blocked: Need the API key.` or `agile-team idle: Nothing in
  sprint 4 can move.`). On a failure exit it is
  `exit code N; agile-team halted: <reason>` when the halt line is in the last
  50 output lines, else `exit code N; agile-team <status>…` from the state
  file. Without a state file or a halt line, the reason is what it was before:
  empty on exit 0, `exit code N` on a failure. Reasons are cut to the usual
  reason length.
- **Shell:** the command runs with `sh -c` in `--cwd`, in its own process
  group, with stdin closed and stdout and stderr appended to `output.log`.
- **agile-team:** wrap it as `--command "agile-team start --task '…'"
  --resume-command "agile-team start --resume"`. A command that wants to keep
  a dirty tree's leftover edits across a resume must stash them itself.

## Auth

- **`login` (the default):** passes nothing, so Claude Code uses its login.
  Refuses to start or resume while `ANTHROPIC_API_KEY` is set, because the key
  would win and bill a Console workspace.
- **`api-key`:** reads `--key-file`, else `~/secrets/anthropic-api-key`. The
  file must be mode 600. The key goes only into the job's child environment,
  with `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_AUTH_TOKEN` blanked. Only the
  file's path is stored. There are no session limits, so the rate-limit
  backoff and `--max-cost` matter more.
