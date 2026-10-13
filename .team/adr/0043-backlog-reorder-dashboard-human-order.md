# ADR-0043: Backlog reorder requests on the dashboard; human order binds the PO

**Decision:** Add a Backlog tab to the dashboard where the human reads every outstanding story and reorders the backlog outside the current sprint. Reorder requests are queued as files, applied between steps by the router through the PO's code, and recorded as `priority` events with source `"human (dashboard)"`. The human's backlog order cannot be changed by the PO without a stated reason. Write access is gated by localhost and a random token.

**Date:** 2026-10-13  
**Status:** Accepted  
**Affected:** Backlog workflow, dashboard, PO tools, priority rules, reorder requests

## Context

The human has been steering the backlog through `prioritise` and `move_story` requests to the PO. Reading all outstanding stories to make those decisions requires separate reports; the PO is not interactive. Adding a Backlog tab to the dashboard would let the human read stories, reorder them directly, and see the result on their next page reload, making backlog steering faster and more visual.

However, reordering is a decision with consequences: the PO must still respect priorities set by other rules (started stories first, held stories hold), and the human's order must be auditable (who moved what, when, why). The token security model must extend write access to the dashboard without weakening it.

## Decision

### The Backlog tab and request flow

**D1: Stateless request queueing.** The dashboard remains stateless. When the human reorders a story, the browser POSTs a request to `/api/reorder` carrying the story id, target backlog position, and the current order version. The server writes the request as a JSON file in `.team/run/reorders/rN.json` and replies 202 (accepted for processing), never modifying `state.json`. Between steps, before the PO picks work, the router calls `desk.apply()` to process pending requests.

**D2: Order version and staleness.** The snapshot includes `order_version`, a short hash of the current queue and backlog. When the human reorders, they send the version they saw. Before applying a request, the PO checks: if the version doesn't match, the request is marked `STALE`, the order is unchanged, and the human is told to reload the page. This prevents lost updates when the order changes (due to sprints, holds, or other reorders) between the human's view and the request's arrival.

**D3: Applied between steps.** The request does not apply immediately. Between steps, the router's `_tick()` calls `desk.apply()` right after the checkout check, before picking work. Applying a request does not stop the router and does not trigger a hand-over by itself; it updates the state and emits an event, so the human sees the change in the next snapshot (via SSE) and the PO is told at the next real hand-over.

**D4: One request at a time.** The human can queue only one reorder request; while one is pending, the Backlog tab disables the handles. This simplifies the implementation and keeps the UI clear about what's in flight. If the human reloads the page before the runner applies a request, the request becomes stale on the next order change.

### The human's order rule (D5–D7)

**D5: Human order as a record.** When a request is applied, the new backlog order is recorded in `state.human_order`, which persists across steps. This is the human's declared order for the backlog.

**D6: Human order binds the PO.** The PO cannot change the human's backlog order without a stated reason. When a `prioritise` or `move_story` tool call would change the order of stories that the human has moved (comparing the guarded projection before and after), the tool is refused unless the `reason` parameter is non-blank and is recorded in the event. This rule applies only to stories the human reordered; PO changes to other stories (e.g., adding a new story to the backlog) do not require a reason.

**D7: No PO change to human order tracking.** The `human_order` list is never modified by the PO, even when the PO changes the queue. Empty `human_order` (the human has never reordered) guards nothing. A `start_sprint` that moves stories between sprint and backlog does not trigger the human-order rule.

### Write security (D8–D10)

**D8: Localhost and token required.** The `/api/reorder` endpoint accepts POST requests only from `127.0.0.1` or `::1`. Additionally, every request must carry an `X-Agile-Team-Token` header matching the token `app.token`. Both checks happen before the body is read, so an invalid request costs no parsing. Both 403 (network boundary) and token mismatch are reported the same way, so the attacker sees no difference.

**D9: Random token by default, fixed for presentations.** When the dashboard starts, it generates a random token (`secrets.token_urlsafe(16)`) and prints it in the local URL shown to the human: `dashboard: http://localhost:<port>/?token=<token>`. The browser extracts the token from the URL and sends it in every reorder request. For presentation workspaces (e.g., demos), the config file can set a fixed token (`[dashboard] token = "..."`) so the link is predictable; the fixed token gets the same treatment as a random one (printed, never logged, only in the URL).

