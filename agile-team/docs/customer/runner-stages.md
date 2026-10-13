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
{"built_in": [{"name": "env.prepare", "description": "Prepare the acceptance environment …",
               "when": "before", "attach": "step"}, …],
 "repo": [{"name": "deploy.preview", "description": "Deploy the branch to the preview site",
           "command": "make preview"}]}
```

- `when` is `before` (the stage runs before a step or a sprint), `after`
  (after a step, or closing a sprint) or `during` (a runner tool working
  inside a developer's step).
- `attach` is what the stage belongs to: a `step`, a `story` or the sprint
  `boundary`.

## See what each stage did

Every time a stage runs, the runner adds one `runner-stage` line to
`.team/run/events.jsonl`. It holds the stage name, the story and step it ran
for (or `null` outside a step), the command that failed or else the last one
it ran (secrets masked, at most 80 characters), its exit code, the start time
and the awake seconds (time asleep is left out). The dashboard does not draw
these lines yet.

## Name your repo's own tools

Add `[[tool]]` rows to `.agile-team.toml`. DevOps owns them, as it owns
`[toolchain]` and `[[delivery]]`:

```toml
[[tool]]
name = "deploy.preview"
description = "Deploy the branch to the preview site"
command = "make preview"
```

- `name`: lowercase letters, digits, `-`, `_`, `+` and dots.
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
