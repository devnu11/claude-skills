# ADR-0045: Liaison opinions on stories via append-only JSONL files

**Decision:** The liaison's opinions on backlog stories are recorded as a view over three append-only JSONL files, each with one writer: the CLI records opinions, the server records acts (dismiss/apply), and the liaison records review closure. The dashboard renders opinions as badges and a filterable list on the Backlog tab, allows the human to dismiss or apply them, and sends applied non-move opinions to the PO as thread posts.

**Date:** 2026-10-13  
**Status:** Accepted  
**Affected:** Dashboard, CLI, router, PO tools, snapshot, Backlog workflow, liaison interaction

## Context

The liaison sees the backlog and can suggest changes (move, reorder, scope, fold, close, ask). The human needs to see these suggestions on the dashboard without opening a separate request flow. Opinions are not critical (the PO drives priorities); they are interactive suggestions the human can act on (dismiss) or escalate (apply). The liaison may record opinions unasked, or respond to a request on the dashboard.

The challenge is to record opinions, review requests, and acts without creating a new data store or blocking the run. The CLI (liaison) and server (human) both need to write; the run may be stopped while the human reviews.

## Decision

### Shape: opinions as a view over three files

**O1: Three single-writer JSONL files.** Following the s84 pattern (story threads), opinions data lives in three append-only JSONL files under `liaison/`:
1. **`opinions.jsonl`:** Appended by `agile-team opinion` CLI command. One entry per opinion: `{story, kind, text, at}`. Story uniqueness is not enforced; the latest opinion per story wins (latest by line order).
2. **`reviews.jsonl`:** Appended by `agile-team reviewed` CLI command. Records when the liaison closed a review: `{text, at}`. The last entry is the current review; its summary is shown in the dashboard.
3. **`opinion-acts.jsonl`:** Appended by the server after a dismiss or apply. One entry per human act: `{opinion, story, act, route, ref, at}`. An opinion settles when an act is recorded; no undo or second act.

Each file has one writer; multiple files allow concurrent readers (browser snapshot, CLI). Entries are lenient-read: blank, torn, and malformed lines are skipped; ids continue from well-formed lines. This follows s84's data structure.

**O2: Latest opinion per story wins.** `Board.latest()` returns a dict mapping story id to its last Opinion entry. Line order decides; `at` timestamp is not consulted. This allows backdated opinions (e.g., liaison records one per story in a batch) without disrupting the "latest" concept.

### Recording opinions and reviews

**O3: `agile-team opinion <story> <kind> <source>`.** The liaison records an opinion. Refusals in order: unknown story, unknown kind, empty text. On success, appends `{story, kind, text, at}` stripped to `opinions.jsonl` and prints `recorded {id}: {kind} on {story}`. The kind is one of `keep`, `move-up`, `move-down`, `fold`, `close`, `scope`, `ask` (in this order, per design O1).

**O4: `agile-team reviewed <source>`.** The liaison records that a review is done. Checks text is non-empty after stripping, appends `{text, at}` to `reviews.jsonl`, prints `recorded backlog review {id}`.

**O5: Ask for a review.** The human clicks "Ask the liaison to review the backlog" on the dashboard. The server POSTs to `/api/review` with an empty body `{}` (validated: non-empty JSON object). On success, `Opinions.ask_review()` calls `Threads.post()` with a special post: story is empty string (`BACKLOG = ""`), recipient is LIAISON, text is `REVIEW_TEXT` (asking the liaison to use the `opinion`/`reviewed` commands). This appends to the liaison inbox and fires the `liaison_message` watch trigger. Dashboard shows "Asked <time>; waiting for the liaison" when `asked_at` (the largest `at` among review request posts) is later than the last review's `at`.

### Acts and routing

**O6: Dismiss or apply.** The human clicks dismiss or apply on an opinion from the Backlog tab. The server POSTs to `/api/opinion` with `{opinion: oN, act: "dismiss"|"apply", version}` and the write token. The server checks refusals in order:
1. The opinion id exists.
2. It is the story's latest opinion.
3. Its kind is not `keep` (nothing to act on).
4. No prior act on this opinion exists.

