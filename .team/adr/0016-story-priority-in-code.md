# ADR-0016: Story priority lives in code

**Date:** 2026-10-11 (s40 done)  
**Status:** Accepted; amended by s51 (2026-10-12)  
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

**The rule:** `Priority.key(story) = (done, RANK[tier], listed, natural(id))`

- `done`: done stories sort last (0 if not done, 1 if done)
- `tier`: group the story is in (in progress, held, not started), ranked by `RANK`: in progress = 0, held = 1, not started = 2. Groups sort before listed order.
- `listed`: index in `order`, or `len(order)` when unlisted (so unlisted sort after listed)
- `natural(id)`: digit runs compare as numbers (s9 < s10 < s100)

**Vocabulary:**
- **started**: story has commits in the tree (`story.commit is not None`). The runner records its first commit, and every later commit is a fixup.
- **held**: `story.hold is not None`, or status is `BLOCKED` or `NEEDS_MANAGER`.
- **in progress**: started and not held. A step that ran but committed nothing is not started.
- **not started**: no commits, and not pulled ahead with a reason.
- **pulled**: the PO pulled a not-started story ahead of started ones. The ids are in `state.pulled`.

Stories with commits always go first (in progress), held started ones after those in progress, then stories not started. Within each group, the PO's order (listed index) decides.

The router picks the first story in `Priority.ranked(...)` that is `_movable`. Creation order plays no part.

**Consequence:** Every role follows the same rule. Commits in the tree beat explicit order, but the PO ranks within each group.

### 3. PO tools: prioritise and move_story (P5, P6, AC2)

- **`prioritise(ids, reason)`:** Sets the order to the listed ids in the order given, followed by every other unfinished story in its current order (the plan, with no groups). Duplicates collapse (first wins). When the listed ids include a not-started story before a started one, that story is **pulled ahead** and the tool is refused unless `reason.strip()` is non-empty. Refused (nothing changes) for empty list, unknown ids, or done ids.
- **`move_story(story, position, reason)`:** Takes the story out of the queue and puts it back at `position` (1 = next). When moving a not-started story before a started one, it is pulled ahead and the tool is refused unless `reason.strip()` is non-empty. Refused for unknown or done story, or a position outside 1 to queue length.
- **`start_sprint(goal, stories)`:** Treats its list as an order. After `begin_sprint`, applies prioritise with the sprint's ids (done ids skipped), so the sprint's stories come first in the order given. `start_sprint` never pulls not-started stories ahead, except when the upstream has a pending CI bug story (which is pulled and prioritized as a fix).

**Consequence:** The PO explicitly agrees on an order, then sets it with one tool. Pulls require a reason to prevent accidental disorder. Refusals are clear.

### 4. Hold semantics: held stories keep their place in order (P4, AC6)

Holds (hold, needs-manager, blocked, open questions) never change `order` (the plan of unfinished stories). A held story keeps its place in that list. While held, it ranks after all in-progress stories and before not-started ones, so its #position on the board changes. Once released via `continue_story`, it ranks back at its place among started stories.

Every change (set, move, sprint) builds the new `order` from the old `order` (the plan, with no groups), never from the queue (with groups). So reordering other stories while a story is held does not move its place in `order`.

`_movable` skips held stories; `_repeat_work` (for escalated stories) also respects holds.

**Consequence:** The order shown makes sense. A held story's place in the plan is remembered; its #position tells you when it will run once released.

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
  "reason": str,
  "pulled": [list of not-started story ids pulled ahead of started ones, empty if none]
}
```

The timeline shows:
- `set`: "order set" label, reason in body, moves in meta, pulled in meta when non-empty
- `move`: "#<from> → #<to>" label (or "#<n> (unchanged)" when move changes nothing), pulled in meta when non-empty
- `sprint`: "sprint order" label, pulled in meta when non-empty

**Consequence:** Every decision is logged and visible on the timeline. Pulls are recorded for audit.

### 7. Snapshot and board (D1–D5)

- `run.order` is the queue (unfinished stories, ranked)
- `stories` are listed in ranking order
- Each story adds:
  - `position`: 1-based int in queue, or `null` when done
  - `tier`: the group the story is in (`"in progress"`, `"held"`, or `"not started"`), or `null` when done
  - `hold`: str or `null` (the reason, e.g., "questions, needs the human")
  - `wait`: `{"reason", "on"}` or `null` (why it's not moving)

The board shows `#<position>` in the story id line and a wait pill `⏸ <reason>` when waiting.

**Consequence:** The snapshot and board are the single source of truth. The order shown is what runs next, grouped by tier.

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
- **Hold is a position, not a move:** Releasing a held story does not change its position in the plan.
- **Groups first:** Stories are ranked by tier (in progress, held, not started) before the PO's listed order applies within each group.
- **Full queue on save:** After any change, `order` holds every unfinished story, in plan order (no groups).
- **Wait is read-only:** The wait reason is computed from the story's state; no separate field stores it.

## Tradeoffs

- **Unlisted stories sort after listed:** Stories opened during a sprint are unlisted until the PO places them. They don't interrupt the plan, but the PO must place them intentionally.
- **Position is 1-based on the board:** Matches user expectations; the rule computes 0-based (sorted list), then +1 for display.
- **One wait reason per story:** The first matching `WAITS` row wins. If a story has both "questions" and "held", "questions" fires. This keeps the UI simple.
- **Groups are fixed:** A not-started story always ranks after started ones unless the PO explicitly pulls it ahead with a reason. A pull does not change the ranking function; it marks the story as moved intentionally.

## References

- Story: `.team/stories/s40.md`
- Design: `agile-team/docs/design/s40.md` (rules P1–P10, W1–W2, D1–D5, X1, test checklist)
- Review: `.team/reviews/s40.md` (round 2 approved, D1 and T1 fixed)

## Amended by s122 (2026-10-14)

`add_to_sprint(stories, reason)` is a fourth source of PO reorders. After
adding the stories to the current sprint, it applies `prioritise`'s placement
(the listed ids first, in the order given, `with_first`) with no pull, as one
`Change.SPRINT` reorder that carries the PO's reason. Started stories still
rank first. See ADR-0055 and `agile-team/docs/design/s122.md`.
