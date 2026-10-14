# routed-group-chat protocol

## Roster (TOML, validated on load)

```toml
team = "leadership"            # optional; shown to every role

[[role]]
name = "manager"               # the @mention: ^[a-z][a-z0-9-]{0,31}$
title = "Manager"              # optional; defaults to name
model = "sonnet"               # optional; defaults to the CLI's model
prompt = "You are ..."         # exactly one of prompt or prompt_file

[[role]]
name = "po"
prompt_file = "prompts/po.md"  # relative to the roster file
```

Rejected on load: no roles, a duplicate name, a reserved name (`all`,
`human`, `orchestrator`), a name that breaks the pattern, both or neither of
`prompt`/`prompt_file`, an empty or unreadable prompt. Roster order is the
order `@all` answers in.

## Addressing

| Message | Answered by |
|---|---|
| `@manager, timeline?` | manager |
| `@po @manager thoughts?` | po, then manager (each sees the other's reply) |
| `@all status?` | every role, roster order |
| `and the risks?` (no leading mention) | whoever was addressed last |
| first message has no mention, or `@cto` is unknown | refused, exit 2, nothing recorded |

Only mentions at the start of the message route. `ask @manager later` in the
middle of a sentence does not.

## Markers

Any line of any message (human or role) may carry one. A marker starts its
line, optionally after leading @mentions.

| Line | Effect |
|---|---|
| `DECISION: <text>` | pins decision `D<n>` |
| `QUESTION: <text>` | opens question `Q<n>` |
| `RESOLVED: Q<n>` | closes that question |
| `HANDOFF: @<name>` | (role replies only) next turn goes to `<name>` |

A handoff to yourself or an unknown name is ignored. Past `--max-handoffs` per
human message, the runner records an `@orchestrator` note instead.

## What each role sees

1. Its own prompt, then the chat rules and member list (system prompt).
2. The pinned decision log, in full.
3. The rolling summary of older turns.
4. The recent turns, verbatim.
5. The cue `Reply as @<name>.`

Each turn is one tool-free model call through the Agent SDK, on the Claude
Code login, with no user settings, tools or connectors loaded.

## Compaction

After each message, if the verbatim turns exceed `--recent-tokens` (default
6000, estimated at 4 characters per token), the oldest turns are folded into
the summary by one more model call, always keeping the last 4 turns. The
decision log is never folded.

## State

`<dir>/state.json`: turns, summary, last addressee and decision log, written
atomically after every message.
