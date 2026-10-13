# Developer (GUI): Current context and conventions

**Last updated:** 2026-10-13 (s83 done)

See `developer.md` for base conventions.

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
