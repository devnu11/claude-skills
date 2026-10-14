# routed-group-chat protocol

## Roster (TOML, validated on load)

```toml
team = "leadership"            # optional string; shown to every role

[[role]]
name = "manager"               # the @mention: [a-z][a-z0-9-]{0,31}
title = "Manager"              # optional string; defaults to name
model = "sonnet"               # optional string; defaults to the CLI's model
prompt = "You are ..."         # exactly one of prompt or prompt_file

[[role]]
name = "po"
prompt_file = "prompts/po.md"  # relative to the roster file
```

Rejected on load: no roles; an unknown key at the top or in a role (a typo
such as `modle` fails); a value of the wrong type; a duplicate name; a reserved
name (`all`, `human`, `orchestrator`); a name that breaks the pattern; both or
neither of `prompt`/`prompt_file`; an empty, unreadable or non-UTF-8 prompt.
Roster order is the order `@all` answers in. Every command validates the
roster, including `log` and `show`.

## Addressing

| Message | Answered by |
|---|---|
| `@manager, timeline?` | manager |
| `@po @manager thoughts?` | po, then manager (manager sees po's reply) |
| `@all status?` | every role, roster order |
| `@Manager hi` | manager (mentions are case-insensitive) |
| `and the risks?` (no leading mention) | whoever the human addressed last |
| first message has no mention, or `@cto` is unknown (even with `@all`) | refused, exit 2, nothing recorded |

Only mentions at the start of the message route; `ask @manager later` does
not. Sticky routing follows the human's last targets, not handoffs.

## Markers

A marker starts a line of any message (human or role), optionally after
leading @mentions, a `-`/`*` bullet or `**` bold. Markers are upper case. Lines
inside ```` ``` ```` fenced blocks never count, and a marker with blank text is
ignored.

| Line | Effect |
|---|---|
| `DECISION: <text>` | pins decision `D<n>` |
| `QUESTION: <text>` | opens question `Q<n>` |
| `RESOLVED: Q<n>[, Q<m>]` | closes every listed question; unknown ids do nothing |
| `HANDOFF: @<name>` | (role replies) next turn goes to `<name>` |

A handoff to the speaker, an unknown name or a role already waiting in this
message's queue is ignored. Past `--max-handoffs` (default 2) per human
message, the runner records an `@orchestrator` note instead.

Any member can write markers, so a role can pin a decision or close a
question. The log shows who wrote each entry; correct it in the chat
(`QUESTION:` again, or a new `DECISION:`).

## What each role sees

1. Its own prompt, then the chat rules and member list (system prompt).
2. The pinned decision log, in full.
3. The rolling summary of older turns.
4. The recent turns, each in a `<turn speaker="...">` block. Turn tags inside
   a message are escaped, so a reply cannot pose as another speaker.
5. The cue `Reply as @<name>.`

Each turn is one model call through the Agent SDK on the Claude Code login,
with no tools (`tools=[]`), no MCP servers or claude.ai connectors, no user or
project settings, and `max_turns=1`.

## Compaction

After each message, if the recent turns exceed `--recent-tokens` (default
6000, estimated at 4 characters per token), the oldest turns are folded into
the summary by one more model call, always keeping the last 4 turns. The
decision log is never folded. If that call fails, an `@orchestrator` note says
so, the turns stay verbatim and the next message tries again.

## State and failures

`<dir>/state.json` holds the turns, summary, last addressee and decision log.
It is saved after the human's message and after every reply, each time through
a temp file that is fsynced and renamed into place. A malformed `state.json`
exits 2 with its path.

A message holds `<dir>/lock` from start to finish; a second `say` on the same
chat exits 2 instead of interleaving. If a crash leaves the lock behind, delete
it.

If a model call fails, the replies that arrived are kept and printed, an
`@orchestrator` note records which role could not answer, the rest of that
message's queue is skipped, and the command exits 1.

## Commands and exit codes

```
group-chat --roster R --dir D [--max-handoffs N] [--recent-tokens N] say MESSAGE...
group-chat --roster R --dir D chat      # one message per stdin line; /quit ends
group-chat --roster R --dir D log       # pinned decisions and open questions
group-chat --roster R --dir D show      # summary, then recent turns
```

`chat` reports an error and keeps reading. Exit codes: 0 done, 1 a model call
failed, 2 a usage problem (bad roster, address, flag or state, or the chat is
locked).
