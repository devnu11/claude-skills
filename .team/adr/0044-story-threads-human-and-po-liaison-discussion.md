# ADR-0044: Story threads for human discussion with the PO and liaison

**Decision:** Story threads let the human discuss a story directly on the dashboard with the PO or the liaison. A thread is a read-only view over four data sources (not a new store): posts to the PO go through `Relay.tell` with a thread tag; PO replies use a new `reply_story` tool; posts to the liaison append to `liaison/inbox.jsonl` and trigger a new `liaison_message` watch event; liaison replies use a new `agile-team reply` CLI command. The dashboard serves thread entries merged by time, with a token-gated form to post from localhost.

**Date:** 2026-10-13  
**Status:** Accepted  
**Affected:** Dashboard, router, PO tools, watch triggers, relay, CLI, snapshot, story workflow

## Context

The human needs to discuss a story with the team without opening the PO through separate requests. The PO is not interactive; posts through `tell` and `notify_user` are asynchronous. The liaison watches the run and can respond faster. A thread on the dashboard would let the human ask questions, get quick answers from the liaison, and see PO replies when they come, keeping discussion with the story.

The challenge is to avoid creating a new data store. The runner has multiple writers: the server (posts), the PO (replies), the CLI (liaison replies), and the watch process (not a writer, but needs to trigger on posts to the liaison). Files exist: `relay.tell` writes message files, `outbox.jsonl` tracks PO answers, and `liaison/inbox.jsonl` logs watch triggers. These can be the thread's sources if combined into a view.

## Decision

### Thread shape and data sources

**D1: Thread as a view, not a store.** A thread is the merged view of four append-only files, each with one job:
1. **Posts to PO:** Files in `liaison/messages/t<N>.md` (existing `Relay.tell` files), tagged with a thread head.
2. **PO replies:** Lines in `outbox.jsonl` with `kind == "reply"` and a story in `stories` (existing outbox, new kind).
3. **Posts to liaison:** Lines in `liaison/inbox.jsonl` (existing for watch triggers, now also thread data).
4. **Liaison replies:** Lines in `liaison/replies.jsonl` (new JSONL file, parallel to inbox).

`Threads.all()` reads all four, parses each into `Entry` records, sorts by time, and presents them as a unified thread. No aggregation happens until read-time. This keeps writers simple: each path writes its own format, the view stitches them together.

**D2: Entry structure.** Each thread entry is `Entry(id, story, author, to, text, at)`. Author is one of `Party.HUMAN`, `Party.PO`, or `Party.LIAISON`. Recipient (`to`) is `Party.PO` or `Party.LIAISON` for posts, `Party.HUMAN` for replies. The `id` distinguishes sources: `t<N>` (relay files), `m<N>` (outbox lines), `lp<N>` (liaison inbox), `lr<N>` (liaison replies). Time is system time at write.

### Writing rules (H1–H5)

**D3: Parties.** Three roles post or reply: human (via dashboard), PO (via tool), liaison (via CLI). Party enum: `HUMAN = "human"`, `PO = "product-owner"`, `LIAISON = "liaison"`. Recipients for new posts: `RECIPIENTS = {PO, LIAISON}`. (AC1, H1)

**D4: Text validation.** Text must be non-empty after stripping, and no longer than 4000 characters. Blank text refused with `EMPTY = "the message is empty"`. Over-long text refused with `TOO_LONG = "the message is longer than 4000 characters"` (exact format). All writers (server, PO tool, CLI) call `text_refusal(text)` and store only stripped text. (AC1–AC3, H2)

**D5: Story validation.** Story id must be a key in `state.stories`. Done stories are allowed (the human may discuss a finished story). Unknown stories refused with `UNKNOWN_STORY = "no story {story!r}"`. `story_refusal(story, stories)` returns the refusal or None. (AC1–AC3, H3)

**D6: Write gate for dashboard posts.** `/api/thread` POST is checked in order: (1) May the peer write (localhost, token)? — 403. (2) Is Content-Length a whole number 1–32768? — 400. (3) Does `parse_post(body)` give a valid Post? — 400. (4) Does `post_known(post)` apply the post and return an Entry? — 400. (5) Reply: 202 with `{"id": entry.id, "status": "posted"}`. The body is not read before (1) and (2) pass. (AC1, H4)

