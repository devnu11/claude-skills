# agile-team protocol reference

Loaded on demand by the liaison. Everything here is implemented in
`runner/agile_team/`.

## CLI

Run from the target repo root, or pass `--repo PATH`.

| Command | What it does |
|---|---|
| `init --detect` | Print the detected stack preset, commands, globs and suggested delivery kind as JSON. No writes. |
| `init --preset P --delivery K [--url U] [--docs-dir D] [--artifacts committed\|ignored] [--key-file F] [--budget USD] [--cadence sprint\|until-blocker]` | Phase A: write `.agile-team.toml`, `.gitignore` lines, `.team/CLAUDE.md`, `.team/roles/`; commit `chore(team): onboard agile team`. |
| `init … --reconfigure` | Re-run phase A; keeps every value already in the config and never overwrites the charter. |
| `config check` | Validate config, every role's resolution and glob placeholders. Exit 1 on problems. |
| `start --task T [--cadence C] [--onboard] [--resume]` | Preflight, then run the PO loop in the foreground (the liaison backgrounds it). |
| `status` | JSON: run status, stories and their pipeline step, open questions, spend. |
| `answer ID TEXT` | Answer PO question `ID`. |
| `stop [--now]` | Stop after the current role step; `--now` also SIGTERMs the runner. |

Preflight refuses to start when: the tree is dirty; no key file exists; the
repo key file is not gitignored; a key file is not mode 600; a toolchain
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
```

Stories pick a delivery with `open_story(…, delivery="cli")`; the default is
the first one.

## Roles

Built-ins live in `runner/agile_team/roles/`. Frontmatter is data:

```yaml
name: unit-tester
model: sonnet          # CLI alias: opus | sonnet | haiku, or a full model id
effort: medium         # low | medium | high | xhigh | max
tools: [Read, Grep, Glob, Write, Edit, Bash]
write: ["{tests}"]     # !glob excludes; {placeholders} from [toolchain.globs]
read: ["**"]
extends: _shared       # or another role, e.g. developer-cli extends developer
enabled: true
```

Per repo: `.team/roles/<role>.md` **without** frontmatter is appended to that
role's prompt; **with** frontmatter it replaces the built-in (or adds a role).

System prompt order: `_shared` → role chain bodies → repo addendum →
`.team/CLAUDE.md` → `.team/briefs/<role>.md` → file scope.

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

## Enforcement

- PreToolUse hook: Write/Edit/NotebookEdit outside the role's write globs are
  denied. The Customer Proxy's Read/Grep/Glob are limited to its sandbox,
  `.team/stories/` and `<docs>/customer/`; its Bash may not name source or test
  directories, `..`, or repo paths outside the sandbox.
- After each step the runner diffs the tree. Out-of-scope changes are
  committed as `chore(team): quarantine out-of-scope changes by <role>` and
  reverted at once; the PO gets the sha.
- In-scope changes: the first commit of a story is `feat(<story>): <title>`,
  later ones `fixup! feat(<story>): <title>`. Story-less steps commit
  `chore(team): <role> step`. Nothing is autosquashed.
- Proxy OS sandbox: Claude Code `sandbox.filesystem.denyRead` on the repo with
  `allowRead` for the sandbox, stories and customer docs. Needs
  bubblewrap (Linux) or Seatbelt (macOS); not verified end to end yet.

## Delivery kinds

| kind | prepare | Proxy tools |
|---|---|---|
| `package` | build and install into `{sandbox}` | Bash, Read/Grep/Glob, Write; cwd = sandbox |
| `script` | copy scripts and samples into `{sandbox}` | same as package |
| `web` | start the server in the background; stopped after the step | Playwright MCP, Bash limited to `curl`, Write |
| `library` | build the package; Proxy works in `{sandbox}/consumer` | Bash, Read/Grep/Glob, Write/Edit |
| `harness` | anything DevOps defines | Bash limited to `commands`, Write |
| `manual` | nothing | Write; its acceptance script goes to the human as a question |
