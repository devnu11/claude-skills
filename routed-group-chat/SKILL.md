---
name: routed-group-chat
description: Hold one shared-thread group chat between the human and several Claude roles (for example a leadership team of manager, product owner, liaison and customer proxy), where only the role the human @mentions answers, everyone sees the whole thread, and decisions are pinned. Use when the user says "group chat with", "talk to the leadership team", "ask the manager and the PO", "@manager", "@all", "get everyone's view", or wants several agents in one conversation without them talking over each other.
---

# routed-group-chat

One thread, many roles. The human addresses roles by @mention; code routes the
message, so only those roles answer, each with the whole thread in view.
Decisions and open questions are pinned in a log that summaries never touch.

```sh
GC="uv run --frozen --quiet --project ~/.claude/skills/routed-group-chat/runner group-chat"
```

`--frozen` runs the skill's tested `uv.lock` as it is; never drop it. Roster
format, addressing, markers and compaction are in `reference/protocol.md` next
to this file. Read it before writing a roster.

## Steps

1. **Pick the roster.** Use the team's own roster file if it has one;
   otherwise start from `examples/leadership.toml` here. Pick a chat directory
   (default `.group-chat/<team>` in the cwd) and state both to the human.
2. **Relay each message as written:**
   ```sh
   $GC --roster <roster.toml> --dir <chat dir> say "<the human's message>"
   ```
   Show the printed replies verbatim, one per role. Do not add your own reply
   unless the human addresses you.
3. **Addressing errors** exit 2 with the valid names. Show them; do not guess
   a recipient.
4. **On request:** `log` prints pinned decisions and open questions; `show`
   prints the summary and recent turns.

## Rules

- Routing is the human's: never add or change an @mention in their message.
- A role hands the floor on with `HANDOFF: @name`; the runner caps hops per
  message (`--max-handoffs`, default 2).
- The chat directory is the record. Do not edit `state.json` by hand.
