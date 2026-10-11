# agile-team protocol reference

Loaded on demand by the liaison. Everything here is implemented in
`runner/agile_team/`.

## CLI

Run from the target repo root, or pass `--repo PATH`.

| Command | What it does |
|---|---|
| `init --detect` | Print the detected stack preset, commands, globs and suggested delivery kind as JSON. No writes. |
| `init --preset P --delivery K [--url U] [--docs-dir D] [--artifacts committed\|ignored] [--key-file F] [--budget USD] [--cadence sprint\|until-blocker]` | Phase A: write `.agile-team.toml`, `.gitignore` lines, `.team/CLAUDE.md`, a stub per role in `.team/roles/`; commit `chore(team): onboard agile team`. |
| `init … --reconfigure` | Re-run phase A; keeps every value already in the config and never overwrites the charter. |
| `config check` | Validate config, every role's resolution and glob placeholders. Exit 1 on problems. |
| `roles list` | JSON: each role's layers (built-in, global, repo: `replace`, `addendum` or `stub`) and its resolved model, provider, effort and write scope. |
| `roles scaffold [--global]` | Write a commented stub for `_shared` and every enabled role that has no file yet, in `.team/roles/` (default) or the global dir. Never overwrites. |
| `start --task T [--cadence C] [--onboard] [--resume]` | Preflight, then run the team in the foreground (the liaison backgrounds it): the runner drives the pipeline and calls the PO for judgement (see "Routing"). With `--resume`, `--task` is optional and reaches the PO as "New from the human". Exit codes: see "Run status and stops". |
| `status` | JSON: run `status` and `status_reason` (why the runner stopped, or `null`), current `sprint`, stories with their pipeline step, `sprint` (`null` = backlog) and routing fields (`hold`, `developer`, `previous`; see "Routing"), open questions, spend, the pending sprint `boundary` (or `null`) and `upstream` (the review stack; see "Sprint boundaries"). |
| `answer ID TEXT` | Answer PO question `ID`. |
| `stop [--now]` | Stop after the current role step; `--now` also SIGTERMs the runner, which stops cleanly with status `stopped` (exit 143). |
| `dashboard [--host H] [--port 8765] [--no-open]` | Serve the read-only live dashboard until interrupted (the liaison backgrounds it). Prints `dashboard: <url>` once it is listening, then opens it in a browser unless `--no-open`. Default host: `0.0.0.0` (all interfaces; the URL uses the machine's hostname), `127.0.0.1` on Windows. `--port 0` picks a free port and prints the real one. Exit 1 if the address can't be bound. See "Dashboard". |

`init` (without `--detect`) in a directory that is not a git work tree prints
`agile-team init: not a git repository: <repo>; run git init first` and exits 1.

Preflight refuses to start when: the tree is dirty (except after a kill, see
"Interrupted steps"); with `auth = "api-key"`,
no key file exists, the repo key file is not gitignored, or a key file is not
mode 600; with `auth = "login"`, `ANTHROPIC_API_KEY` is set in the environment; a toolchain
command's executable is missing; `config check` fails.

## Relay files (`.team/run/`, always gitignored)

`outbox.jsonl`, one JSON object per line, written by the PO:

```json
{"id": "m3", "kind": "question", "text": "…", "stories": ["s2"], "at": 1730000000.0}
```

`kind` is one of `question`, `update`, `sprint-end`, `blocked`, `done`,
`failed`, `stopped`. A `question` blocks only the stories it lists. While a
question is open and nothing else can move, the runner keeps running and
waits for the answer. The runner itself posts an `update` at each sprint
end that pushed review branches (or built them without pushing; see
"Sprint boundaries"). A
`manual` delivery's acceptance script arrives as a `question`; the answer is
the human's test result. The runner itself posts `blocked`, `failed` or
`stopped` when it halts (see "Run status and stops").

`inbox.jsonl` holds `{"id", "text", "at"}` answers, written by `answer`.

Other run files: `state.json` (resume state; `task` holds the last
non-resume `start --task`, `""` in older files; `po_cost` holds the PO
session's last running cost, see "Ledger cost"; `in_flight` the role step
running now as `{role, story, brief}`, else `null`; `interrupted` the
interrupted steps not yet shown to the PO, see "Interrupted steps"),
`ledger.jsonl` (per-step cost), `runner.pid` (the live runner's pid; a
stale one is ignored and the next `start` overwrites it), `stop`, `crash.log` (append-only tracebacks of every error the
runner handled, each headed `--- <time> <ExceptionType>`),
`customer/<delivery>/` (Customer Proxy sandboxes), `presentation/<story>/`
(what the Integration Tester presents to the Customer Proxy: see
"Presentation"), `api-key` (default key location).

## Run status and stops

`state.json` `status` (shown by `status`):

| Status | Set by | Meaning |
|---|---|---|
| `idle` | runner | The run ended normally: the PO ended its turn and nothing could move, or a stop took effect after a step. |
| `running` | runner | The run is going (PO turns and router passes). Every `start` sets it, which clears any stop below. |
| `sprint-end`, `done` | PO (`notify_user`) | The sprint or the whole task finished. |
| `blocked` | PO (`notify_user`) or runner | Nothing can move without the human, or a usage limit was hit. |
| `failed` | runner | The runner crashed. |
| `stopped` | runner | `stop --now` (SIGTERM) ended the run. |
| `interrupted` | derived by `status` and the dashboard, never stored | `state.json` says `running`, but `runner.pid` is missing or names a dead process: the runner was killed outright (`kill -9`, power loss, Ctrl-C). `running` is `false`. |

`status` also shows `running` (a live process holds `runner.pid`),
`in_flight` and `interrupted`.

`status_reason` says why the runner stopped (`null` otherwise). For example:
`session limit, resets 2:20pm (America/Edmonton)`, `crashed: RuntimeError:
boom` or `stopped by stop --now`. Older `state.json` files load with `null`.

When the runner halts, it saves the status and reason, posts a note of the
same kind to the outbox, appends the traceback to `crash.log`, prints **one**
line to stderr (`agile-team start: <reason>; <advice>`) and exits:

| Exit | Cause | Status | Advice in the note and line |
|---|---|---|---|
| 0 | the run ended (see "Routing") | `idle`, or what the PO set | — |
| 1 | CLI error or failed preflight | unchanged | the error |
| 70 | any other error in the PO loop | `failed` | ``details in .team/run/crash.log; run `agile-team start --resume` to continue`` |
| 75 | a session or usage limit, in the PO or in a role step | `blocked` | ``run `agile-team start --resume` after the reset`` |
| 77 | spend reached `team.budget_usd` (see "Budget ceiling") | `blocked` | ``raise team.budget_usd in .agile-team.toml, then run `agile-team start --resume` `` |
| 130 | Ctrl-C | unchanged | — |
| 143 | `stop --now` (SIGTERM) | `stopped` | ``run `agile-team start --resume` to continue`` |

- A limit is recognized from the SDK's error text by a pattern table. The
  reset time is copied from that text (`resets 2:20pm (America/Edmonton)`).
  The runner never sleeps or resumes by itself.
- A limit inside a role step stops the run as well. The PO's `run_role`
  returns `{"status": "halted", "reason": …}`, and every later `run_role` in
  that process is refused (`the run is blocked (<reason>); end your turn`).
  Other errors in a role step reach the PO as a tool error, as before, and
  are logged to `crash.log`.
- The first stop in a process wins. Only one note is posted, even when the PO
  then hits the same limit.
- `start --resume` sets `running` and clears `status_reason` before the PO's
  first turn, so a limit stop never leaves the resumed PO refused. When the
  PO's own query failed with an SDK error result (a limit included), its
  session id is saved, so the resume continues that session.
- A step cut off mid-way never leaves its edits in the tree (see
  "Interrupted steps"). The halt note ends with
  `; <role> on <story>'s edits are saved in <sha> (git cherry-pick -n <sha>)`.
  The stderr line does not change.

### Interrupted steps

The runner records the role step in flight (`in_flight`: role, story,
brief) when the step starts and clears it when the step settles. A step
that ends without settling is **interrupted**. Its cause is one of:

| Cause | When the edits are saved |
|---|---|
| `error` | at once, when a role step raises an error that is not a limit (the PO still gets the error text) |
| `limit`, `crash`, `sigterm` | when the run halts (see the table above) |
| `killed` | on `start --resume`, when `state.json` says `running` and `runner.pid` is missing or dead |

Saving means: every changed path, in scope or not, goes into one commit
`chore(team): interrupted step by <role> on <story>` (body `cause: <cause>`),
which is reverted at once, so the tree is clean. With nothing in flight,
the edits are the PO's own turn's (`by product-owner`). The sha is stored
on the story (`interrupted`) and logged as a `step-interrupted` event
(`{cause, commit, brief}`). A step with no edits records no sha.

- The next prompt for **any** role on that story says so and offers the
  work back (``git cherry-pick -n <sha>``). The offer is cleared when a step
  on the story settles.
- Every cause but `error` is also queued in `state.json` `interrupted`. The
  PO's next opening prompt gets an `## Interrupted steps` section (role,
  story, cause, sha, brief), and the queue is cleared. With pending
  interrupted steps, `start --resume` without `--task` gives the PO a turn
  before any router pass.
