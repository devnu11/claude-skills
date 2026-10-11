# When the runner stops on its own

The team may stop before its work is done. Three causes are handled:

- your Claude session or usage limit runs out;
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
