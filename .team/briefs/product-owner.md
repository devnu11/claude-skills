# Product Owner: Current context and conventions

**Last updated:** 2026-10-11 (s4 documented, s58 done)

## s4: Dashboard backend – snapshot builder and read-only server

The dashboard backend is now live. When you run `agile-team dashboard [--host HOST] [--port 8765] [--no-open]`, it:
- Binds to the given host:port (default `0.0.0.0:8765`; Windows defaults to `127.0.0.1`).
- Prints the URL with the **bound** port (so `--port 0` shows the real port).
- Opens the browser (unless `--no-open`) to view the live dashboard.
- Serves `index.html` on `/`, the snapshot JSON on `/api/snapshot`, and an SSE stream on `/api/stream` that pushes updates every second if files change.

The snapshot builder reads only explicit files (state, events, ledger, messages, requirements) and returns raw data. The browser derives all views (board, flow, tokens, questions) in JavaScript. The fixture is the API contract. No new runtime dependencies. Covered at 99.68% (14 e2e tests); ruff clean. See ADR-0027, design `agile-team/docs/architecture.md` § "s4: Dashboard backend".

## Recent decisions

## s58: Customer Proxy sandbox now reaches local services

All five ACs pass: (1) `network.allowLocalBinding` set only for service deliveries (web, dashboard kinds with `Start.BACKGROUND`). (2) E2E test on macOS curls a live service from inside the sandbox: 200 with the setting, exit 7 without (proving sandbox active). (3) Docstring updated; says what is verified (macOS) and what is not (Linux). (4) Service lifecycle stated in docs: trial stops by design, Proxy gets fresh from `plan()`. (5) Docs moved with behaviour. E2E test skipped off macOS with stated reason; unit test pins the setting's presence. Coverage ≥95%, ruff clean. See design `agile-team/docs/design/s58.md`, ADR-0026. Customer Proxy acceptance step no longer bounces on "connection refused."

## s47: Status shows what the run waits on; halt notes include it

When you post a question and your turn ends, the run waits on the answer. While waiting, `agile-team status` shows `status_reason: "waiting on answers: s40 waits on m42; the run waits on m43"`. The router polls every 5 seconds (unchanged); when the answer arrives, the PO gets it as a hand-over. If you halt the run while questions are open, the halt note includes the waiting context so you know what to answer. No change to wake logic or polling. See ADR-0025, design `agile-team/docs/design/s47.md`.

## s46: Advance ruling moves stories forward; code commits tracked

You can now run the Manager with `"ruling": "advance"` to move a story one step forward, clearing its loops. This solves the problem of a story stuck at a gate no role can satisfy. The Manager sees whether the story's implementation is in the branch (`repeated_setback.code`), so they can decide whether to rule on it. Handoffs may carry `"ruling_reason": "<text>"` (string); it defaults to the summary and is logged in the `ruling` event. When calling the Manager on a stuck story, provide the reason for your ruling. See ADR-0024, design `agile-team/docs/design/s46.md` (A1–A4).

## s45: Manager crash fixed; blocked stories cannot be released; faults on any story

Manager step crash fixed (emit signature), crash log now captures all exceptions, fault rulings work on any story (not just repeated ones), and `continue_story` is blocked for blocked stories.

**Your changes:**
- **Blocked-story release blocked (B1):** `continue_story` on a blocked story is now refused. Reason: the story cannot move while blocked (would stall). Run the manager on it with a `ruling` or `fault` to move it.
- **Faults on any story (M1):** Manager can name a fault on any story: repeated bounces, escalations from round cap, runner faults from unit-tester escalate. The fault path taken when `handoff.fault` is named OR `story.repeated` is set.
- **Report shows applied/unapplied (M6):** Every fault/ruling appears in the report with `applied: true|false` and `why` when false. New hand-over: `fault_not_applied` for missing/unknown faults.
- **Crash log now has tracebacks (C1):** Any role-step exception is logged to `.team/run/crash.log` exactly once, with traceback. Previous crashes without logs can now be diagnosed.