- `start --resume` after a kill prints
  `agile-team start: the last run was killed; <role> on <story>'s edits are saved in <sha> (reverted)`
  before preflight. A dirty tree with no interrupted run behind it (any other
  status, a live pid, or a plain `start`) is still refused.
- If git fails while saving, the error goes to `crash.log`, the tree is
  left as it is, and preflight refuses it on the next start.

## Dashboard

`agile-team dashboard` is a read-only HTTP server (Python stdlib, no auth).
It never writes, and it never serves files by path.

| Route | Returns |
|---|---|
| `GET /` | the dashboard page (`index.html`, packaged with the runner; vanilla JS, no build step). It loads `api/snapshot`, then follows `api/stream` and reconnects by itself. Its only outside resource is `mermaid@11.4.1` from `cdn.jsdelivr.net`, for the Flow chart. |
| `GET /api/snapshot` | the snapshot as JSON |
| `GET /api/stream` | Server-Sent Events. It sends a `data:` line holding the full snapshot JSON right away, and again whenever a watched file changes (checked once a second). Otherwise it sends a `: keepalive` comment every second. |
| anything else | 404 (other methods: 501) |

The snapshot has these keys: `generated_at`, `run` (status, sprint, cadence,
task, budget, Manager checkpoint percentage, round cap, `manager_due`,
`order`: the priority queue), `pipeline` (enabled steps), `roles` (name,
model, provider, with PO overrides applied), `stories` (in priority order;
state plus `opened_at`, `repeated`, the story file's `acceptance`,
`position`, `in_progress`, `hold` and `wait`: `{"reason", "on"}` or
`null`). The board keeps that order in every column and shows each
unfinished story's `#position`. A story that cannot move shows one pill,
`⏸ <reason>`: `questions`, `manager` (a repeated setback), `round cap`,
`needs the human` (blocked, or an open question names it) or `held` (any
other hold). Below the pill is a `waits on: …` line with the open question
ids and texts, and the last step's summary or the repeated reason. The
timeline shows `escalation`, `fault` and `priority` events. The remaining
keys are `requirements` (from `<docs>/requirements/REQ-*.md`, with
`history` from `requirement-changed` events), `events` (`events.jsonl` plus
outbox and inbox entries as `message`/`answer` events), `ledger`, `messages`,
`answers` and `upstream` (remote, branch, team branch, push permission, the
last end report, the pending boundary and the review stack: each sprint's
branch, base, PR number and URL, `mode` `none`/`draft`/`ready`/`closed`,
`check` `unchecked`/`pass`/`fail`; the Board tab shows it as the **Review
stack** card, and the timeline shows `boundary` events). The contract is
`runner/agile_team/dashboard/fixtures/snapshot.json`. The Tokens tab's role
and story tables show turns per step, the latest step's turns and context
per turn next to tokens and cost (see "Turns and context"). The timeline
shows each step-end's turns and each `po-session` renewal.

Watched and read files: `.team/run/{state.json, events.jsonl, ledger.jsonl,
outbox.jsonl, inbox.jsonl}`, `.agile-team.toml`, `.team/stories/*.md` and
`<docs>/requirements/REQ-*.md`. A missing file gives an empty section. A
torn last line, which can appear while the runner is appending, is skipped.
Each snapshot re-reads `.agile-team.toml`, so a budget, round cap or
pipeline edit shows within a second. While the file is missing or does not
parse, the snapshot uses the config from start. Role files are read once, at
start.

The Board never scrolls sideways: its columns share the page width, and a
column with no cards collapses to a narrow strip. The Tokens tab's bar chart
switches between tokens and dollars. Only that chart changes, and the choice
holds across live updates.

Anyone who can reach the port can see the run (task, stories, questions and
spend). It never shows keys. Use `--host 127.0.0.1` to keep it local to the
machine.

## `.agile-team.toml`

```toml
[team]
docs_dir = "docs"
artifacts = "committed"        # or "ignored"
key_file = ".team/run/api-key" # falls back to ~/secrets/anthropic-api-key
auth = "api-key"               # or "login": run on the human's Claude Code login
cadence = "sprint"             # default; the liaison asks at every start
budget_usd = 20.0              # ceiling: the run halts when spend reaches it
manager_every_pct = 25         # Manager checkpoint every N% of budget

[toolchain]
preset = "python"
test = "uv run pytest"
coverage = "uv run pytest --cov --cov-report=term"  # must print a total %
lint = "uv run ruff check ."
static = "uv run ruff format --check ."
pragma = "# pragma: no cover"

[toolchain.globs]              # {source} {tests} {e2e} {ci} in role globs
source = ["src/**"]
tests = ["tests/**", "!tests/e2e/**"]
e2e = ["tests/e2e/**"]
ci = [".github/workflows/**"]

[gates]
coverage = 95
round_cap = 3
repeat = 2                     # the same setback this many times in a row escalates to the Manager
backstop = 4                   # this many bounces/returns in a row between two steps, any reasons, escalate too
steps = ["design", "tests", "implement", "quality", "review",
         "design-review", "e2e", "acceptance"]   # drop steps to skip them

[upstream]                     # optional; these are the defaults (see Sprint boundaries)
remote = "origin"              # "" turns sync and pull requests off
branch = "main"                # merged in at sprint start; what the bottom PR targets
prefix = "team/sprint-"        # review branch names: <prefix><sprint>

[[delivery]]                   # one or more
name = "cli"
kind = "package"               # package | script | web | library | harness | manual
prepare = "uv venv {sandbox}/venv && uv pip install --python {sandbox}/venv {repo}"
bin = ["venv/bin"]             # prepended to the Proxy's PATH
e2e = ""                       # this delivery's e2e suite, run with the full checks at sprint boundaries
url = ""                       # web only; its host and port fill {host} and {port}
probe = ""                     # web only: path joined to url that must answer 200 (e.g. "api/snapshot")
commands = []                  # harness only: the Proxy's Bash allowlist
# prepare placeholders: {repo}, {sandbox} (absolute paths), {host}, {port} (from url)

[roles.integration-tester]
enabled = false                # disable a role
[roles.developer]
model = "opus"                 # override any frontmatter field
[roles.developer-embedded]
extends = "developer"          # add a role without a file
[roles.scribe]
provider = "local"             # run on a [providers.*] endpoint (see Providers)
model = "qwen3-coder"          # that provider's model name

[providers.local]              # any name but "anthropic", which is built in
base_url = "http://localhost:11434"
kind = "anthropic"             # the only kind so far; see Providers
token_env = ""                 # env var holding its token; empty sends a placeholder
billing = "free"               # free (ledgered as 0) | reported (Claude-priced)
```