**D7: Post shape.** JSON object with keys `story` (matching story id pattern), `to` (`"product-owner"` or `"liaison"`), and `text` (string passing H4). Extra keys ignored. Invalid JSON, missing keys, bad `to`, non-str text, or text failing H4 gives `None`. (AC1, H5)

### To the PO (H6–H8)

**D8: Posts to PO go through `Relay.tell` with a thread tag.** `Threads.post(Post(story, PO, text))` calls `Relay(run_dir).tell(tagged(story, text))` where `tagged` prepends the head `<!-- thread story={story} at={at} -->` (two newlines after). The entry id is the `Told` id (`t<N>`). Author is `HUMAN`, recipient `PO`, text is stored stripped. (AC2, H6)

**D9: Tag format and reading.** `HEAD_RE` matches the head exactly: `\A<!-- thread story=([A-Za-z][A-Za-z0-9_-]{0,63}) at=([0-9]+(?:\.[0-9]+)?) -->\n\n`. `tag_of(told: Told)` reads the file and returns `Tag(story, at, text)` if the head matches, else `None` (OSError also gives `None`). The text is everything after the head. (AC2, H7)

**D10: PO is told the story in hand-over.** In `Router._told_lines`, each told file becomes `threads.told_line(told, repo)`. That is `THREAD_TOLD_LINE = "The human wrote to you on {story}'s thread ({id}): read {path}. Answer there with reply_story; the reply shows under the story on the dashboard."` when the file has a tag, else today's `TOLD_LINE`. The PO's answer stories in `_deliver` are the ones from tools plus `threads.told_stories(told)` (tagged stories, deduplicated in order). (AC2, H8)

**D11: PO replies with `reply_story` tool.** New tool `reply_story(story: str, text: str)`. Refusals in order: `story_refusal` (H5), then `text_refusal` (H4), each giving `text_result(refused(reason))`. On success, it calls `relay.post(Note(REPLY, text.strip(), [story]))` and returns `{"status": "posted", "id": msg.id}`. (AC2, H9)

**D12: No notify_user for replies.** `notify_user` with `kind == REPLY` is refused with `USE_REPLY = "use reply_story to answer on a story's thread"` before posting. This ensures every `reply` message comes from `reply_story` and names exactly one story. (H9)

### To the liaison (H10–H11)

**D13: Posts to liaison append to inbox.** `Threads.post(Post(story, LIAISON, text))` appends `{"story", "text", "at"}` as one JSON line to `run_dir/liaison/inbox.jsonl` (after `make_dirs`). Entry id is `lp<N>` where N is the 1-based line count after parsing. Author `HUMAN`, recipient `LIAISON`, text stripped. (AC3, H10)

**D14: Liaison inbox wakes the liaison with a new watch trigger.** `Seen` gains `posts: int = 0` (count of liaison-inbox entries already reported). `Look` gains `posts: list[Entry]` and `new_posts(seen)` method following the message-trigger rule: entries after `seen.posts`, or all if the inbox got shorter. `TRIGGERS` gains `("liaison_message", lambda seen, now: bool(now.new_posts(seen)))` after `message`. In `line()`, `"posts"` is `[entry.as_dict() for entry in now.new_posts(seen)]` (or `[]` for heartbeat). `Watcher._next` keeps `seen.posts`. Old memory files load with `posts = 0`. First watch records current posts as seen (s67 F2). (AC3, H11)

**D15: Liaison replies with CLI command.** `agile-team reply <story> <source>` where source is a file or `-` (stdin). Runs H4 (text), then H5 (story against `state_mod.load(run_dir).stories`). Raises `CliError(reason)` on refusal. On success, appends `{"story", "text", "at"}` to `liaison/replies.jsonl` and prints `REPLIED = "replied {id} on {story}"`. Works while run is stopped. (AC3, H12)

### Reading the thread (H13)

