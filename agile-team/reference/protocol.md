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
| `start --task T [--cadence C] [--onboard] [--resume]` | Preflight, then run the PO loop in the foreground (the liaison backgrounds it). With `--resume`, `--task` is optional and reaches the PO as "New from the human". Exit codes: see "Run status and stops". |
| `status` | JSON: run `status` and `status_reason` (why the runner stopped, or `null`), current `sprint`, stories with their pipeline step and `sprint` (`null` = backlog), open questions, spend. |
| `answer ID TEXT` | Answer PO question `ID`. |
| `stop [--now]` | Stop after the current role step; `--now` also SIGTERMs the runner, which stops cleanly with status `stopped` (exit 143). |
| `dashboard [--host H] [--port 8765] [--no-open]` | Serve the read-only live dashboard until interrupted (the liaison backgrounds it). Prints `dashboard: <url>` once it is listening, then opens it in a browser unless `--no-open`. Default host: `0.0.0.0` (all interfaces; the URL uses the machine's hostname), `127.0.0.1` on Windows. `--port 0` picks a free port and prints the real one. Exit 1 if the address can't be bound. See "Dashboard". |

Preflight refuses to start when: the tree is dirty; with `auth = "api-key"`,
no key file exists, the repo key file is not gitignored, or a key file is not
mode 600; with `auth = "login"`, `ANTHROPIC_API_KEY` is set in the environment; a toolchain
command's executable is missing; `config check` fails.

## Relay files (`.team/run/`, always gitignored)

`outbox.jsonl`, one JSON object per line, written by the PO:

```json
{"id": "m3", "kind": "question", "text": "…", "stories": ["s2"], "at": 1730000000.0}
```

`kind` is one of `question`, `update`, `sprint-end`, `blocked`, `done`,
`failed`, `stopped`. A `question` blocks only the stories it lists. A
`manual` delivery's acceptance script arrives as a `question`; the answer is
the human's test result. The runner itself posts `blocked`, `failed` or
`stopped` when it halts (see "Run status and stops").

`inbox.jsonl` holds `{"id", "text", "at"}` answers, written by `answer`.

Other run files: `state.json` (resume state; `task` holds the last
non-resume `start --task`, `""` in older files), `ledger.jsonl` (per-step cost),
`runner.pid`, `stop`, `crash.log` (append-only tracebacks of every error the
runner handled, each headed `--- <time> <ExceptionType>`),
`customer/<delivery>/` (Customer Proxy sandboxes), `api-key` (default key
location).

## Run status and stops

`state.json` `status` (shown by `status`):

| Status | Set by | Meaning |
|---|---|---|
| `idle` | runner | The PO ended its turn normally. |
| `running` | runner | The PO loop is running. Every `start` sets it, which clears any stop below. |
| `sprint-end`, `done` | PO (`notify_user`) | The sprint or the whole task finished. |
| `blocked` | PO (`notify_user`) or runner | Nothing can move without the human, or a usage limit was hit. |
| `failed` | runner | The runner crashed. |
| `stopped` | runner | `stop --now` (SIGTERM) ended the run. |

`status_reason` says why the runner stopped (`null` otherwise). For example:
`session limit, resets 2:20pm (America/Edmonton)`, `crashed: RuntimeError:
boom` or `stopped by stop --now`. Older `state.json` files load with `null`.

When the runner halts, it saves the status and reason, posts a note of the
same kind to the outbox, appends the traceback to `crash.log`, prints **one**
line to stderr (`agile-team start: <reason>; <advice>`) and exits:

| Exit | Cause | Status | Advice in the note and line |
|---|---|---|---|
| 0 | the PO ended its turn | `idle`, or what the PO set | — |
| 1 | CLI error or failed preflight | unchanged | the error |
| 70 | any other error in the PO loop | `failed` | ``details in .team/run/crash.log; run `agile-team start --resume` to continue`` |
| 75 | a session or usage limit, in the PO or in a role step | `blocked` | ``run `agile-team start --resume` after the reset`` |
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
- A step cut off mid-way can leave uncommitted edits, and preflight then
  refuses the dirty tree. After a halt the runner commits nothing more: the
  cut-off step's edits and the PO's edits from that turn stay in the tree
  for the human.

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
task, budget, Manager checkpoint percentage, round cap, `manager_due`),
`pipeline` (enabled steps), `roles` (name, model, provider, with PO
overrides applied), `stories` (state plus `opened_at` and the story file's
`acceptance`), `requirements` (from `<docs>/requirements/REQ-*.md`, with
`history` from `requirement-changed` events), `events` (`events.jsonl` plus
outbox and inbox entries as `message`/`answer` events), `ledger`, `messages`
and `answers`. The contract is
`runner/agile_team/dashboard/fixtures/snapshot.json`.

