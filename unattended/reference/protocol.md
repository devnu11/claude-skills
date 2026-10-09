# unattended: protocol

Runner: `unattended/runner` (Python ≥ 3.12, `uv`, `claude-agent-sdk`). Run it
as `uv run --quiet --project ~/.claude/skills/unattended/runner unattended`.

## Commands

| Command | What it does |
|---|---|
| `start NAME SOURCE [options]` | Create the job and start a detached supervisor (new session, pid file). Prints the job as JSON. |
| `status [NAME]` | The job as JSON; every job without `NAME`. |
| `list` | Every job as JSON. |
| `wait NAME` | Block until the job ends or its supervisor is gone, print it, and exit with its code. |
| `log NAME [-f]` | Print `events.jsonl` and the output; `-f` keeps printing until the job ends. |
| `stop NAME` | Write the stop file and SIGTERM the supervisor. With no supervisor alive, mark the job stopped. |
| `resume NAME [--max-resumes N] [--until T \| --for D] [--max-cost USD] [--foreground]` | Restart a `stopped` or `limit-reached` job, or an orphaned one (not ended, no supervisor alive). Limits given replace the old ones; the rest are kept. |

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
| `--model M`, `--permission-mode P` | Passed to the Agent SDK. Prompt jobs only. With no `--permission-mode`, the user's settings decide. |
| `--until T` \| `--for D` | Deadline: `21:00`, `9pm`, `tomorrow 9am`, `today 18:15`, ISO (`2026-10-10T09:00`), or a duration (`24h`, `90m`, `1h30m`, `2d`). |
| `--max-resumes N` | Most automatic resumes; default 10. On `resume` it is the new total, not an increment. |
| `--max-cost USD` | Cost cap on the summed `total_cost_usd`. Each prompt run gets what is left as the SDK's `max_budget_usd`, so the run stops itself at the cap. On `resume` it must leave room above what is spent. Command jobs report no cost. |
| `--fallback-wait D` | Wait after a limit with no readable reset time; default `5h`. |
| `--foreground` | Supervise in this process instead of detaching; for `run_in_background`. |

### Exit codes (`wait`, and `start`/`resume --foreground`)

| Status | Code |
|---|---|
| `done` | 0 |
| `failed` | 1 (also: an orphaned job when `wait` returns) |
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
| `state.json` | The job (written atomically): `spec`, `bounds`, `status`, `reason`, `runs`, `resumes`, `retries`, `cost`, `session_id`, `next_wake`. |
| `events.jsonl` | One line per event: `start`, `run` (outcome, reason, cost, turns, tokens), `wait` (until), `resume`, `end` (status, reason). |
| `output.md` | A prompt job's latest result text. |
| `output.log` | A command job's output, one `--- run N: <command>` header per run. |
| `supervisor.log` | The detached supervisor's own stderr (tracebacks). |
| `supervisor.pid`, `stop` | The live supervisor; a stop request. |

### Statuses

`running`, `waiting` (until `next_wake`), and the final ones: `done`, `failed`,
`stopped` (by the user), `limit-reached` (deadline, resumes or cost; a
mid-run cost stop keeps the session, so `resume --max-cost` continues it). Each
comes with a `reason`; `limit-reached` gives the last limit and the bound,
e.g. `session limit, resets 7pm; used all 10 resumes`.

## Supervisor loop

```
loop:
  stop file? -> stopped
  outcome = run once          # DONE | LIMIT | RATE_LIMITED | BUDGET | FAILED
  runs += 1, cost += run cost, append a run event
  DONE / FAILED -> finish; BUDGET -> limit-reached
  next_wake = reset + 3 min   # LIMIT; the fallback wait when no reset is readable
            = now + 1, 2, 4… min (cap 30)   # RATE_LIMITED, consecutive
  deadline <= next_wake, resumes >= max, or cost >= max -> limit-reached
  status waiting; sleep in 30 s slices, checking the stop file
  resumes += 1; run again as a resume
```

The first run uses the prompt or command. Later runs resume: a prompt job
resumes its saved session with the resume prompt, and a command job runs the
resume command. A prompt job with no saved session yet runs its prompt again.

SIGTERM (`stop`) and Ctrl-C unwind the current run. A command's process group
gets SIGTERM, then SIGKILL after 30 s. The job ends `stopped`. An unexpected
supervisor error ends it `failed` with the traceback in `supervisor.log`.

## Limit detection

The reason text is matched against these patterns, last match wins:

- `hit your <kind> limit … resets <time>` gives `<kind> limit, resets <time>`;
- `hit your <kind> limit`;
- `usage limit reached`.

The SDK's trailing ` (exit code: N)` is stripped first. A rate limit is an API
error or HTTP status `429` or `529`, `rate limit` or `overloaded`. Reset times read are `resets 7:20pm
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
  `RATE_LIMITED`. Anything else is `FAILED` (`crashed: <Type>: <first line>`).
- **Output:** the result text goes to `output.md`. `total_cost_usd`, `usage`
  and `num_turns` go into the run event; cost is summed into `state.cost`. The
  cost of a login run is priced at API rates.

## Command contract

- **Exit codes:** 0 means done. 75 (`EX_TEMPFAIL`, what `agile-team start`
  exits with on a usage limit) means a usage limit. Any other code means
  failed.
- **Reset time:** read from the last 50 output lines. A line such as `resets
  7pm` is enough. Without one, the fallback wait applies.
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