**D16: All entries merged by time.** `Threads.all()` = `to_po() + po_replies() + liaison_posts() + liaison_replies()`, sorted by `(at, id)`. `to_po`: tagged relay files (author HUMAN, to PO, id t<N>). `po_replies`: outbox lines with `kind == "reply"` and non-empty `stories` (author PO, to HUMAN, story from `stories[0]`). `liaison_posts`/`liaison_replies`: inbox and replies JSONL lines (ids lp<N>/lr<N>). JSONL read leniently: blank, torn, non-object lines skipped; blank and later non-object lines ignored; records without str `story`, str `text`, or number `at` skipped. Only the last line can be torn (append-only). Earlier ids never shift. (AC2–AC4, H13)

### Dashboard (H14–H18)

**D17: Events merge thread entries.** Every entry is an event on its story: `{"id": "thread-<entry id>", "at", "kind": "thread", "role": EVENT_ROLES.get(author), "story", "data": {"entry", "author", "to"}}`. `EVENT_ROLES = {Party.PO: "product-owner"}` (liaison replies have no role). Merged by time with the event log, outbox, and inbox. Outbox messages with `kind == "reply"` appear once as `thread`, not as `message`. (AC4, H14)

**D18: Snapshot carries thread and thread events.** New top-level key `"thread"`: `[entry.as_dict() for entry in Threads(run_dir).all()]`. Each dict is `{"id", "story", "author", "to", "text", "at"}` (enums as strings). `watched_files` adds `*threads.watched(run_dir)` (inbox, replies, and relay told files). (AC2–AC4, H15)

**D19: Token-gated thread form on the expanded Backlog row.** An expanded row (s83) ends with `threadHtml(story, view)`. Lists story's entries from `view.thread` in time order: `WHO[author] → WHO[to]` label, time, and Markdown text. With a `TOKEN`, a form follows: textarea (maxlength 4000, drafts in `ui.drafts`), select for recipient (PO or liaison, default PO, state in `ui.to`), send button (disabled while posting, in `ui.sending`). Posting is `postThread(id)`: blank draft sets note `SEND_EMPTY`, else POST `api/thread` with `{story, to, text}` and token header. Response 403 sets `READ_ONLY`, other non-OK sets error, OK clears draft. Entry appears in next snapshot. Without token, no form, read-only note. (AC1, AC4, H16–H17)

**D20: Focus survives re-renders.** `renderBacklog` wraps its work with `keepFocus(fn)`: when a `[data-thread-text]` has focus, note the id and selection, run `fn`, refocus the new textarea with that id, restore selection. (AC1, H18)

**D21: Timeline shows thread entries.** `TIMELINE.thread = (e, ctx) => ({from: WHO[e.data.author], to: WHO[e.data.to], what: "thread", body: ctx.thread[e.data.entry]?.text ?? ""})`. `ctx.thread` maps snapshot's `thread` by id. "thread" joins `MARKDOWN_KINDS`. (AC4, H19)

### Implementation modules (D22–D27)

**D22: New `agile_team/threads.py` module.** Pure reading and composition logic. Party enum, Entry dataclass, refusal and validation functions (`text_refusal`, `story_refusal`, `parse_post`), tagging (`tagged`, `tag_of`), Threads class with `post`, `reply`, and the four readers. No imports of dashboard. Lenient JSON reading copied from snapshot (design specifies local copy). (H1, H2, H5, H6, H7, H13)

**D23: `relay.py` changes.** `REPLY = "reply"` added last to `KINDS`. `tell` draft renamed from `.draft-{pid}` to `.draft-{token()}` so dashboard threads don't collide (multiple threads in one process). (H6, H11)

**D24: `router.py` changes.** `_told_lines` uses `threads.told_line` instead of inline `TOLD_LINE`. `_deliver` stories = answer stories + tagged stories, deduplicated in order. (H8, H10)

**D25: `po_tools.py` changes.** New `reply_story(args)` tool. `notify_user` refuses `REPLY` kind before posting. Schema for `reply_story` added. (H9, H12)

**D26: `watch.py` changes.** `Seen.posts`, `Look.posts`, and the `liaison_message` trigger. Old memory loads with `posts = 0`. First watch takes existing posts as seen. (H11, H14)