**D10: Token never leaks.** The token is absent from the snapshot, events, ledger, crash log, request files, and log output. It appears only in the printed URL and the browser's request header.

### Event source tracking (D11–D12)

**D11: Source field on priority events.** Every `priority` event now carries a `source` field: `"product-owner"` when the PO's `prioritise` or `move_story` tool made the change, `"human (dashboard)"` when a human reorder request caused it. This audit trail shows who ordered what.

**D12: Event role.** When `source` is `"human (dashboard)"`, the event's `role` field is `None` (not `"product-owner"`). This distinguishes human decisions from PO decisions in reports and dashboards.

### Reorder request refusals (D13–D14)

**D13: Refusal checks in order.** Before applying a request, the router checks (in order):
1. Is the version stale? → `STALE`
2. Is the story unknown or done? → order refusal (same as PO tools)
3. Is the story in the current sprint? (Only backlog stories can be moved.) → `SPRINT_STORY`
4. Is the position a valid backlog place (1 to backlog length)? → `BAD_PLACE`
5. Would the move be refused by the existing move rules? → move refusal

**D14: Refusal as a record.** When a request is refused, the refusal text (e.g., `"STALE"`, `"SPRINT_STORY"`) is recorded in `state.reorders[request_id]`, replacing the `"pending"` marker. The order is unchanged; no event is emitted. The human sees the refusal and its reason on the Backlog tab.

### File serving by story id (D15–D16)

**D15: Strict file paths.** The dashboard serves story files through `/api/file?kind=K&id=I`, where kind is one of `story`, `design`, `review`, `acceptance` and id is a story id. The server builds the path only from a whitelist of folders (no aggregation, no templates, no user input in the path), checks that the id matches the story pattern (`[A-Za-z][A-Za-z0-9_-]{0,63}`), and verifies the file exists and is a regular file. Any other path, unknown kind, bad id, missing file, or directory returns 404. This prevents directory listing and path traversal.

**D16: Story id as the only key.** Files are served by story id alone, never by path. The story must exist in `state.json`. This ensures the file route cannot be used to read files outside the story/design/review/acceptance folders, and the set of files changes only when stories change.

### Implementation and data

**D17: New modules and state fields.**
- New `backlog.py` module (pure, no I/O): `View` class, `order_version()` function, `label()`, refusal functions.
- New `reorders.py` module: request file I/O, `Requests.queue()`, `Desk.apply()` for applying requests and updating state.
- New `story_files.py` module in dashboard: folder whitelist, file path builder, existence checks.
- Three new `state.json` fields: `human_order`, `reorders` (id → status/reason), `reorders_told` (lines to hand over).
- `priority.py` gains `Source` enum and source field on `Reorder`.
- `dispatch.py` gains `Runtime.reorder()` method and `Desk` instance in `router.py`.

**D18: Snapshot updates.**
- Add `order_version` and `backlog` to the `run` section.
- Add `label` and new fields to each story.
- Add a top-level `reorders` array (last 20 requests with status and reason).
- Add `source` field to all `priority` events (existing and new).

## Consequences

**Human can steer backlog interactively** on the dashboard without asking for `prioritise` requests. The human reads stories, sees the current backlog order, and reorders by dragging or buttons. The change applies at the next step boundary.

**Order is auditable.** The snapshot shows request status and reason. Events carry the source (human or PO). `human_order` records what the human set. The PO's reason for overriding the human's order is logged.

**Data contract extends.** The snapshot fixture gains `order_version`, `backlog`, `label`, `commits`, `developer`, `disputes`, `files` per story, and `reorders` at the top level. The fixture's priority events now include `source`.

**New module boundaries.** Pure `backlog.py` and `reorders.py` modules keep I/O in `story_files.py`. Request flow is now: browser → server (POST) → file queue → router (apply) → PO hand-over.

**Write access model changes slightly.** The dashboard is still read-only to the world; writes need localhost and a token. The token is random by default but can be fixed for presentations, matching how other parameters (like a demo script) are configured.

## Related decisions

- **ADR-0027 (s4):** Dashboard snapshot as raw data contract. This decision adds new snapshot fields but keeps the contract pure; no aggregation.
- **ADR-0015 (s29):** Boundary steps (sync, push, review). The reorder request is applied by the router, not the boundary, but between steps like other asynchronous changes.
- **ADR-0016 (s51):** Story priority ranking. Reorder requests use the same ranking logic and refusal checks as PO tools.
