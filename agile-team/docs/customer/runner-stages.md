# See the runner's stages, and name your repo's own tools

Besides running the roles, the runner does work of its own: it runs the
gates, the quality checks, the checkout checks, prepares the Customer
Proxy's environment, lays out and tries the presentation, runs the sprint
boundary stages, and runs named tests for developers. Each of these is a
named stage, such as `gate.tests+coverage`, `checkout.guard` or
`boundary.push`.

## List them

```sh
agile-team tools
```

This prints one JSON object:

```json
{"built_in": [{"name": "env.prepare", "label": "env prepare",
               "description": "Prepare the acceptance environment …",
               "when": "before", "attach": "step"}, …],
 "repo": [{"name": "deploy.preview", "description": "Deploy the branch to the preview site",
           "command": "make preview", "label": "preview deploy"}]}
```

- `when` is `before` (the stage runs before a step or a sprint), `after`
  (after a step, or closing a sprint) or `during` (a runner tool working
  inside a developer's step).
- `attach` is what the stage belongs to: a `step`, a `story` or the sprint
  `boundary`.

## Sprint boundary stages

A sprint start runs `boundary.sync` (fetch, and report how far main moved;
nothing is rebased) and `boundary.check`. A sprint end runs, in order:

| Stage | What it does |
|---|---|
| `boundary.sync` | Fetch the target, record the team branch, add the sprint to the review stack |
| `boundary.check` | Run the full checks |
| `boundary.review` | Build the sprint's review branch on the target and check it |
| `boundary.push` | Push the sprint's review branch |
| `boundary.rebase` | Rebase the team branch onto the target (sprint end only) |
| `boundary.restack` | Bring every review PR up to date, bottom up: rebase, same tree, push, retarget |
| `boundary.ci-wait` | Wait for CI on every PR in the stack and read failing logs |

See [review-stack.md](review-stack.md) for what each one means for your
pull requests.

## See what each stage did

Every time a stage runs, the runner adds one `runner-stage` line to
`.team/run/events.jsonl`. It holds the stage name, the story and step it ran
for (or `null` outside a step), the command that failed or else the last one
it ran (secrets masked, at most 80 characters), its exit code, the start time
and the awake seconds (time asleep is left out). The dashboard does not draw
these lines yet.

## Name your repo's own tools

Add `[[tool]]` rows to `.agile-team.toml`. DevOps owns them, as it owns
`[toolchain]` and the acceptance environments (`[[environment]]`):

```toml
[[tool]]
name = "deploy.preview"
description = "Deploy the branch to the preview site"
command = "make preview"
label = "preview deploy"
```

- `name`: lowercase letters, digits, `-`, `_`, `+` and dots.
- `label` (optional): what the Flow chart's tool box says, in at most 24
  characters. Without it, the box shows the name. Each label appears once,
  and it can't be the label of a built-in stage (`agile-team tools` lists
  them).
- It must not be a built-in stage or start with a built-in namespace
  (`env`, `presentation`, `quality`, `checkout`, `gate`, `boundary`,
  `runner-tool`, `po`).
- `description` and `command` must not be empty, and each name appears once.

A broken row stops `config check`, `start` and `agile-team tools` with a
message naming every problem, for example:

```
[[tool]] 'gate.mine' clashes with a built-in name; pick another; [[tool]] name 'deploy.preview' is repeated
```

For now these rows only name your tools: the runner does not run their
commands.