**D27: `cli.py` changes.** New `cmd_reply(args)` command and COMMANDS row. (H12, H15)

**D28: `dashboard/server.py` changes.** `Dashboard.post` callable, bound to `threads.post_known` for `/api/thread`. `BODY_LIMITS` table with route-specific limits. `_body` checks per-route limit. `_thread` handler in H4 order. (H4, H6)

**D29: `dashboard/snapshot.py` changes.** `_thread` section builder. `_events` maps thread entries and drops `reply` outbox lines from message events. `watched_files` includes thread files. (H14, H15, H18)

**D30: `dashboard/index.html` changes.** UI state for drafts, recipients, sending status, notes. Functions: `threadEntries`, `threadHtml`, `threadFormHtml`, `postThread`, `keepFocus`. Input/change listeners for drafts and recipients. Click handler routing (send checked first, clicks in details outside expand). Timeline integration. CSS for thread blocks and form. (H16–H21)

### File formats (D31–D32)

**D31: Relay tell with thread head.** Format: `<!-- thread story=<id> at=<timestamp> -->\n\n<text>`. Head matches `HEAD_RE` exactly. Absent head means plain tell (no story tag). (H6–H7)

**D32: Liaison inbox and replies.** Format: one JSON line per entry: `{"story": "<id>", "text": "...", "at": <timestamp>}`. No extra fields required. JSONL is append-only; torn last line acceptable. Read leniently: blank and non-object lines skipped. (H10, H12–H13)

## Consequences

**Positive:**
- **Human can discuss directly.** Posts to the PO arrive at the next hand-over; posts to the liaison wake them within 2 seconds. No separate request cycle needed.
- **Threads are auditable.** Every post, reply, and author is in the run files with time and story tag. Dashboard and timeline show the full conversation.
- **View over files, not a new store.** Each path owns its data; no central thread table. Append-only files are safe (torn reads skip the tail).
- **Relay and outbox unchanged.** Thread posts use existing `tell` and `reply` message kinds; only the add-ons (head tag, file reading) are new.
- **Liaison wakes fast.** New `liaison_message` trigger fires within the watch poll interval (~2s), no heartbeat wait.
- **PO and liaison flows differ.** PO replies are async (next hand-over); liaison replies are interactive (CLI call while run is stopped).

**Tradeoffs:**
- **PO reads one post at a time.** Hand-over names only the new post, not prior thread. PO can ask questions via the thread itself or human can quote.
- **Two JSONL readers.** Both `liaison_posts` and `liaison_replies` read leniently. Sharing a helper avoids duplication, but torn lines must be understood (append-only is assumed).
- **Liaison doesn't interrupt a run.** The `reply` command works while run is stopped. Liaison can listen and reply via watch, or batch replies after the run stops.

**Data contract extends:**
- Snapshot gains `thread` array with entries and `thread` events merged in `events`.
- Watched files include `liaison/inbox.jsonl`, `liaison/replies.jsonl`, and `liaison/messages/t*.md`.
- Relay adds REPLY kind; relay drafts are named by token to avoid collision.
- Outbox reply messages are no longer dual-logged as message events (only thread).
- Watch adds `liaison_message` trigger and `posts` field in memory and line output.
- Router's `_told_lines` includes thread-tagged tells.

**Module boundaries:**
- `threads.py` is pure; reads files, returns composed data.
- Server and CLI write files independently; reads happen at view-time.
- Snapshot watches all thread files and rebuilds on any change.
- No new dependencies.

## Related decisions

- **ADR-0027 (s4):** Snapshot as raw data contract. This decision adds thread entries and events to the snapshot; the builder is a thin function (8 lines or fewer per rule).
- **ADR-0043 (s83):** Backlog on dashboard. This decision adds the expanded row where the thread form appears; no changes to reorder logic.
- **ADR-0021 (s43):** Live config in snapshot. Token display in the URL is consistent with how dashboard config is shown (no secrets in snapshot).
- **ADR-0029 (s62):** Liaison commands (tell, watch). This decision adds `reply` command to the liaison's toolkit, alongside `tell` and `watch`.