Stories pick a delivery with `open_story(…, delivery="cli")`; the default is
the first one.

## Roles

Built-ins live in `runner/agile_team/roles/`. Frontmatter is data:

```yaml
name: unit-tester
model: sonnet          # CLI alias: opus | sonnet | haiku, or a full model id
effort: medium         # low | medium | high | xhigh | max
provider: anthropic    # default; or a [providers.<name>] from the config
tools: [Read, Grep, Glob, Write, Edit, Bash]
write: ["{tests}"]     # !glob excludes; {placeholders} from [toolchain.globs]
read: ["**"]
extends: _shared       # or another role, e.g. developer-cli extends developer
enabled: true
```

### Your instructions: global and repo layers

Two layers of human-written role files sit on top of the built-ins:

| Layer | Directory | Applies to |
|---|---|---|
| global | `~/.config/agile-team/roles/` (`$AGILE_TEAM_HOME/roles/` when set) | every repo |
| repo | `.team/roles/` | this repo |

- `<role>.md` **without** frontmatter is an addendum, appended to the role's
  prompt (global first, then repo). HTML comments are dropped, so a
  scaffolded stub changes nothing until you write in it.
- `<role>.md` **with** frontmatter replaces the role (or adds one). Repo beats
  global beats built-in.
- `_shared.md` addenda apply to every role.

`roles scaffold` writes the stubs; `roles list` shows what each layer does.
Global files can live in a dotfiles repo; the runner only reads them.

System prompt order: `_shared` (+ `_shared` addenda) → role chain bodies →
global addendum → repo addendum → `.team/CLAUDE.md` →
`.team/briefs/<role>.md` → file scope.

## Providers

A role's `provider` picks the endpoint its step talks to. Every provider so far
has a **Claude front end**: the step still runs in Claude Code, with the same
tools, guard hooks, sandbox and handoff, and only the model behind the
Anthropic Messages API changes. Ollama, a LiteLLM proxy or any other
Anthropic-compatible server works. For a provider other than `anthropic`, the
step's environment gets:

- `ANTHROPIC_BASE_URL` set to `base_url`;
- `ANTHROPIC_AUTH_TOKEN` set from `token_env`;
- `ANTHROPIC_API_KEY` blanked, so the project key never leaves for that endpoint;
- Claude Code's default and subagent model variables pinned to the role's
  `model`.

`billing` controls the ledger. With `free`, the step is recorded at $0 and does
not count towards the budget ceiling. With `reported`, the step keeps
`total_cost_usd`, which Claude Code prices at Claude rates (for a resumed PO
query, only its own share: see "Ledger cost").

Preflight probes `base_url` and checks `token_env` for every provider that an
enabled role uses. The PO's kickoff lists each such role as
`role (provider: model)`. `set_role_model` takes a provider, so the PO can move
a struggling role back to `anthropic`.

Which roles suit a local model: Scribe and Code Quality Czar; Unit and
Integration Tester are worth a try. Keep PO, Architect, DevOps, Code Reviewer
and Manager on Claude. DevOps runs on Opus at high effort, like the Architect,
because the tooling and hooks it writes run around every other role. Weak tool use mostly shows up as bad handoffs, which bounce
and count a round. At the round cap, the PO gets the story.

**Other vendors.** `kind` names the harness. Supporting another vendor's agent
CLI (Codex, Gemini, …) would mean adding a `ProviderKind` and a dispatch path
that runs that CLI in place of `query()`. That path would lose the PreToolUse
guard and keep only the post-step diff audit and quarantine. Role files would
not change.

## Handoff block

Every role ends with:

````
```handoff
{"status": "done", "summary": "…", "changed_files": [], "open_questions": [],
 "next_role": null, "friction": ""}
```
````