Watched and read files: `.team/run/{state.json, events.jsonl, ledger.jsonl,
outbox.jsonl, inbox.jsonl}`, `.team/stories/*.md` and
`<docs>/requirements/REQ-*.md`. A missing file gives an empty section. A
torn last line, which can appear while the runner is appending, is skipped.
Role files and `.agile-team.toml` are read once, at start.

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
budget_usd = 20.0              # soft budget, enforced by the Manager
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
steps = ["design", "tests", "implement", "quality", "review",
         "design-review", "e2e", "acceptance"]   # drop steps to skip them

[[delivery]]                   # one or more
name = "cli"
kind = "package"               # package | script | web | library | harness | manual
prepare = "uv venv {sandbox}/venv && uv pip install --python {sandbox}/venv {repo}"
bin = ["venv/bin"]             # prepended to the Proxy's PATH
url = ""                       # web only
commands = []                  # harness only: the Proxy's Bash allowlist

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
not count towards the soft budget. With `reported`, the step keeps
`total_cost_usd`, which Claude Code prices at Claude rates.

Preflight probes `base_url` and checks `token_env` for every provider that an
enabled role uses. The PO's kickoff lists each such role as
`role (provider: model)`. `set_role_model` takes a provider, so the PO can move
a struggling role back to `anthropic`.

Which roles suit a local model: Scribe, Code Quality Czar and DevOps; Unit and
Integration Tester are worth a try. Keep PO, Architect, Code Reviewer and
Manager on Claude. Weak tool use mostly shows up as bad handoffs, which bounce
and cost a PO turn.

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
 "next_role": null}
```
````

`status`: `done`, `changes_requested`, `blocked`, `failed`. The Manager adds
`"ruling"`: `rescope`, `upgrade_model`, `revise_design`, `escalate`. A missing
or malformed block fails the step (and counts a round).

## Pipeline and gates

design (architect) → tests (unit-tester; gate: test command **fails**) →
implement (developer-*; gate: tests pass and coverage ≥ threshold, or ≥
`.team/baseline.json` coverage when old debt keeps the total lower) → quality
→ review → design-review → e2e → acceptance (customer-proxy).

A failed gate or `changes_requested` moves the story back and adds a round. At
`round_cap` the runner refuses every role but the Manager on that story.
`blocked` and `failed` do not count a round.

The Manager must also run after `start_sprint`, after any `set_role_model`,
and when spend crosses each `manager_every_pct` checkpoint.

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
  backlog. Step, rounds, status and commit are kept. On resume, the PO starts
  a sprint with the stories to continue.

## Enforcement

- PreToolUse hook: Write/Edit/NotebookEdit outside the role's write globs are
  denied. The Customer Proxy's Read/Grep/Glob are limited to its sandbox,
  `.team/stories/` and `<docs>/customer/`; its Bash may not name a forbidden
  root, `..`, or repo paths outside the sandbox.
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
  push.
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
  `allowRead` for the sandbox, stories and customer docs, plus
  `permissions.deny` rules `Read(/<repo>/<root>)` and `Read(/<repo>/<root>/**)`
  for each forbidden root, so the rules never cover `<docs>/customer/` unless a
  source or test glob does. Needs bubblewrap (Linux) or Seatbelt (macOS); not
  verified end to end yet.

## Delivery kinds

| kind | prepare | Proxy tools |
|---|---|---|
| `package` | build and install into `{sandbox}` | Bash, Read/Grep/Glob, Write; cwd = sandbox |
| `script` | copy scripts and samples into `{sandbox}` | same as package |
| `web` | start the server in the background; stopped after the step | Playwright MCP, Bash limited to `curl`, Write |
| `library` | build the package; Proxy works in `{sandbox}/consumer` | Bash, Read/Grep/Glob, Write/Edit |
| `harness` | anything DevOps defines | Bash limited to `commands`, Write |
| `manual` | nothing | Write; its acceptance script goes to the human as a question |