See ADR-0023, design `agile-team/docs/design/s45.md` (rules B1, M1, M6, C1).

## s38: Budget correction and the ceiling halts the run

The runner now uses the corrected PO ledger (s25's actual costs, not inflated running totals) everywhere. The budget is a hard ceiling: when spend reaches it, the run halts cleanly and only you can raise it.

- **Corrected everywhere:** `agile-team status`, the dashboard, `budget_status`, and the Manager all show the true spend (PO overcount removed). In this repo, spend dropped by ~$1,025 at once.
- **The ceiling halts the run:** When spend reaches `budget_usd`, the runner halts with status `blocked` and a reason naming the spend and ceiling. One liaison note. The run stays `blocked` until you raise it.
- **Raise and resume:** Edit `.agile-team.toml`, raise `team.budget_usd`, commit it (required: the tree must be clean), then `agile-team start --resume`. Config reloads and the run resumes if the new budget allows it.
- **If you resume without raising:** The run halts again at once with zero queries (no new spend).

See ADR-007, design `agile-team/docs/design/s38.md`.

## s9: Interrupted steps and recovery on resume

When a step is cut short (error, limit, SIGTERM, kill -9), the runner saves its edits and offers them to the next step. On resume, your first prompt may hold an **Interrupted steps** section listing them. Key changes:

- **On resume:** Your opening prompt may include `## Interrupted steps` with each cut-off step's role, story, brief, and `git cherry-pick -n <sha>` line. Run each step to handle it. For story steps, the runner offers the sha in the next brief on that story.
- **After interrupt, before you run:** The status is `interrupted` (not `running`), and `agile-team status` shows `in_flight` (the step that was running) and `interrupted` (the list of cuts). Resume with `start --resume`, or if you need context, read `state.json`.
- **Recovery after kill -9 or power loss:** `start --resume` detects a dead pid and saves the partial edits (cause `killed`), adding them to the interrupted section. The stderr line tells you the sha was saved.
- **Note for stale pid:** If `runner.pid` points to a dead process from an old run, `status` ignores it (shows `interrupted` if status is `running`) or re-runs `start` clears it.

See ADR-0017, design `agile-team/docs/design/s9.md` (rules I1–I15, exact strings).

## s40: Set and manage the story order

You now have explicit tools to set the order the team works in. The router follows your order, and a held story keeps its place:

- **`prioritise(stories, reason)`:** Set the order the team works in: the listed story ids first, in that order; every other unfinished story keeps its order after them. Unknown or done ids are refused. The router follows it; a held story keeps its place.
- **`move_story(story, position, reason)`:** Move one story to a position in the order (1 = next; the board shows each story's #position). Unknown or done stories are refused.
- **`start_sprint(goal, stories)`:** The order you list them in is their priority. After sprint starts, they come first in that order, and every other unfinished story follows.
- **The board shows priority:** Each unfinished card displays `#<position>` (where it will run in priority order). A held or blocked card shows `⏸ <reason>` (questions, manager, round cap, held, or needs the human) and what it waits on.

Held stories keep their position number. When released with `continue_story`, they run from their original position.

See ADR-0016, design `agile-team/docs/design/s40.md` (rules P1–P10, W1–W2).

## s11: Ruling not applied hand-over and test disputes

Rulings now work at any step. If a ruling cannot apply (no story, or story is done), the report shows why with no change to the story. New hand-over: **`ruling_not_applied`**: run the manager on the story it meant, or drop it.

Developers can hand off disputes to send stories back to `tests` without bouncing. The tester fixes the test or confirms it (which escalates to architect). Free disputes bounded: first `round_cap` per story cost no round. Dispute details (test id, rule, reason) appear in the brief at every step while open. See ADR-0018, design `agile-team/docs/design/s11.md`.

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