`status`: `done`, `changes_requested`, `blocked`, `failed`. The Architect
adds `"developer": "<role>"` (a string or `null`) to name the developer
specialisation a story needs; the runner uses it for the implement step (see
"Routing"). `friction` is
optional: what slowed the step down or would make it cheaper. It is logged on
the step-end event for the Manager. A developer at `implement` may add
`"dispute": {"test": "<test id, file path first>", "rule": "<design rule
id>", "reason": "…"}` with status `changes_requested` when a test contradicts
the design (see "Test disputes"). A dispute without `test` and `rule`, or
with another status, is a malformed handoff. The unit-tester may add
`"tests": "changed"` or `"tests": "confirmed"` when a story is back at
`tests` with its code in (see "Back at tests with the code in"). The Manager adds `"ruling"` (`rescope`,
`upgrade_model`, `revise_design`, `escalate`) and may add `"followups":
{"<role>": "<question>"}`. On a story escalated for a repeated setback it
must add `"fault": "<role>"` or `"fault": "runner"` (see "Repeated
setbacks"); a `fault` that is not a non-empty string is a malformed
handoff. The runner appends each follow-up to that role's
next brief under "Questions from the Manager" and clears it once the role
hands off; the answer comes back in that role's `friction`. A missing or
malformed block fails the step (and counts a round).

### What the Manager sees

The Manager's runner context carries `budget` (the corrected
`budget_status`: `spent_usd`, the ceiling `budget_usd`, `remaining_usd`,
`pct_used`, `by_role`, tokens and `po_overcount_usd`; see "Ledger cost"), `spend_by_role`
(steps, cost, cost per step, tokens, `turns_per_step`, `latest_turns` and
`context_per_turn`, most expensive first; see "Turns and context"),
`long_running_roles`, `friction_since_last_review` (friction from step-ends
since its last step) and `pending_followups`, beside the review reasons,
overrides and capped stories. It also carries
`test_disputes_since_last_review` (story, role, test, rule, rounds for each
test dispute since its last step). When it runs on a story escalated for a
repeated setback, it also carries `repeated_setback` (see "Repeated
setbacks"), and `stories_at_round_cap` leaves that story out. The Manager raises every role in
`long_running_roles` as friction in its summary, with one proposal: split
the step, change the brief, or change the tools.

### Rulings

A ruling applies to the story that the Manager's step runs on, at any step
and in any status (active, at the round cap, blocked). It moves the story
(`rescope` → first step, `revise_design` → `design`, `escalate` → blocked)
and resets its rounds and test disputes. The Manager's report carries
`"ruling": {"ruling", "applied": true, "now_at"}`. When the ruling cannot
apply, the report says why and the story does not change:
`{"ruling", "applied": false, "why"}`. That happens when the step has no
story (`a ruling needs a story; run the manager on that story`) or the story
is done (`story sN is done; a ruling cannot move it`). On a repeated
setback the `fault` applies first and a ruling in the same handoff then
wins; see "Repeated setbacks".

### Ledger cost

Each ledger entry's `cost_usd` is what that one query cost. Claude Code's
`total_cost_usd` is a running total for the **session** (ADR-004 in the
docs). A role step always starts a fresh session, so its figure is already
its own. The PO resumes one session, so the runner ledgers only the
difference:

- `own = reported − base` when `reported ≥ base`, else `reported` (a drop
  means the counter restarted). `base` is the running total last seen for
  the session the query resumes, or `0` for a fresh session or a different
  session.
- `state.json` keeps `po_cost: {"session", "reported"}` with the raw
  figure, so `start --resume` keeps the baseline. An older `state.json`
  takes its baseline from the last PO ledger entry.
- The provider's `billing` applies to the own cost. A query with no result
  ledgers `0` and leaves `po_cost` as it was.
- A PO query that is never ledgered (an error result) is still in the
  next query's running total, so that query's difference pays for it.

Ledger lines are never rewritten. PO entries written before s25 are running
totals, so they are corrected when the ledger is read (ADR-007):

- A PO entry with `at` before `1791694950` (2026-10-11 05:02:30 UTC, when
  s25 began ledgering deltas) is legacy. Legacy PO entries, in file order,
  each count only `figure − previous legacy PO figure`, or the figure
  itself when it is lower (a new session). Other entries count as written.
- One function (`ledger.corrected`) does this, and every reader goes
  through it: `status`, `budget_status`, `spend_by_role`,
  `long_running_roles`, the budget checkpoints, the ceiling, the Manager's
  runner context and the dashboard snapshot. They all show the same spend.
- `budget_status` (and `status`'s `budget`) carries `po_overcount_usd`, the
  amount the correction takes off the raw ledger. In this repo that is
  about $1,024.87: ADR-004's $256.93 covered only lines up to 196, and the
  same PO session ran on to line 310.

### Budget ceiling

`team.budget_usd` is a ceiling. The runner halts the run when the corrected
spend, rounded to 4 places as `budget_status.spent_usd` shows it, is at or
over `budget_usd`. It checks:

- after every role step has landed (committed and gated; a step is never
  cut off for budget);
- after every PO query is ledgered;
- at run start, before the PO's first turn. A `start --resume` that is still
  over the ceiling halts at once, with no query and no spend.

The halt is like a limit stop: status `blocked`, `status_reason`
`budget reached: spent $X of $Y`, one `blocked` note to the liaison, every
later `run_role` refused, and exit 77. After a halt, no further PO query
starts in that process. The run can pass the ceiling by at most the step or
PO query that was in progress. To carry on, the human raises `budget_usd` in
`.agile-team.toml` and runs `agile-team start --resume`. The config is read
afresh at start, and `status` and the dashboard re-read it on every call, so
nothing else needs a restart. Under `unattended`, exit 77 ends the job as
failed (it is not a limit to wait out). The Manager checkpoints
(`manager_every_pct`) still apply below the ceiling, on corrected spend.

### Turns and context

Each ledger entry (`ledger.jsonl`, one per role step and per PO query)
records the step's `turns` beside its tokens and cost. The `step-end` event
carries `turns` too. Ledger lines written before turns were recorded count
as steps but are left out of turn averages. Per role (and per story on the
dashboard):

| Field | Meaning |
|---|---|
| `turns_per_step` | turns ÷ steps that recorded turns |
| `latest_turns` | the turns of the role's most recent such step |
| `context_per_turn` | (input + cache read + cache write tokens) ÷ turns: the average context a turn re-sends |

`long_running_roles` lists each role whose last 3 measured steps include at
least 2 of more than 30 turns, with those turns and its `context_per_turn`.

There is **no turn cap**: turns are reported, and no step is stopped for
them. If a cap is ever added, the role gets one warning turn to write its
handoff before the cap ends the step.

Every query (role steps and the PO) runs with `strict_mcp_config` and
`ENABLE_CLAUDEAI_MCP_SERVERS=false`. It loads only the MCP servers the
runner passes (the PO's `team` tools, the Customer Proxy's sandbox servers),
never the human's claude.ai connectors. Why: `docs/adr/ADR-003-lean-context.md`.

### The PO stays in its lane

The PO may read only `.team/**` and the docs directory, so it cannot read
source or tests. Diagnosis goes to the architect, reviewer or devops.

## Pipeline and gates

design (architect) → tests (unit-tester; gate: test command **fails**, or
see "Back at tests with the code in") →
implement (developer-*; gate: tests pass and coverage ≥ threshold, or ≥
`.team/baseline.json` coverage when old debt keeps the total lower) → quality
→ review → design-review → e2e (integration-tester; gate when `acceptance`
is enabled: a `done` handoff passes only with a complete presentation and,
for a `web` delivery, a service that starts from it and answers its probe)
→ acceptance (customer-proxy).

A failed gate or `changes_requested` moves the story back and adds a round
(a test dispute is the exception: see "Test disputes"; the same setback
twice in a row escalates instead: see "Repeated setbacks"). At
`round_cap` the runner refuses every role but the Manager on that story.
`blocked` and `failed` do not count a round. When `e2e` is enabled,
`run_role(customer-proxy)` on a story with no complete presentation does not
start the Proxy. The runner moves the story back to `e2e` **without** a round
(gate event `verdict: "return"`) and reports `{"status": "returned", …}`. The
same happens when a `web` delivery's service does not come up for the Proxy
(the reason holds its output). The runner then runs the integration-tester
itself.

### Repeated setbacks

A **setback** is a gate outcome that sends a story back or holds it:
`bounce`, `return` or `hold`, including a gated role's malformed handoff
(which now logs a `gate` event like any bounce). Passes and test disputes
are not setbacks. For each setback the runner records, on the story's
`streak` in `state.json`: step, step sent to, role, verdict, `author`
(`role` when the reason is a role's handoff, `runner` when the runner's own
gate, return or hold wrote it), the reason, the event id and a **key**:

`<step>><to_step> <normalised reason>`

The reason is lowercased and passed through a table of patterns
(`loops.NORMALISE`): date-times and clock times → `<time>`, URLs → `<url>`,
`host:port` → `<host>`, anything with a `/` → `<path>`, ids such as `s4` or
`e451` → `<id>`, commit shas → `<sha>`, other numbers → `<n>`, runs of
whitespace → one space. So `nothing is listening at 127.0.0.1:8799` and
`nothing is listening at 127.0.0.1:8800` share a key. Two different failing
tests do not.

- A setback with the same key as the last one extends the streak, and a
  different key restarts it at 1. A pass in between does not reset it, so a
  ping-pong between two steps still counts. A Manager ruling or fault
  clears it.
- When the streak would reach `[gates] repeat` (default 2, at least 2), the
  runner does **not** send the story round again. The gate verdict becomes
  `escalate`: the story stays at its step, gets no round, becomes
  `needs_manager`, and `repeated` holds the full reason. The gate event is
  an `escalation` event: the gate fields plus `key`, `author`, `count` and
  `history` (the earlier setbacks' event ids). Every setback's `gate` event
  carries `key`, `author`, `count` and `history` too.
- An escalation is not a hand-over. The router's next step is the
  `manager` **on that story**, with a brief that starts `Story sN hit the
  same setback N times in a row…` and a `repeated_setback` entry in the
  runner context: the reason verbatim (the last gate or job output), key,
  count, author, the history (roles, steps, verdicts, reasons, event ids)
  and the story's `gate`, `step-end`, `test-dispute`, `escalation`,
  `ruling` and `fault` events since the first setback. If the escalating
  step also handed over (questions, blocked), the PO gets the story first,
  and the Manager runs after `continue_story`.
- While a story is escalated, `run_role` of any gated role on it is
  refused: `story sN repeated a setback (<key>); the manager rules on it
  first`.
- The Manager names the owner of the fault with `"fault"`:

  | `fault` | Effect |
  |---|---|
  | a role with an enabled step | the story goes to that role's step, `active` |
  | another known role (e.g. `devops`) | `active`, step kept; the PO gets `off_pipeline_fault` and briefs that role |
  | `runner` | `blocked`; flagged as a runner fault in the `fault` event (`kind: "runner"`); the runner posts an `update` note to the human naming the story and reason, and the PO gets `runner_fault` |

  A fault resets the story's rounds and disputes and clears `streak` and
  `repeated`, so the loop costs no role a round. A `ruling` in the same
  handoff applies after the fault and wins. A missing or unknown fault
  changes nothing (not even a ruling), and the PO gets `fault_not_applied`.
  The Manager's report carries `"fault": {"fault", "kind", "applied",
  "reason", "now_at"}` (or `"why"`), and a `fault` event logs `{fault, kind,
  reason, now_at}`.
- The next standard brief on the story says `The same setback repeated, so
  the manager ruled on it: <reason>`. The Manager's `followups` tell the
  fault role what to fix.
- Role prose seldom repeats word for word, so two summaries saying the same
  thing differently are two keys. The round cap and the backstop still
  apply to them.
- **Backstop.** A `bounce` or `return` from one step to another extends the
  story's `run` when it crosses the same pair of steps as the last one,
  whatever its reason; a new pair restarts it at 1. A pass of the step that
  sends the story back, a fault or a ruling empties it; holds and in-place
  bounces leave it alone. When the run would reach `[gates] backstop`
  (default 4, at least 2), the setback escalates exactly as above, with
  `rule: "backstop"` on the escalation event, every reason in `repeated`,
  and a brief that starts `Story sN bounced between <step> and <to_step> N
  times in a row…`. If both rules fire, the repeat rule wins. Gate events
  carry `bounces` (the run length, 0 when the setback does not count). The
  backstop is for runs that include returns, which count no round; pure
  bounces reach the round cap first.

### Back at tests with the code in

Each story counts how often it has passed the implement gate
(`implemented` in `state.json`). A ruling, a review or a closed dispute can
send a story back to `tests` after its code is in. Its suite may then be
green already. In that case, with no dispute open and a `done` handoff:

- A red suite passes, as on a first pass.
- A green suite passes when the handoff says `"tests": "changed"` (the
  unit-tester changed tests for the story) or `"tests": "confirmed"` (it
  checked that the existing tests already cover it). The gate reason is
  `tests pass on code from an earlier pass; tests <claim>`.
- A green suite without a claim bounces back to `tests` with a round:
  `tests pass on code from an earlier pass; write a failing test, or hand
  off "tests": "changed" or "tests": "confirmed"`.
- A `changes_requested` goes where its `next_role` points, as with an open
  dispute.

The unit-tester's prompt says `Code from an earlier pass is in…` while this
applies. On a first pass (`implemented` is 0) the gate still needs a red
suite, and a claim is ignored. An open dispute's own gate (below) takes
precedence. Any other value of `tests` is a malformed handoff. A
`state.json` written before s24 loads `implemented` as 1 for stories past
`implement` and as 0 for the rest.

### Test disputes

Developers cannot edit tests. When a test contradicts the design, the
developer hands off `changes_requested` with a `dispute` (see "Handoff
block"):

1. The runner moves the story from `implement` to `tests` without running
   the implement gate. It logs a `test-dispute` event (the gate fields plus
   `test`, `rule` and `disputes`) instead of a `gate` event. The first
   `round_cap` disputes on a story count no round, and each later one counts
   a round. A Manager ruling resets the count.
2. Every step on the story gets `Test dispute (raised|confirmed): <test>
   contradicts <rule>: <reason>` in its prompt until the story is back at
   `implement`.
3. At `tests`, the unit-tester either fixes the test and hands off `done`,
   or confirms it with `changes_requested` and `next_role: architect`. A
   `done` passes only when the test file's content changed since the
   dispute was raised; otherwise it bounces and counts a round, with a
   reason naming the test id, the file and the baseline hash. Confirming
   moves the story to `design`, counts a round and marks the dispute
   `confirmed`. The red-tests gate does not run while a dispute is open.
4. The architect rules on a confirmed dispute (it keeps the rule or changes
   the design) and hands off `done`. Back at `tests`, a `done` then passes
   whether or not the test changed, and the story goes on to `implement`.

A dispute is free only when the unit-tester upholds it. If the tester
confirms the test, the developer's round is spent all the same.

How "changed" is checked (s30):

- **Path.** When a dispute is raised, the runner resolves the test file
  (the test id up to `::`) to a tracked path at the repo root. It uses the
  path as given if git tracks it. Otherwise it uses the only tracked file
  that ends with `/<path>` (a runner-relative id such as
  `tests/test_x.py` resolves to `agile-team/runner/tests/test_x.py`). With
  no match, several matches, or an unreadable file, the dispute is
  rejected: the developer's step bounces back to `implement` with a
  round, and the reason says to give the path from the repo root.
- **Baseline.** The dispute stores the resolved `file` and a `baseline`:
  the sha256 of the file's content as it was when the dispute was raised,
  with whitespace and comments removed. Python is compared by its tokens.
  Other files are compared line by line, with whitespace collapsed and
  whole-line comments dropped for known suffixes. The gate compares the
  working tree's file with the baseline, not commits. Editing only
  whitespace or comments is not a change. Changing an assertion, a
  parameter row, a string or a test name is. A deleted file counts as
  changed.
- **Repeats.** The same "unchanged" bounce twice in a row escalates to the
  Manager (see "Repeated setbacks"), so it never runs into the round cap
  by itself.
- **Older disputes.** A dispute saved before s30 has no baseline. It
  passes at the next `done`.
- **Way out.** `pass_tests(story, reason)` (PO tool) moves a story stuck
  at `tests` to the next step. Stuck means one of these: an open dispute,
  `needs_manager`, `blocked`, or a repeated setback. The runner runs the
  test command first and refuses on a red suite, or on a story that is not
  stuck or not at `tests`. The move resets the story's rounds, disputes
  and setback history, clears its hold, and passes `reason` to the next
  brief as a note. It logs a `tests-passed` event and queues a Manager
  review.

## Presentation

The Integration Tester presents each story to the Customer Proxy; the Proxy
never builds or repairs an environment (a broken one is `changes_requested`
to `integration-tester`).

- Before each integration-tester step the runner wipes
  `.team/run/presentation/<story>/` and, for every delivery kind but
  `manual`, creates `workspace/` in it as an empty git repo (`git init`).
- The tester builds the workspace the way a customer would have it (for this
  runner: `agile-team init` already run, plus the run files the ACs need),
  writes `PRESENTATION.md` (what to try for each AC), and adds real
  live-run output such as `agile-team status` as `live-status.json` when an
  AC needs a live run.
- The presentation is self-contained. The Proxy's sandbox can't read repo
  paths, so `PRESENTATION.md` never names one and the presentation holds no
  links into the repo. Anything an AC cites (an ADR, a protocol section,
  files to try, test, coverage or ruff output) goes into the presentation
  as a verbatim copy or as captured output with its command and exit code
  (for example `docs/` and `evidence/`).
- Complete = `PRESENTATION.md` is not blank and, except for `manual`,
  `workspace/` holds something besides `.git`. Otherwise the e2e gate
  bounces with `story sN has no presentation: <path> is missing or empty`.
- **Up and answering** (s26). Each kind's row in `presentation.PRESENTATIONS`
  says whether its check is `files` or `service`; only `web` is `service`.
  For a service, once the files are complete, the e2e gate runs a trial: it
  prepares the sandbox exactly as for the Proxy (presentation copied in),
  starts the delivery's `prepare` in the background, and probes
  `url` + `probe` every 0.25 s for up to 30 s. It passes (`presentation
  ready; <url> answered`) only on HTTP 200 (and, for a JSON response, a
  body that parses), then stops the service. A start that exits or never
  answers bounces to `e2e` with a round:
  `story sN presentation is not up: delivery '<name>' did not start: the start command exited with code <rc> before <url> answered. Last output: …`
  (or `… did not answer <url> within 30s. …`), quoting the last 20 lines of
  its output. A port that another process holds puts the gate on **hold**
  (no round, the PO gets a `gate_hold` hand-over):
  `delivery '<name>' cannot start: <host>:<port> is already in use by a process the runner did not start; stop it or change the delivery's url`.
- For the Proxy step the runner copies the dir to `<sandbox>/presentation/`
  (symlinks kept as links) **before** the delivery's `prepare` runs, so a
  `web` prepare can serve `{sandbox}/presentation/workspace`. A `web`
  service is started and probed the same way before the Proxy starts. The
  Proxy's prompt quotes `PRESENTATION.md` and gives the copy's absolute
  path.
- A service is never reused. Its process group id is in
  `.team/run/customer/<delivery>.pid` and its output is in `<delivery>.log`
  next to it. Before each start, the runner stops a group still named
  there (left by an earlier step or a killed runner). It stops the service
  when the Proxy's step ends (pass, fail, halt or crash) and deletes the pid
  file. It never kills a process it did not start.

The Manager must also run after `start_sprint`, after any `set_role_model`,
and when spend crosses each `manager_every_pct` checkpoint. The runner runs it
before any other step while one of these is due (see "Routing").

## Routing: the runner drives, the PO judges

`start` alternates **PO turns** with **router passes**. A PO turn resumes the
PO's session with one prompt (the kickoff, the resume note or a hand-over)
and lasts until the PO ends its turn. A router pass runs steps with no PO
involved, in this order:

0. the pending sprint **boundary** (sync, full checks, review branches,
   push; see "Sprint boundaries"), one stage per step, or its DevOps fix
   step. A held boundary is skipped. While a boundary is pending, no sprint
   story moves;
1. the `manager`, story-less, while `manager_due` is not empty;
2. the `manager` on a story escalated for a repeated setback (in the
   current sprint, not held, not blocked by a question; see "Repeated
   setbacks");
3. the `scribe`, on each story that has just reached done (`scribe_due`);
4. the next step of the movable story that comes first in the **priority
   ranking** (see "Story priority"). A movable story is in the current sprint,
   `active` and not held, and no open question blocks it. A story that is not
   movable keeps its place in the order and is skipped until it is released.
   Step 2 also takes the escalated story that comes first in the ranking.

The role for a story step is the first of these that fits the step: the PO's
`set_developer` choice, the role a bounce named (`next_role`), the role that
just bounced at this step, the Architect's `developer`, and finally the
step's default role.

Each step gets a **standard brief**. It lists the paths that exist from
`.team/stories/<id>.md`, `<docs>/design/<id>.md` (else
`<docs>/architecture.md`) and `.team/reviews/<id>.md`. It adds the previous
step's role, status and summary; on a bounce or return,
`Sent back to this step: <gate reason or reviewer summary>`; and any
`continue_story` note from the PO.

The pass ends at the first step whose report matches a row of the
`HANDOVERS` table. The PO then gets every matching reason in one prompt:

| Trigger | When |
|---|---|
| `refused` | the step was refused |
| `error` | the step raised an error other than a limit (traceback in `crash.log`) |
| `stopped` | the handoff is `blocked` or `failed` |
| `gate_hold` | the gate put a `done` step on hold for an environment reason (e.g. a `web` delivery's port is in use by another process); `continue_story` once it is fixed |
| `bad_handoff` | the `manager` or `scribe` gave no valid handoff |
| `questions` | the handoff has `open_questions` |
| `quarantine` | the step's out-of-scope changes were quarantined |
| `round_cap` | the story reached the round cap (not an `escalate` verdict) |
| `unroutable` | a bounce names a `next_role` that owns no pipeline step |
| `ruling_not_applied` | the Manager ruled but the ruling could not apply (see "Rulings") |
| `runner_fault` | the Manager put a repeated setback on the runner; the story is blocked and the human was told |
| `off_pipeline_fault` | the Manager put a repeated setback on a role with no pipeline step; brief it, then `continue_story` |
| `fault_not_applied` | the Manager ruled on a repeated setback without a valid `fault` |
| `sync_conflict` | merging upstream into the team branch at sprint start conflicts (files named; the merge was aborted) |
| `push_permission` | the review branches are built and checked, and the human has not yet said whether the team may push |
| `push_rejected` | a review branch push was refused (its remote branch moved) |
| `boundary_error` | a boundary stage raised an error (traceback in `crash.log`) |
| `boundary_escalated` | the same boundary failure repeated after a fix and the Manager reviewed it |

The runner also hands over `human_message` (the inbox has answers the PO has
not seen; they are listed by id with the question), `sprint_end` (every story
in the sprint is done and the sprint's end boundary has finished; a
`Review: …` line says what was pushed) and `stalled` (nothing can move; the
reason for each story is listed, or the held boundary). Gate bounces, `changes_requested` to a pipeline role, a
gated role's malformed handoff and `returned` do **not** hand over. The
runner passes their reasons on in the next standard brief. An `escalate`
verdict does not hand over either: the runner runs the Manager on the
story.

- A story named in a hand-over is **held** (`hold` in `status`): the router
  skips it until the PO calls `continue_story(story, note)` or runs a step on
  it with `run_role`. A done story never moves again, so its hold does not
  stop its Scribe; the Scribe runs after the PO's turn. `continue_story`
  clears a done story's hold too (for example after `ruling_not_applied`),
  and its note reaches the Scribe's brief if the Scribe is still due.
- PO tools added: `continue_story(story, note)` releases a held story (done
  or not) and adds `note` to its next brief. `set_developer(story, role)` picks the
  developer for that story; it refuses an unknown role or one that is not a
  developer. `pass_tests(story, reason)` (s30) moves a story stuck at
  `tests` on when the suite is green (see "Test disputes").
- When nothing can move but a question is open, the runner waits for an
  answer (polling every 5 s, no timeout). `stop` ends the wait.
- The run ends when a stop is requested, the run halts, the PO sets
  `sprint-end` (sprint cadence), `done` or `blocked`, or the PO ends a turn
  and the next pass finds only "sprint complete" or "nothing can move" without
  running a step.
- `start --resume` with no `--task` runs a router pass first. The PO gets a
  turn only when that pass hands over; its prompt then starts with the resume
  note. Exception: with interrupted steps pending, the PO gets the first
  turn (see "Interrupted steps").
- Each hand-over is logged as a `handover` event:
  `{"triggers": [...], "stories": [...], "steps": n}`.
- `state.json` additions: per story `developer`, `po_developer`, `hold`,
  `note`, `previous` (the last gated step: role, status, summary, verdict,
  reason, next_role), `dispute` (the open test dispute: test, rule, reason,
  `file` (resolved at the repo root) and `baseline` (content hash when
  raised, s30), stage `raised` or `confirmed`), `disputes` (disputes since
  the last ruling), `implemented` (implement-gate passes), `streak` (the
  setbacks since the key last changed), `run` (the bounces and returns in a
  row between one pair of steps), `repeated` (the repeated reason while
  escalated, else `null`), `escalated_by` (`repeat`, `backstop` or
  `null`) and `interrupted` (saved work from an interrupted step, offered to
  the next step; see "Interrupted steps"); run-level `order` (the PO's
  story order; see "Story priority"), `scribe_due`, `delivered` (answer ids the
  PO has seen), `goal` (the current sprint's goal), `boundary` and
  `upstream` (see "Sprint boundaries"). Older files load with these empty. On the first run after
  the upgrade, every answer already in the inbox counts as seen.

## PO sessions

The PO is the only role whose session lasts across turns. To keep it from
growing for a whole sprint, the runner **renews** it at two boundaries:
`start_sprint`, and a story reaching done. Each boundary adds a reason to
`state.json` `po_renew_due`. Before the PO's next turn that resumes a
session, the runner renews it once for all the reasons queued, then clears
them:

1. **Compact** (`po_renew_path: "compact"`, the default). One PO query on
   the session with `/compact Keep only what your next turns need: open
   decisions; pending questions with their ids and the stories they block;
   what is next and why; paths to artifacts …`. It worked if the stream
   holds a `compact_boundary` system message. The turn then goes on in the
   same session.
2. **Handoff** (fallback). If no boundary came back, `po_renew_path` becomes
   `"handoff"` from then on (it is saved in `state.json`), and the runner deletes
   `.team/po/handoff.md`. It then asks the PO to write that file (the same
   list) and starts a **fresh** session. The fresh session's first prompt
   holds the kickoff header (mode, cadence, roles, the task), the handoff,
   the `story_status` JSON, the open questions and the prompt the turn was
   going to send. The new session id is saved when that query ends. If the
   PO writes no handoff, the old session goes on (`kept`).

Neither path relies on the PO's memory for the human: every open question
is listed again from the inbox (`- q3 (blocks s5): …`), and answers are
handed over from `delivered` as before. Each renewal is logged as a
`po-session` event: `{"path": "compact" | "handoff" | "kept", "reasons":
[...], "pre_tokens": n | null}`. Renewal queries are ledgered as PO
entries. A halt during a renewal keeps `po_renew_due`, so the next run
renews again. The PO may write `.team/po/**`. Older `state.json` files load
with no reasons and the `compact` path.

## Backlog and sprints

Each story in `state.json` has `sprint`: the number of the sprint it is
committed to, or `null` when it is in the backlog.

- `open_story` puts a story in the backlog.
- `start_sprint(goal, stories)` is the only way into a sprint. It opens sprint
  `N+1` with exactly the listed stories. Unfinished stories it does not list
  go back to the backlog. Done stories never move; they keep the sprint they
  finished in. It refuses an empty list or unknown ids (`unknown stories: s7;
  open them with open_story first`) and changes nothing when it refuses.
- The `sprint-start` event carries `{"sprint", "goal", "stories"}`.
- `run_role` on a backlog story is refused: `story sN is in the backlog; add
  it to a sprint`. The status refusals (done, blocked, round cap) come first.
  `manager`, `scribe` and story-less steps are not affected.
- A story is in at most one sprint. To carry it over or add it mid-sprint,
  list it in the next `start_sprint`, which queues the Manager again.
- `state.json` from before backlogs existed loads every story into the
  backlog. Step, rounds, status and commit are kept. On resume, the runner
  tells the PO that nothing can move, and the PO starts a sprint with the
  stories to continue.
- `start_sprint` opens the sprint's **start boundary**, and it is refused
  while a boundary is pending (`sprint N <edge> boundary is still pending
  (…); finish it first`). See "Sprint boundaries".
- The order in which `start_sprint` lists its stories is their priority (see
  "Story priority").

## Story priority

`state.json` `order` is the PO's explicit list of story ids. It covers
sprint stories and the backlog. One rule ranks every story. These keys are
compared in turn:

1. done stories come last;
2. the story's index in `order`; stories not in `order` come after those
   that are;
3. among stories with no explicit place, a story **in progress** (past the
   first pipeline step, or a step already ran on it) comes before one not
   started. This limits work in progress;
4. the id, with numbers compared as numbers (`s9` before `s10`).

So an explicit place always beats in-progress. The unfinished stories in
this ranking are the **queue**. A story's **position** is its place in the
queue (1 = next). The router follows the ranking (see "Routing"). Holds,
open questions, the round cap and blocks never change the order. A held
story keeps its position and is skipped until it is released. A file
without `order` loads with an empty list, which ranks by rules 3 and 4.

PO tools:

- `prioritise(stories, reason)` puts the listed ids first, in the order
  given. Every other unfinished story keeps its order after them.
- `move_story(story, position, reason)` moves one story to `position`.
- `start_sprint(goal, stories)` puts the sprint's stories first, in the
  order listed. Its reason is the goal.

Each change saves the whole new queue as `order`. A story opened later has
no explicit place until the PO gives it one. Refusals change nothing:
`no stories listed; pass the story ids in the order to work on them`,
`unknown stories: s7; open them with open_story first`, `done stories have
no place in the order: s1`, and `position must be a whole number from 1 to
N`. Each change is logged as a `priority` event (role `product-owner`;
`story` is the moved story for a move):
`{"change": "set" | "move" | "sprint", "order": [...], "moves": [{"story",
"from", "to"}], "reason": "..."}`. `moves` lists only the stories whose
position changed. `story_status` returns the stories in ranking order, with
`order` set to the queue.

## Sprint boundaries: sync, full checks, review stack

At each sprint's start and end the runner runs a **boundary**: code steps,
not prompts, that no role can skip. It is saved as `state.json` `boundary`
(`edge` `start`/`end`, `sprint`, `stage`, `hold`, `failure`, `streak`,
`rounds`, `escalated`, `restack`, `note`) until it finishes. Each stage logs
a `boundary` event (`edge`, `sprint`, `stage`, `outcome`, plus `note`,
`reason`, `sha`, `files`, `branch`, `branches`, `checks`, `hold`, `key`,
`count`, `history` where they apply). While a boundary is pending, no story
in the current sprint moves: `run_role` of a gated role on one is refused
with `sprint N <edge> boundary is at <stage>…; the sprint's stories move
once it passes`.

**Skipped.** With `[upstream] remote = ""`, no such remote, a failed
`git fetch` or no `<remote>/<branch>`, the whole boundary is skipped with
one `skipped` event and a note. This is not an error. (At a sprint end whose
fetch failed, the sprint is still added to the stack.)

**Start** (opened by `start_sprint`, before any role runs, including the
Manager):

1. **sync**: fetch. Drop stack entries whose commits are all in main (see
   below). Then `git merge --no-edit --no-verify <remote>/<branch>` into
   the team branch, with message `chore(team): merge origin/main at sprint
   N start`. If nothing is new, no commit is made. On a conflict the merge
   is aborted, the team branch is unchanged, and the PO gets
   `sync_conflict` with the files. The human merges by hand, and the PO
   calls `continue_boundary`. The team branch is never rebased, reset or
   amended.
2. **check**: the full checks on the team branch (skipped when HEAD is the
   sha that last passed them).
3. **review** and **push**, only when an entry was dropped (a PR was
   merged): the stack is rebuilt and pushed so the next PR is retargeted.

**End** (opened when every sprint story is done, before the `sprint_end`
hand-over):

1. **sync**: fetch, drop merged entries, and add this sprint's entry:
   branch `<prefix><N>`, range `start..end` (start = the previous entry's
   end, or `git merge-base HEAD <remote>/<branch>` for the first one).
2. **check**: the full checks on the team branch.
3. **review**: in the scratch worktree `.team/run/review/`, each entry's
   own commits (`start..end`, no merges, only those whose patch is not in
   main) are cherry-picked onto the latest main, each on the branch below.
   This uses `rerere` and skips picks that come out empty. The branch is
   then set. An entry with nothing left is in main and drops out. The
   bottom and the newest branch get the full checks.
4. **push** (needs `gh` and permission): each branch is pushed with
   `--force-with-lease` against the sha the runner last pushed. Then its PR
   is created or updated: the bottom one is **ready** with base `main`, and
   each other one is a **draft** based on the branch below. A PR that is
   closed (or merged elsewhere) is left alone. The runner posts an `update`
   to the human with the PRs. The sprint-end hand-over then says `Review:
   …`.

**Full checks**: the `[toolchain]` `lint`, `static`, `test` and `coverage`
commands (coverage must reach the gate or the baseline), then each
delivery's `e2e` command. Every configured check runs, and the failed ones
are quoted (`<name> failed (<why>): <command>` plus the last 30 lines).

**Failures.** A failed check or a rebuild conflict becomes a **DevOps fix
step**, whose brief quotes the output. Failed checks on the team branch or
a review branch are fixed on the team branch. For that step DevOps may also
write source, tests and e2e tests, and the runner commits it and checks or
rebuilds again. A conflict is resolved in the review worktree, in exactly
the conflicting files, and recorded with `git rerere`, so later rebuilds
reuse it. A fix step that hands over (blocked, questions…) holds the
boundary. Each failure is a setback keyed `<edge>><stage> <normalised
output>` (see "Repeated setbacks"). The same failure again, or
`round_cap` fix steps, **escalates**: the boundary is held, `manager_due`
gets `sprint N <edge> boundary failed K times at <stage>; see
repeated_boundary`, and the Manager's context carries `repeated_boundary`
(reason, key, count, history, events). The PO then gets
`boundary_escalated` with the Manager's summary.

**Permission.** The first push asks: the PO gets `push_permission`, asks
the human once, and records the answer with `set_push_permission` (`yes`
or `no`). `state.json` keeps it in `upstream.push` for every later sprint.
With `no`, or without `gh`, the branches are built and checked locally,
and the human is told their names.

**Safety.** The runner pushes only branches that start with `[upstream]
prefix`, never the team branch, never `[upstream] branch`. The only force
is the lease on a review branch. Roles still cannot run git commands that
write.

**PO tools.** `continue_boundary(note)` releases a held boundary. Its stage
reruns, and the note reaches the next fix brief. After an escalation it
also resets the streak and rounds. `set_push_permission(answer)`.

`state.json` `upstream`: `team_branch`, `push` (`unasked`/`yes`/`no`),
`stack` (per entry: `sprint`, `branch`, `start`, `end`, `title`, `stories`,
`head`, `checked`, `check`, `pushed`, `pr`, `url`, `base`, `mode`),
`last_end`, `checked` (the last team sha that passed), `closed` (the last
sprint whose end boundary finished) and `report`.

CI: the repo's workflows skip draft PRs (`if:
github.event.pull_request.draft == false`, with the `ready_for_review`
trigger), so only the ready bottom PR runs CI. Merge it with **Rebase and
merge**.

## Enforcement

- PreToolUse hook: Write/Edit/NotebookEdit outside the role's write globs are
  denied. The Customer Proxy's Read/Grep/Glob are limited to its sandbox
  (which holds the presentation copy), `.team/stories/`, `.team/acceptance/`
  (so it can read and rewrite its own report) and `<docs>/customer/`; its
  Bash may not name a forbidden root, `..`, or repo paths outside the
  sandbox. The Integration Tester may also write `.team/run/presentation/**`.
- Before any Bash check, for every role, the hook joins line continuations
  as bash and zsh do: a newline after an odd run of `\` is deleted along with
  the last `\`. After an even run (escaped `\\` pairs) the newline stays and
  ends the command. A `#` comment that ends in `\` does not continue in the
  shell, so a command that holds `#` is also checked in a second view. In
  that view, continuations are joined except on a line that holds `#`. The
  key-name, git, allowlist and path checks run on every view, and a denial in
  any view denies the command. A quoted `#` can over-deny, but no view
  under-denies.
- Forbidden roots: for each positive glob in `[toolchain.globs]` `source`,
  `tests` and `e2e`, the leading path segments before the first segment that
  holds `*`, `?`, `[` or `{` (`agile-team/runner/agile_team/**` →
  `agile-team/runner/agile_team`; `src/main.py` → `src/main.py`). `!` globs and
  globs that start with a wildcard give none. A root nested in another root is
  dropped. With no roots at all, the hook forbids `src`.
- Proxy Bash words: the hook denies a word when the shell (bash or zsh) could
  expand it to a forbidden root or a path under it, read from the repo root.
  Over-denying is accepted. Literal and wildcard words go through the same
  steps:
  1. Words are unquoted by `shlex`. If shlex can't parse the command, the
     whitespace-split words have `'`, `"` and `\` deleted.
  2. Denied: a `..` segment anywhere. Also denied, in any segment except the
     last: a `{` or `(`, or a leading `.` together with `*`, `?` or `[`. Such a
     segment could climb (`..`) or span a `/`.
  3. The word is normalized: leading `.` and `/` are stripped, `a//b` and
     `a/./b` become `a/b`, a trailing `/` is dropped. It is then compared
     without regard to case.
  4. A word made only of `*` and `?` (`ls *`) passes.
  5. The word's segments are paired with each root's segments, from the left.
     The word is denied if the root runs out first, or if a `**` segment is
     reached. It passes if the word runs out first (an ancestor) or if a pair
     doesn't match. A segment with `[`, `{` or `(` matches any one segment.
     Any other segment is matched with `fnmatch`, where `?` counts as `*`.

  So `agile-team status`, `cat agile-team/docs/*.md` and `echo {1..3}` pass.
  `cat agile-team/runner/agile_*/cli.py`, `cat */runner/agile_team/cli.py` and
  `cat {,}agile-team/runner/agile_team/cli.py` are denied. With flat roots
  (`src`), so are `cat src*` and `cat {,}src`, while `ls *` passes. Not
  covered: `$VAR`, `$(…)`, `~`, a change of cwd (`cd`), and words glued to
  `--opt=` or `<`.
- The Proxy's Bash cwd is its sandbox, so a relative path such as
  `cat agile-team/docs/customer/x.md` passes the hook but does not reach the
  docs. The Proxy reads customer docs with the Read tool.
- Every role: no writes under `.git/`; no Read/Grep/Glob/Write of the key
  files or `~/secrets/` (hook plus Claude Code `permissions.deny` rules); Bash
  may not mention `ANTHROPIC_API_KEY` or the key paths; Bash git is limited to
  `status`, `diff`, `log`, `show`, `blame`, `grep`, `ls-files`, `rev-parse`,
  `describe` and `cherry-pick -n`, so no role can commit, rewrite history or
  push. Only the runner pushes, and only review branches (see "Sprint
  boundaries").
- A change to `.agile-team.toml` outside `[toolchain]` and `[[delivery]]` is
  quarantined, so no role can widen its own scope for the next run.
- Residual risk: the key is in the runner's environment, so a role's Bash could
  still read it through an interpreter (e.g. `python -c 'import os; …'`). Use
  a project-scoped key with a Console spend cap.
- After each step the runner diffs the tree. Out-of-scope changes are
  committed as `chore(team): quarantine out-of-scope changes by <role>` and
  reverted at once; the PO gets the sha.
- In-scope changes: the first commit of a story is `feat(<story>): <title>`,
  later ones `fixup! feat(<story>): <title>`. Every step commit has a body
  `<role>: <handoff summary>`, so a fixup says what it changed. Story-less
  steps commit `chore(team): <role> step`; the PO's own story edits commit as
  `chore(team): product-owner step` before the next role runs. Nothing is
  autosquashed.
- Proxy OS sandbox: Claude Code `sandbox.filesystem.denyRead` on the repo with
  `allowRead` for the sandbox, stories, `.team/acceptance` and customer docs, plus
  `permissions.deny` rules `Read(/<repo>/<root>)` and `Read(/<repo>/<root>/**)`
  for each forbidden root, so the rules never cover `<docs>/customer/` unless a
  source or test glob does. Needs bubblewrap (Linux) or Seatbelt (macOS); not
  verified end to end yet.

## Delivery kinds

| kind | prepare | Proxy tools |
|---|---|---|
| `package` | build and install into `{sandbox}` | Bash, Read/Grep/Glob, Write; cwd = sandbox |
| `script` | copy scripts and samples into `{sandbox}` | same as package |
| `web` | start the server in the background (it can serve `{sandbox}/presentation/workspace`); the step waits until `url` + `probe` answers 200; stopped after the step | Playwright MCP, Bash limited to `curl`, Read, Write |
| `library` | build the package; Proxy works in `{sandbox}/consumer` | Bash, Read/Grep/Glob, Write/Edit |
| `harness` | anything DevOps defines | Bash limited to `commands`, Read, Write |
| `manual` | nothing | Read, Write; its acceptance script goes to the human as a question |

When the story has a presentation, every kind gets its copy in
`{sandbox}/presentation/` before `prepare` runs. Every kind except `manual` has a `workspace/` in it.
