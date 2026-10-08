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
| `start --task T [--cadence C] [--onboard] [--resume]` | Preflight, then run the PO loop in the foreground (the liaison backgrounds it). |
| `status` | JSON: run status, current `sprint`, stories with their pipeline step and `sprint` (`null` = backlog), open questions, spend. |
| `answer ID TEXT` | Answer PO question `ID`. |
| `stop [--now]` | Stop after the current role step; `--now` also SIGTERMs the runner. |

Preflight refuses to start when: the tree is dirty; with `auth = "api-key"`,
no key file exists, the repo key file is not gitignored, or a key file is not
mode 600; with `auth = "login"`, `ANTHROPIC_API_KEY` is set in the environment; a toolchain
command's executable is missing; `config check` fails.

## Relay files (`.team/run/`, always gitignored)

`outbox.jsonl`, one JSON object per line, written by the PO:

```json
{"id": "m3", "kind": "question", "text": "…", "stories": ["s2"], "at": 1730000000.0}
```

`kind` is one of `question`, `update`, `sprint-end`, `blocked`, `done`. A
`question` blocks only the stories it lists. A `manual` delivery's acceptance
script arrives as a `question`; the answer is the human's test result.

`inbox.jsonl` holds `{"id", "text", "at"}` answers, written by `answer`.

Other run files: `state.json` (resume state), `ledger.jsonl` (per-step cost),
`runner.pid`, `stop`, `customer/<delivery>/` (Customer Proxy sandboxes),
`api-key` (default key location).

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
- Forbidden roots: for each positive glob in `[toolchain.globs]` `source`,
  `tests` and `e2e`, the leading path segments before the first segment that
  holds `*`, `?` or `[` (`agile-team/runner/agile_team/**` →
  `agile-team/runner/agile_team`; `src/main.py` → `src/main.py`). `!` globs and
  globs that start with a wildcard give none. A root nested in another root is
  dropped. A Bash token names a root when, after stripping leading `.` and `/`
  and normalizing (`a//b`, `a/./b` → `a/b`), it equals the root or starts with
  `root/`. So `agile-team status` and `cat agile-team/docs/customer/x.md` pass,
  and `cat agile-team/runner/agile_team/cli.py` is denied. With no roots at
  all, the hook forbids `src`.
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