On success, the server routes the act: **dismiss** records an empty route (Route.NONE) and `ref=""`. **Apply** routes based on the opinion's kind and the story's group:
- **Move**: If kind is `move-up` or `move-down` AND the story is in the Backlog group, route to REORDER (queue an s83 reorder request for position 1 or len(backlog)). Ref is the request id `r<N>`.
- **Other kinds or sprint story moves**: Route to PO (create a thread post to the PO via `Threads.post()`). Ref is the thread id `t<N>`.

The route is computed from the current state each time the act is posted, not taken from the page. Then `opinion-acts.jsonl` is appended with `{opinion, story, act, route, ref, at}`.

**O7: Route NONE (dismiss).** Record only: no reorder, no thread post, no side effect.

**O8: Route REORDER.** Queue an s83 reorder request with `Requests.queue(Ask(story, position, version))` where position is 1 (top) for `move-up` or len(backlog) (bottom) for `move-down`. The desk applies it on the next runner step with all s83 checks (stale version, already in sprint, etc.). If refused, the details show the refusal. The act is still settled.

**O9: Route PO.** Post to the PO as a thread message: `Threads.post(Post(story, LIAISON, APPLY_TEXT))`. The text is templated: `"The human applied the liaison's opinion {opinion_id} on {story} from the dashboard: {kind}.\n\n{opinion_text}"`. The PO sees this at the next hand-over as a new thread post; it shows in the Backlog row's thread view and in the timeline.

### Dashboard: see, filter, and act

**O10: Render opinions.** The snapshot carries `opinions` with:
- `items`: All opinions in line order (the timeline needs old texts), each `{id, story, kind, text, at, latest: bool, route, act}`. Route is the latest opinion's route (if it has no act and kind is not `keep`), else empty. Act is filled only for settled opinions.
- `asked_at`: Timestamp of the last review request (largest `at` among posts to BACKLOG story), or `None`.
- `review`: The last review entry `{id, text, at}`, or `None`.

**O11: Highlight suggestions.** On the Backlog tab, a story with a non-`keep` latest opinion shows a badge `liaison: {kind}`. The expanded story shows the opinion's text and date. If settled, shows `dismissed <time>` or `applied <time> → <ref>`. If settled with a reorder ref, shows the request's status (`pending`, `applied`, or `refused: <reason>`).

**O12: Filter by suggestions.** A checkbox "only suggestions (N)" where N is the count of open stories with a suggestion (non-`keep` latest opinion, no act). When checked, each Backlog group shows only its rows with a suggestion. Group places and move handles are recomputed from the full group first, then filtered—so filtering does not change the `#position` or move target.

**O13: Review request button.** At the top of the Backlog tab, a review bar shows:
- "Last review: <time>" and the review summary (rendered as Markdown), or "The liaison has not reviewed the backlog yet."
- If `asked_at` is set and later than the last review's `at` (or there is no review), add "Asked <time>; waiting for the liaison."
- With a token, a button "Ask the liaison to review the backlog" (disabled while waiting or while a request is in flight).

**O14: Dismiss and apply buttons.** On the expanded story with a suggestion (no token hides them), two buttons:
- `dismiss`: Clears the opinion without escalation.
- `apply: <label>`: Posts the opinion-act. Label is "move to the top of the backlog" (move-up), "move to the bottom of the backlog" (move-down), or "send to the PO" (other kinds). Apply is disabled while a reorder request is pending on that story (s83 B8).

### Events and timeline

**O15: Events merge opinions and acts.** Every opinion and act is an event, sorted by time:
- Opinion: `{"id": "opinion-oN", "at", "kind": "opinion", "role": None, "story", "data": {"opinion": "oN", "kind": "kind_str"}}`
- Act: `{"id": "opinion-act-aN", "at", "kind": "opinion-act", "role": None, "story", "data": {"opinion": "oN", "act": "dismiss"|"apply", "route": "", "ref": ""}}`

These merge into the snapshot's `events` with thread, message, and reorder events (s84, s83).

