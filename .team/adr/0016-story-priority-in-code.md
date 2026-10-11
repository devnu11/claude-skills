# ADR-0016: Story priority lives in code

**Date:** 2026-10-11 (s40 done)  
**Status:** Accepted  
**Relates to:** ADR-0009 (routing in code), ADR-0014 (escalate repeated setbacks), s3 (sprints)

## Context

**Before s40:** The order in which stories were worked on was not explicit in code. The router picked the first movable story in `state.stories` (creation order), and the board showed each column in that same order. The order the PO and human agreed on (e.g., "sprint starts with s24 and s30, then s26, s27, s29") lived only in prose. When a held story sat at the top of its column with no mark, the board order made no sense.

**The live problem:** s29 ran before s30 (not the intended order). s9 (nothing in flight) jumped ahead of s29 (in flight at tests), and the board showed s27 at the top of the design column with no indication it was held.

## Decision

### 1. Explicit order in state (P1, P7)

`RunState.order: list[str]` (default `[]`) holds the PO's explicit list of story ids. It is saved in `state.json` and survives session boundaries. A legacy file without it loads with `[]`. Ids in the list that are done or unknown are harmless: the ranking ignores unknown ids and puts done stories last.

After any priority change (set, move, sprint), `state.order` holds the **full queue**: every unfinished story, explicitly placed. Stories opened later are unlisted until the PO places them, so they sort after listed ones (P2).

**Consequence:** The order is durable and explicit. Legacy state loads and works without changes.

### 2. The one ranking rule (P2, AC3, AC8)

**The rule:** `Priority.key(story) = (done, listed, not in_progress, natural(id))`

- `done`: done stories sort last (0 if done, 1 if not)
- `listed`: index in `order`, or `len(order)` when unlisted (so unlisted sort after listed)
- `in_progress`: 0 if past the first step or `previous` is set, else 1 (prefer in-flight stories when priority is equal)
- `natural(id)`: digit runs compare as numbers (s9 < s10 < s100)

An explicit position always beats in-progress. In-progress only breaks ties between unlisted stories.

The router picks the first story in `Priority.ranked(...)` that is `_movable`. Creation order plays no part.

**Consequence:** Every role follows the same rule. The rule is one function with tests.

### 3. PO tools: prioritise and move_story (P5, P6, AC2)

- **`prioritise(stories, reason)`:** Sets the queue to the listed ids in the order given, followed by every other unfinished story in its current queue order. Duplicates collapse (first wins). Refused (nothing changes) for empty list, unknown ids, or done ids.
- **`move_story(story, position, reason)`:** Takes the story out of the queue and puts it back at `position` (1 = next). Refused for unknown or done story, or a position outside 1 to queue length.
- **`start_sprint(goal, stories)`:** Treats its list as an order. After `begin_sprint`, applies prioritise with the sprint's ids (done ids skipped), so the sprint's stories come first in the order given.

**Consequence:** The PO explicitly agrees on an order, then sets it with one tool. Refusals are clear.

### 4. Hold semantics: held stories keep their place (P4, AC6)

Holds (hold, needs-manager, blocked, open questions) never change `order`. A held story keeps its position number and is skipped by the router until released. Once released via `continue_story`, it runs before later stories and its position never changes.

`_movable` skips held stories; `_repeat_work` (for escalated stories) also respects holds.

**Consequence:** The order shown makes sense. A held story's position tells you when it will run.

### 5. Comprehensive wait system (W1, W2, AC6)

`waits.wait(story, asking)` returns the first matching row of the `WAITS` table (data-driven, ordered):

| Reason | Applies when | Detail |
|--------|---|---|
| `needs the human` | blocked status | `_summary` |
| `manager` | needs_manager + repeated | first line of `repeated` |
| `round cap` | needs_manager | `"round {rounds}: the manager must rule"` |
| `questions` | hold contains "questions" | `_summary` |
| `held` | any hold | hold + `" · " + _summary` |
| `needs the human` | open questions asked | `""` |

The system covers every reason a story can't move. The board marks each with `⏸ <reason>` and `waits on: <on>`.

**Consequence:** The order displayed on the board makes sense. A customer, human, or role can see why a story isn't next.

### 6. Priority events (P9, AC5)

Every change in `prioritise`, `move_story`, and `start_sprint` emits one `priority` event with role `product-owner` and data:

```json
{
  "change": "set" | "move" | "sprint",
  "order": [...full queue after change...],
  "moves": [{"story", "from", "to"} for each story whose position changed (1-based)],
  "reason": str
}
```

The timeline shows:
- `set`: "order set" label, reason in body, moves in meta
- `move`: "#<from> → #<to>" label (or "#<n> (unchanged)" when move changes nothing)
- `sprint`: "sprint order" label

**Consequence:** Every decision is logged and visible on the timeline.

### 7. Snapshot and board (D1–D5)

- `run.order` is the queue (unfinished stories, ranked)
- `stories` are listed in ranking order
- Each story adds:
  - `position`: 1-based int in queue, or `null` when done
  - `in_progress`: bool
  - `hold`: str or `null` (the reason, e.g., "questions, needs the human")
  - `wait`: `{"reason", "on"}` or `null` (why it's not moving)

The board shows `#<position>` in the story id line and a wait pill `⏸ <reason>` when waiting.

**Consequence:** The snapshot and board are the single source of truth. The order shown is what runs next.

### 8. Documentation (X1, AC7)

`roles/product-owner.md` (developer role file) documents:
- Agree the order with the human, then set it with `prioritise` or `start_sprint`'s list order
- Move one story with `move_story`
- Give a reason (required for audit)
- The router follows the order
- A held story keeps its place

`protocol.md`, `SKILL.md`, the README row, and `customer/backlog-and-sprints.md` are updated.

**Consequence:** The contract is clear and auditable.

## Consistency rules

- **No implicit order:** Creation order never affects ranking. Explicit `order` is the only priority source.
- **Hold is a position, not a move:** Releasing a held story does not change its position.
- **Tie-breaking:** In-progress only breaks ties between unlisted stories. Explicit priority always wins.
- **Full queue on save:** After any change, `order` holds every unfinished story, in queue order.
- **Wait is read-only:** The wait reason is computed from the story's state; no separate field stores it.

## Tradeoffs

- **Unlisted stories sort after listed:** Stories opened during a sprint are unlisted until the PO places them. They don't interrupt the plan, but the PO must place them intentionally.
- **Position is 1-based on the board:** Matches user expectations; the rule computes 0-based (sorted list), then +1 for display.
- **One wait reason per story:** The first matching `WAITS` row wins. If a story has both "questions" and "held", "questions" fires. This keeps the UI simple.
- **No position groups:** Each listed story has its own position. In-progress only breaks ties among unlisted stories (future: group positions for equal-priority batches).

## References

- Story: `.team/stories/s40.md`
- Design: `agile-team/docs/design/s40.md` (rules P1–P10, W1–W2, D1–D5, X1, test checklist)
- Review: `.team/reviews/s40.md` (round 2 approved, D1 and T1 fixed)
