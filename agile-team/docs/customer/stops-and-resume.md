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

If a team member was cut off halfway through a step, the working tree may
have uncommitted changes. `start` refuses a dirty tree, so decide what to do
with them first (`git status` shows them).
