# ADR-0063: A PO turn names the stories its tool calls touched

Story: s113. Design: `agile-team/docs/design/s113.md`.

## Context

`po-turn` events carry the PO's `model_s`, `tool_s` and `waiting_s` but no
story, so the Flow chart cannot show the PO's time in Story scope. One PO
turn can work on several stories (a hand-over, a `start_sprint`, an
`ask_user` on two stories), so the event's single `story` field cannot hold
it.

## Decision

- Each `po-turn` event's `data` gets `"stories"`: the ids its PO tool calls
  named, deduplicated, first named first; `[]` when none. The event's own
  `story` stays `null`.
- A call names the values of its `story` and `stories` arguments, and
  `open_story` its `id` (the `STORY_ARGS` table in `po_tools.py`). The story
  is noted when the tool is called, before it runs, so refused calls count.
  Hand-over stories that no tool names do not count.
- `mcp_server` wraps every PO tool with `Tools.noted(name)`, which notes the
  stories into the turn's `Touched` collector. `PoRun` builds the turn's
  `Tools` itself (`plan_for(tools, turn)`) so it can read the collector when
  it emits the event.
- On the dashboard, a turn counts in the Story scope of every story it
  names, in full. The PO's box marks such time `shared turns`. Sprint and
  Run scope are unchanged (Sprint still takes the turns inside the sprint's
  window).

## Consequences

- The field is additive; events from before s113 read as `[]` and keep
  showing `—` in Story scope.
- Adding the PO's Story-scope times over several stories counts a shared
  turn more than once; the `shared turns` mark says so. No share-out by
  fraction is attempted.
- A new PO tool that names a story under another key must be added to
  `STORY_ARGS`.
