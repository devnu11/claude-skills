# When the runner stops on its own

The team may stop before its work is done. Four causes are handled:

- your Claude session or usage limit runs out;
- the team's spend reaches your budget (`team.budget_usd`);
- the runner hits an unexpected error;
- you run `agile-team stop --now`.

In every case the runner stops cleanly. It does not leave a raw traceback as
its only output.

## What you see

`agile-team start` prints **one** line on stderr that says what happened and
what to do next, then exits with a code you can script against:

```text
agile-team start: session limit, resets 2:20pm (America/Edmonton); run `agile-team start --resume` after the reset
```

| Exit | Why | `status` |
|---|---|---|
| 75 | session or usage limit | `blocked` |
| 77 | spend reached the budget | `blocked` |
| 70 | unexpected error | `failed` |
| 143 | `stop --now` | `stopped` |

`agile-team status` shows the same reason next to the status:

```json
{
  "status": "blocked",
  "status_reason": "session limit, resets 2:20pm (America/Edmonton)",
  "sprint": 2,
  "...": "..."
}
```

The liaison also gets a note in `.team/run/outbox.jsonl` (kind `blocked`,
`failed` or `stopped`) with the same text, so your Claude session tells you
without being asked.

The reset time comes word for word from Claude's own message. The runner
does not wait for the reset or restart by itself.

## When the budget is reached

`team.budget_usd` in `.agile-team.toml` is a ceiling. The runner checks it
after every step and when it starts, and halts once spend is at or over it:

```text
agile-team start: budget reached: spent $50.12 of $50.00; raise team.budget_usd in .agile-team.toml and commit it, then run `agile-team start --resume`
```

A step that is already running finishes and is kept, so spend can pass the
ceiling by about one step. To carry on, raise `budget_usd` (by as much or as
little as you like), commit the change, and run `agile-team start --resume`:

```sh
git commit -m "Raise the team budget" .agile-team.toml
agile-team start --resume
```

The commit is needed because `.agile-team.toml` is tracked and the runner
only starts from a clean working tree. If you skip it, `start --resume`
stops with `working tree is dirty (.agile-team.toml); commit or stash first`
and nothing runs. If you resume
without raising it, the runner stops again at once and spends nothing.
`agile-team status` shows the spend under `budget`. `po_overcount_usd` there
is the Product Owner's early overcount (from before the s25 fix), which is
already taken off `spent_usd`.

## After an error

The full traceback is appended to `.team/run/crash.log`. Each entry starts
with a line like `--- 2026-10-08 14:02:11 RuntimeError`.

## Carrying on

Run `agile-team start --resume` (after the reset, for a limit). The Product
Owner picks up from the saved state. After a limit, it continues the very
session that was cut off. The old status and reason are cleared as soon as
the run starts.

## Work cut off mid-step is kept

If a team member was cut off halfway through a step, the runner keeps its
edits. It commits them as `chore(team): interrupted step by <role> on
<story>` and reverts that commit at once, so your working tree stays clean.
The note names the commit:

```text
session limit, resets 2:20pm (America/Edmonton); run `agile-team start --resume` after the reset; developer-cli on s7's edits are saved in 3f2a9c1… (git cherry-pick -n 3f2a9c1…)
```

When the team picks the story up again, the next team member is told about
that commit and can bring the work back with `git cherry-pick -n <sha>`
instead of starting over. You don't need to stash anything.

## If the runner was killed

If the runner process died without a clean stop (`kill -9`, a closed
terminal, a power loss), `agile-team status` says `interrupted` with
`"running": false`. It never claims `running` when no process is behind it.
`agile-team start --resume` saves whatever the cut-off step left in the tree,
in the same way, before it checks for a clean tree:

```text
agile-team start: the last run was killed; developer-cli on s7's edits are saved in 3f2a9c1… (reverted)
```

A dirty tree that no interrupted run left behind is still refused. Commit
or stash your own changes first.
