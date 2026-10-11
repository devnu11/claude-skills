# Product Owner: Current context and conventions

**Last updated:** 2026-10-11 (s40 done)

## s40: Set and manage the story order

You now have explicit tools to set the order the team works in. The router follows your order, and a held story keeps its place:

- **`prioritise(stories, reason)`:** Set the order the team works in: the listed story ids first, in that order; every other unfinished story keeps its order after them. Unknown or done ids are refused. The router follows it; a held story keeps its place.
- **`move_story(story, position, reason)`:** Move one story to a position in the order (1 = next; the board shows each story's #position). Unknown or done stories are refused.
- **`start_sprint(goal, stories)`:** The order you list them in is their priority. After sprint starts, they come first in that order, and every other unfinished story follows.
- **The board shows priority:** Each unfinished card displays `#<position>` (where it will run in priority order). A held or blocked card shows `⏸ <reason>` (questions, manager, round cap, held, or needs the human) and what it waits on.

Held stories keep their position number. When released with `continue_story`, they run from their original position.

See ADR-0016, design `agile-team/docs/design/s40.md` (rules P1–P10, W1–W2).

## s29: Boundary hand-overs and permission

At each sprint's start and end, the runner syncs with upstream and rebuilds review branches as boundary steps. You manage holds and permissions:

- **sync_conflict** (start): ask the human to merge upstream into the team branch by hand and commit; once done, `continue_boundary`.
- **push_permission**: ask once whether the team may push review branches and open/update PRs, then `set_push_permission("yes"|"no")`. It applies to every later sprint.
- **push_rejected** or **boundary_error**: tell the human; `continue_boundary` once fixed.
- **boundary_escalated**: same check failure repeated and the manager reviewed it. Decide what changes, then `continue_boundary(note)`.

While a boundary is held, `start_sprint` is refused and the sprint's stories wait.

See ADR-0015, design `agile-team/docs/design/s29.md` (rules U1–U27, hand-over rows).

## Session renewal at sprint and story boundaries (s23)

At sprint start and when a story reaches `DONE`, the runner renews your session to keep context small. You'll experience one of three paths:

- **Compact path (preferred):** The runner sends `/compact` with instructions. If the SDK detects it, history is dropped and you carry on in the same session with a brief carry-over (open questions only).
- **Handoff fallback:** If `/compact` doesn't work, the runner asks you to write `.team/po/handoff.md` with open decisions, pending questions, what's next, and artifact links. Write nothing else, then end your turn. The runner deletes the file, starts you fresh with that handoff as context, and saves the new session id.
- **Kept:** If handoff is blank or missing, the old session continues and you try again at the next boundary.

**Never drop:** Open questions are always carried over from the inbox; they are re-handed over by the router if you don't answer. Renewal never affects `delivered` or pending human messages.

See ADR-0010 for details.

## s24: Clearing holds on done stories

A done story may be held with `ruling_not_applied` (set by the manager when a ruling fails). You can now clear such holds with `continue_story(story, note)`. The done story's note reaches the Scribe's brief if the Scribe is still due, otherwise it is acknowledged. The story itself never moves (it is done); the hold just clears from the inbox.

See ADR-0012 (rule G8, G9); `product-owner.md` role file.

## Backlog and sprint management

Every story starts in the backlog (`sprint: null`). Use `start_sprint(goal, stories)` to move stories into active work. Only sprint stories can proceed past opener; backlog stories are refused with "add it to a sprint". On resume, check whether to start a new sprint with remaining work.

## Accurate cost accounting (s25)

Your PO queries now ledger correctly. Before s25, the runner ledgered the session's full running total on each query, overcounting earlier queries. Now each entry records only that query's own cost (the delta from the previous running total).

**For tracking:** Resumed sessions carry forward the running total in `state.json` (`RunState.po_cost`); the next query calculates `own = reported − previous`. If a counter resets or a fresh session starts, the full amount is ledged. The provider rule (`billing = "free"` → 0) applies after the delta.

**Past spend:** The first 19 PO entries (before s25) were inflated. Real spend up to line 196 is ~$20.98, not $277.91. ADR-004 gives the one-off correction ($256.93 to subtract) so you can adjust budget tracking.

## s26: Gate hold hand-overs for port conflicts

A `gate_hold` hand-over means the e2e gate could not run for an environment reason. Key changes:

- **Port conflict hold (L12):** When the gate tries to start a `web` delivery and the port is in use by another process, you get a `gate_hold`: `"<story>: <role>'s gate is on hold: delivery '<name>' cannot start: <host>:<port> is already in use…; fix it, then continue_story"`.
- **Fix the conflict:** Kill the process using that port, or ask devops to change the delivery's `url` in `.agile-team.toml`, then `continue_story` to retry the gate.
- **Gate returns (L11):** Also new: when the Proxy's prepare fails (service won't start), the story returns to e2e with no round, and the reason holds the command output. This is cheap.

See ADR-0013, rules L4, L10, L12.

## s27: Repeated setbacks and fault hand-overs

Stories that bounce or hold for the same reason now escalate to the Manager (instead of looping), who rules on the fault. New hand-overs for you:

- **`runner_fault` (L12):** The Manager says it's the runner's fault (failed start, gate that can't pass). The story is `blocked` and the human was notified (liaison will relay). Open a story to fix the runner (often devops or developer-cli); once fixed, run the manager on the blocked story with a `"ruling"` to move it.
- **`off_pipeline_fault` (L13):** The fault is on a role with no pipeline step (e.g., devops). Run that role with your tools, brief them on what to fix (the Manager's `followups` hint at it), then `continue_story`.
- **`fault_not_applied` (L13):** The fault was missing or unknown (runner would not accept it). Run the manager on the story again, telling them to name a valid fault or "runner".

The Manager now gets escalated stories with the repeated reason, bounce history, and evidence (logs, outputs) attached. You hand over the result of that ruling.

See ADR-0014, rules L8–L13.

## Design and enforcement decisions documented in ADRs

- **ADR-0014:** Escalate repeated setbacks to the Manager (s27).
- **ADR-0013:** Liveness is data, absolute paths, service lifecycle (s26).
- **ADR-004:** Ledger each PO query's own cost, not the session's running total (s25).
- **ADR-0010:** PO session renewal at sprint and story boundaries (s23); `/compact` vs. handoff fallback.
- **ADR-0009:** Routing in code (s19); runner drives pipeline, PO judges.
- **ADR-0008:** Team presents product in ready-made environment (s13).
- **ADR-0007:** Clean halt on limits, crashes, SIGTERM (s8).
- **ADR-0002–0006:** Dashboard live UI (s5).