**O16: Timeline shows opinions.** Each opinion event shows "liaison: opinion <kind>" (from→to: "liaison" to "you"). Each act event shows "you: opinion <act>" (from→to: "you" to the route target: "liaison", "runner", or "PO"). The body is the opinion text or the id + ref for acts. "opinion" and "opinion-act" kinds are rendered as Markdown.

### Temporary routing

**O17: Close goes to the PO.** When the human applies a `close` opinion, it routes to PO (not yet a cancel). The PO is asked to start a cancel via s53 (not yet built). Until s53 is available, applying `close` asks the PO to consider cancellation, and the decision stays with the human.

## Consequences

**Positive:**
- **Opinions are lightweight.** Not state entries, not event log lines (which only the runner writes). Files live in `liaison/`, written by CLI and server independently.
- **Unasked opinions work.** Liaison can record opinions anytime while the run is stopped, without a request cycle.
- **Latest-by-line is simple.** No timestamps to compare; line order is the order written. Len(backlog) changes, so versions matter only for reorder acts.
- **Dismisses and applies are reversible.** A dismissed opinion can be re-proposed later; applying doesn't lock the story, it queues a request (which may be refused and shown).
- **Acts cascade correctly.** Move acts go to the reorder queue (desk applies with all checks); other acts go to the PO (as thread posts). Close goes to PO, not yet cancel.
- **Suggestions stay interactive.** Filtering and badge count update live as opinions settle; no page reload needed.

**Tradeoffs:**
- **No "how many opinions this run" count.** Opinions are not in the event log; the snapshot lists them all, but only the latest per story is actionable. The timeline will show all events (opinion, opinion-act) in order.
- **Reorder acts settle even if refused.** An act record exists; the refusal is in the reorder request's status. The details show it; the human can try again with the handles or the thread.
- **Close doesn't cancel yet.** Until s53, `close` goes to the PO as a suggestion, not an order.

**Data contract:**
- Snapshot gains `opinions` section with `items`, `asked_at`, and `review`.
- Snapshot's `events` gains `opinion` and `opinion-act` kinds.
- Snapshot's `watched_files` includes the three `liaison/*.jsonl` files.
- Dashboard gains `/api/review` (POST with token) and `/api/opinion` (POST with token) routes.
- CLI gains `opinion` and `reviewed` commands.

**Module changes:**
- New `opinions.py` module: Kind, Act, Route enums; Opinion, Review, Settled, ActAsk dataclasses; Board and Opinions classes; lenient readers and writers.
- `threads.py` gains `BACKLOG = ""` constant and renames `_lines`/`_append` to `read_lines`/`append_line` (public, for DRY).
- `cli.py` adds `cmd_opinion` and `cmd_reviewed` commands.
- `server.py` adds Dashboard.opinions, `_review` and `_opinion` handlers, BODY_LIMITS entries.
- `snapshot.py` adds `_opinions`, `_opinion_item` builders, events merging, watched files.
- `index.html` adds UI state (ui.suggested, ui.acting, ui.asking), opinion renderers, review bar, filter, badge, dismiss/apply buttons, timeline entries.
- `product-owner.md` gains a note: applied opinions (other than moves) are human requests to the PO.

**No new dependencies.**

## Related decisions

- **ADR-0044 (s84):** Story threads—this decision reuses the append-only JSONL pattern for opinions, reviews, and acts. The `ask_review` button posts to the liaison inbox the same way human messages to the liaison post.
- **ADR-0043 (s83):** Backlog reorder—applied move opinions queue reorder requests through the same desk and router, with stale-version and sprint checks.
- **ADR-0027 (s4):** Snapshot raw data contract—this decision adds the opinions section and events to the snapshot; builders are thin functions (8 lines or fewer per house rules).
- **ADR-0021 (s43):** Live config in snapshot—token is shown in the URL; no secrets leak to snapshot.

## Notes

One follow-up (not blocking, s85 does not touch it):
- **s84 `threads._is_reply`** checks `isinstance(at, int | float)` inline, which lets a bool through. It should use the new `threads.has_time(record)` helper (DRY, same check used in `_well_formed` and opinions lenient readers).
