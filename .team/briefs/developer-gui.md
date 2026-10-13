# Developer (GUI): Current context and conventions

**Last updated:** 2026-10-13 (s85 done)

See `developer.md` for base conventions.

## s85 complete: The liaison's opinions on stories, highlighted in backlog (code done, P1 pending)

New opinions feature on the Backlog tab. The liaison records opinions with `agile-team opinion` CLI command; the dashboard shows them as badges and allows the human to dismiss or apply them. Applied move-opinions queue reorders; other applied kinds post to the PO as thread posts.

**Features implemented (design O1–O20, ~200 LOC index.html additions):**
- **Opinion badges:** Backlog stories with non-`keep` opinions show `liaison: <kind>` badges. Expanded rows show the opinion's text, date, and route (reorder or PO).
- **Filter:** Checkbox "only suggestions (N)" filters to stories with open opinions. Places and move handles computed from full group first, then filtered.
- **Review bar:** "Last review: <time>" with summary (Markdown). Button "Ask the liaison to review the backlog" posts to inbox, fires `liaison_message` watch trigger. Shows "waiting" state.
- **Dismiss and apply:** Two buttons on suggestions. Apply routes move-opinions to reorder queue (disabled while pending), others to PO via thread posts. Both buttons disabled without TOKEN; rendered Markdown text in opinion details.
- **Events and timeline:** Opinions and acts merged into events (kind="opinion"/"opinion-act"); timeline shows them with source→target labels and Markdown body.
- **Snapshot fields:** New `opinions` section with items (all, `latest` flag, route, act), `asked_at`, `review` (last); events gain opinion/opinion-act kinds.

**Implementation notes (index.html):** New state: `ui.suggested`, `ui.acting` (Set), `ui.actNote`, `ui.asking`, `ui.reviewNote`. Functions: `storyOpinion()`, `isSuggestion()`, `opinionBadge()`, `opinionHtml()`, `reviewBarHtml()`, `postReview()`, `postOpinionAct()`. Button handlers `[data-opinion-act]` and `[data-ask-review]` checked before expand toggle.

**Shipped:** Code review done (m4 docstring minor). Node harness and e2e tests pending (integration-tester P1).

See ADR-0045.

## s84 complete: Story threads with the PO and the liaison (on Backlog tab)

An expanded Backlog row now shows a thread of discussion with the PO or the liaison. The human can post questions from a form on the dashboard; the PO replies with `reply_story` tool (next hand-over); the liaison replies via CLI `agile-team reply` command (within 2 seconds via new `liaison_message` watch trigger). All ACs pass (code review done, node harness and e2e pending for integration-tester).

**Features implemented (design H1–H21):**
- **Thread view:** Below the expanded row's event list, `threadHtml(story, view)` lists entries in time order: `you → PO`-style labels, time, Markdown text. Shows "No messages yet." if none. With TOKEN, adds a form; without, shows read-only note.
- **Form:** Textarea (maxlength 4000 chars, in `ui.drafts[id]`), select for recipient (PO/liaison, `ui.to[id]` defaults PO), send button (disabled in `ui.sending` while posting).
- **Posting:** `postThread(id)` POSTs `/api/thread` with `{story, to, text}` + token header. Blank text rejected (`SEND_EMPTY`). Response 403 → read-only note; other non-OK → error; OK → draft cleared, entry appears next snapshot.
- **Focus preservation:** `keepFocus(fn)` saves textarea focus and selection, runs render, restores both. Typing survives re-renders.
- **Timeline:** Thread events appear in timeline with author→recipient labels and Markdown body. Story filter in timeline shows thread entries for that story.
- **Snapshot fields:** `run` unchanged; `story` unchanged; new top-level `thread` array with 5 entries per story.

**Implementation notes (index.html):**
- New state: `ui.drafts = {}`, `ui.to = {}`, `ui.sending = new Set()`, `ui.threadNote = {}`.
- Constants: `WHO = {human: "you", "product-owner": "PO", liaison: "liaison"}`, `SEND_EMPTY`, `NO_THREAD`.
- Functions: `threadEntries(view, id)` (filter `view.thread` by story), `threadHtml(story, view)`, `postThread(id)`, `keepFocus(fn)`.
- Event handlers: `[data-thread-text]` and `[data-thread-to]` update drafts/recipients; `[data-thread-send]` posts (checked before expand toggle).
- CSS: `.thread` (entry block), `.tmsg` (sender labels), `.tform` (form layout).

**Shipped:** Code review done (two minor findings left for later: m1 nested div, m2 bool check). Node harness tests (items 14–16) and e2e test (real POST → file, watch trigger, reply in snapshot) owned by integration-tester.

See ADR-0044.

## s83 complete: Backlog tab with reorder handles and file reading

New Backlog tab on the dashboard. Lists every story not done in two groups (Current sprint and Backlog), with expand/collapse, move handles, drag-drop, and file reading.

**Features implemented (design B1–B20):**
- **Row:** Backlog rows show `#position`, id, title, step, status, delivery, label pill (cancelled/held), hold reason. Current-sprint rows are read-only, no handles.
- **Expand:** Click row to expand. Shows story file (fetched from `api/file?kind=story&id=<id>`), state fields (sprint, step, status, rounds, disputes, hold, developer, delivery, commits), links to design/review/acceptance files, spend and turns from ledger, last 10 events, open questions naming the story.
- **Handles and drag:** Backlog rows have move buttons: `↑` (up), `↓` (down), `⤒` (top), plus `draggable="true"` for drag-drop onto another Backlog row. Disabled on edges (first/last) and while pending. Current-sprint rows have no handles.
- **Token and read-only view:** Extract `TOKEN = PARAMS.get("token") ?? ""` from URL. Without token, show read-only note; with token, show handles. Every POST includes `X-Agile-Team-Token` header.
- **File reading:** `loadFile(id, kind)` fetches from `/api/file?kind=<kind>&id=<id>`. Shows `loading…`, falls back to `no story file` on 404 or error. Cached in `ui.files`. Files are text/plain.
- **Reorder requests:** `postReorder(story, position)` POSTs `{story, position, version}` where version is `run.order_version` from snapshot. Server replies 202 with request id and status "queued". Handles pending/applied/refused outcomes in `reorderNote()`.
- **Request status display:** Pending → "waiting for the runner: moves apply between steps"; Applied → clears note; Refused → shows reason (STALE adds reload button); 403 → "read-only: open the link the dashboard printed"; other errors → HTTP status.

**Implementation notes (index.html):**
- New section: `<section id="tab-backlog" hidden>` with `<p class="sub" id="backlog-note">` and `<div id="backlog">`.
- State: `ui.expanded` (Set of ids), `ui.files` (cache), `ui.reorder` ({id, story}), `ui.note` (status text), `ui.drag` (dragged row id).
- Functions: `backlogGroups(view)` (split current/backlog), `storyLabel(story)`, `backlogRow(story, place, count, view)` (with handles), `storyDetails(story, view)` (state fields, links, ledger sums, events, questions), `backlogHtml(view)`, `renderBacklog(view)`, `toggleRow(id)`, `loadFile(id, kind)`, `moveTarget(action, place, count)`, `postReorder(story, position)`, `reorderNote(view)`, `moveFromHandle(btn)`.
- Event handlers: click on `[data-expand]` toggles, click on `[data-move]` posts move, click on `[data-reload]` reloads page; dragstart/dragover/drop for drag-and-drop.
- Timeline: `showEvent()` displays `data.source` when set (human vs PO).
- Snapshot fields: `run.order_version`, `run.backlog`, `story.label`, `story.commits`, `story.developer`, `story.disputes`, `story.files`, `story.developer`, top-level `reorders`.

**Test coverage (AC8, pending integration-tester):**
Node harness: expand/collapse under `tests/dashboard_node.py`, handles present/absent, `moveTarget` edges, `reorderNote` cases (all states), no drag while pending, commits shown in details. E2E: real dashboard --port 0 --token t, POST from 127.0.0.1 gets 202, router applies.

**Shipped:** Review done (D3 README fixed). P1 work (node-harness and e2e tests) for integration-tester. Fixture and contract: design `agile-team/docs/design/s83.md`.

See ADR-0043.

## s15 complete: Dashboard renders Markdown safely

Questions tab and timeline now display Markdown with formatting (headings, lists, emphasis, code, tables) and fall back to plain text if the library doesn't load. All four ACs pass.

- **AC1 syntax:** `md()` renders headings, paragraphs, lists, emphasis, inline/fenced code, tables, links via markdown-it default preset.
- **AC2 safe:** Raw HTML escapes (`html: false`), links http(s) only (`validateLink`), images disabled, script/onerror payloads inert (confirmed in tests).
- **AC3 one function:** `md(text)` is the only renderer; questions, raised questions, answered questions, and timeline bodies (step-end, message, answer) use it. Plain text stays escaped.
- **AC4 pinned URL:** markdown-it@14.1.0 loaded from CDN like Mermaid, graceful plain-text fallback, testable offline with vendored copy.

**Implementation notes:**
- New markdown section in `index.html` (MARKDOWN_URL, SAFE_LINK, markdown state, functions: safeMarkdown, useMarkdown, loadMarkdown, md).
- `boot()` calls `loadMarkdown()` (not awaited); on success, useMarkdown then re-render; on failure, warn and stay plain.
- `renderQuestions` and `renderAnswered` call `md()` for question/answer text; `.q-answer` div styled smaller.
- Timeline: data-driven `MARKDOWN_KINDS` set and `bodyHtml()` helper pick renderer by kind.
- CSS: `.md` normal wrap, `.md.plain` pre-line; block elements 6px margin, headings bold, lists indented, code/pre on surface-2.
- Vendored copy in tests/vendor/markdown-it-14.1.0.min.js for offline e2e (integration-tester's job).

**Rule change (ADR-0042):** "Only outside URL is Mermaid" becomes "exactly two outside URLs: Mermaid and markdown-it" (both pinned).
