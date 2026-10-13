# Integration Tester: Current context and conventions

**Last updated:** 2026-10-13 (s104 P1 pending; s96 P1 pending; s86 P1 pending; s85 P1 pending; s84 P1 pending; s83 P1 pending)

## s104: E2E tests for Flow chart fixes (unit/code-review done, P1: your work)

**File:** `tests/e2e/test_s104_flow_e2e.py` (new). Cause and rendering checks run on fixture via node harness (dashboard_node.run_page). Served-snapshot AC5 test real dashboard.

**Design checklist (all via node harness + served dashboard):**

1. **AC4 (cause):** On fixture, Story scope with focus that dims ≥1 node, and Sprint scope on same data:
   - No `classDef` line contains `opacity`, `filter`, `transform`, `mix-blend-mode` (FL1, FL2).
   - `classDef idle` sets only `fill`, `stroke`, `color` (exact text).
   - This check **fails on today's code** (test confirms fix works).

2. **AC4 (hidden then shown):** Stub `mermaidModule` to record `initialize` options and `render` sources.
   - With `ui.tab = "board"`, call `render()`; stub records nothing.
   - Call `showTab("flow")`; let microtasks run.
   - Expect one `initialize` with `flowchart.useMaxWidth === false`, `themeVariables.fontSize === "16px"`.
   - Rendered source passes FL1 check (no opacity).

3. **AC3 (size):** `parseFloat(mermaidConfig(themeVars()).themeVariables.fontSize) >= 16` and `useMaxWidth === false`. Box stats ≥ 12 CSS px.

4. **AC2 (idle text):** Story scope, role with no totals and no open step has label `· idle`, not `$0.00`. Role with totals still shows `tokens · $ · time`.

5. **AC5 (unused roles):** With `developer-db` `used: false`, `flowSource` has no `developer-db` node. With `used: true`, has one. Role with no `used` key still drawn.

6. **S96 labels:** Running box shows `⏱ running <time>`. Existing s96 expectations still hold.

7. **Served snapshot AC5:** Serve on scratch repo. Snapshot has no `developer-db`. Append `step-start` event for `developer-db` to `events.jsonl`. Next `/api/snapshot` has it `used: true` and `flowSource` draws it (AC5, FL9).

See design `agile-team/docs/design/s104.md` (test checklist items in E2E section), ADR-0047.

## s96: Node harness and e2e for Flow time display (unit/code-review done, P1: your work)

Code shipped. Unit tests pass (23 tests, coverage ≥95%, ruff clean). Code review done (all ACs pass). **Your work (P1): node-harness tests and e2e for active running line.**

### Node harness tests (`tests/dashboard_node.py`, four test functions from design checklist items 7–9, 14–15)

**Setup:** Load fixture with time steps (agent steps with different durations).

1. **Scope toggle (ST10):** With `ui.scope` set to `story`, `sprint`, `run`, `scopeTotals(view)[role].seconds` matches hand-computed sums for the fixture (AC5, ST10).
2. **Box time (ST10, ST11):** `nodeLabel` for a role contains `fmt.span` total. Running role with open step started 600s before `clockNow` gives `runningLine` with `"⏱ running 10 min"`.
3. **Time chart (ST12–ST14):** `Object.keys(UNITS)` is `["tokens", "usd", "time"]`; `UNITS.time.label="Time"`, `title="Time by"`. With `ui.unit="time"`, `renderUnit` writes three buttons and title. `barRows` largest first; `timeRow` tooltip has step count and `% of time`; value is `fmt.span`. `timeLegend()` text exact `"agent steps only; runner stages: see A6"`.
4. **costRow unchanged:** Dollars display unaffected by the `whole` parameter rename.

### E2E test for active running line (real dashboard, 60s timeout)

**File:** `tests/e2e/test_s96_running_time_e2e.py` (new).

**Test:** Open dashboard on Flow tab. Let a step run (or mock one open in snapshot). Verify: active box shows `⏱ running 5 min` (or similar) **without a new snapshot arrival**, and the time increments roughly once per minute. Stop the runner or set a long clock offset to lock the display, verify time stops changing.

See design `agile-team/docs/design/s96.md` (test checklist items 7–9, 14–15).

## s86: E2E and node-harness tests for story dependencies (AC1–AC5 unit/code-review done, P1: migration pin and page harness)

Code shipped. Unit tests pass (coverage 99.46%, ruff clean). Code review done (all ACs pass except P1). **Your work (P1):** DP16 migration pin (AC4) and page harness tests (AC5).

### E2E: DP16 migration pin (AC4)

File: `tests/e2e/test_s86_dependencies_e2e.py` (new).

Read the real `.team/stories/*.md` bodies. Verify:
1. **Prose check:** Every file whose body matches `(?i)\bdepends\s+on\s+s\d+` must have id in `HISTORY` (done stories: s4, s5, s9, s29, s70, s76, s77, s79, s83, s84, s85 only). Assert matching ⊆ HISTORY.
2. **Migration table (DP15):** Each story in table M (s2, s6, s10, s16, s32, s33, s34, s35, s36, s39, s54, s55, s94, s95, s102) has `story_files[id].frontmatter['depends_on']` equal to table M's list (drop-done rule applied, so s39→[], s10→[], etc.). Assert exact match per story.

See design DP15–DP16 and table M for expected lists.

### Node harness: Dependencies on Backlog tab (AC3)

File: `tests/dashboard_node.py` (add to existing file, four test functions).

**Setup:** Load fixture with dependencies. Fixture story s2 depends on s1 (done), s5 depends on s2 (undone), s6 depends on s1 (done).

1. **Dependencies shown (DP14):** Backlog row for s2 shows `depends on s1 (done)`. Row for s5 shows `depends on s2`. Row for s6 shows `depends on s1 (done)`. Story with no depends_on shows no line.

2. **Waiting and done markers (DP14):** s2 and s6 (wait on nothing) have no `waiting_on` banner. s5 (waiting on s2) shows inline with depends line or as banner; no (done) marker on s2.

3. **Warning pills (DP14):** Fixture has s2 above s5 (inversion). Row for s2 shows pill `⚠ s2 is above s5, which it depends on` (exact text). s5 has no warning (depends on s2 which is below it).

4. **Timeline warnings (DP12, DP14):** `TIMELINE.priority` event where s2 moved above s5 has meta ` · ⚠ s2 is above s5, which it depends on` and tone `warning`. Event with no inversions has `warnings: []` and tone `default` (not `warning`).

See design DP11–DP14 for exact texts and warning logic.

## s85: E2E tests for liaison opinions (AC1–AC5 unit/code-review done, P1: node-harness and e2e tests pending)

Story shipped in code. Unit tests pass (coverage 99.46%, ruff clean). Code review done (all ACs pass). **Your work (P1): node-harness and e2e tests.**

### Node harness tests (dashboard_node.py, four test functions)

1. **Badge and filter (AC2):** With fixture (s6 move-down opinion, s5 scope settled), Backlog shows badges `liaison: move-down`, `liaison: scope`. Expanding shows kind, date, text. Ticking "only suggestions (1)" filters to s6 only; unfiltered positions and handles unchanged.
2. **Details (AC2, AC4):** s6 shows opinion details with kind, text, time; dismiss and apply buttons labeled "move to the bottom" (move-down) and "send to the PO"; buttons disabled without TOKEN.
3. **Review bar (AC3):** Shows "Last review: <time>" and summary, or "The liaison has not reviewed yet". With `asked_at` later, adds "Asked <time>; waiting"; button absent without TOKEN.
4. **Posting (AC3, AC4):** `postReview()` POSTs `/api/review` with `{}` and token header. `postOpinionAct(id, act)` POSTs `/api/opinion` with `{opinion, act, version}`. 409 response sets reason; OK clears note.

### E2E test (30s timeout, real dashboard --port 0 --token t)

POST `/api/opinion` with apply (dismiss similar). Expect 202 with id/status. For move-up on Backlog story, expect ref is a reorder id. For other kind, expect ref is a thread post id (route in answer).

See design `agile-team/docs/design/s85.md` (test checklist items 13–17), ADR-0045.

## s84: E2E tests for story threads (AC1–AC5 unit/code-review done, P1: node-harness and e2e tests pending)

Story shipped. Unit tests pass (coverage ≥99.44%, ruff clean). Code review done (all ACs pass except P1). Design rules H1–H19 all enforced.

**Your work (P1): node-harness tests and e2e for thread posting and liaison reply.**

### Node harness tests (`tests/dashboard_node.py`, three test functions)

**Setup:** Load fixture as `data.snap` with thread entries on story s5 from all four sources (human→PO, PO→human, human→liaison, liaison→human).

1. **Thread render (AC1, AC4):** `storyDetails("s5")` shows 4 entries in order (by time). Each has labels `"you → PO"` style and Markdown text (no nested `.md` div—fix m1). `NO_THREAD` text on story with no entries. With `TOKEN`, textarea/select/button present; without, read-only note. Select defaults to `"product-owner"`.

2. **`postThread` (AC1):** Blank draft sets `SEND_EMPTY` note, doesn't call fetch. Valid draft POSTs `api/thread` with `{story, to, text}` and `X-Agile-Team-Token` header. 403 response sets `READ_ONLY` note. 500 sets error text. OK clears draft and note. (Stubbed fetch, no real POST.)

3. **Timeline (AC4):** Timeline event for a thread entry shows `from: "you"`, `to: "PO"`, `what: "thread"`, body is Markdown text. Story filter in timeline includes thread entries for that story.

### E2E test for thread posting and liaison reply (REAL world, 30s timeout)

**File:** `tests/e2e/test_s84_threads_e2e.py` (new).

**Setup:**
- Real runner in a scratch team repo.
- State with at least one story (s5).
- Start dashboard with `--port 0 --token test_token`.

**Test:**
1. **POST to PO (AC1, AC2):** Make a real POST to `/api/thread` from `127.0.0.1` with:
   - Headers: `X-Agile-Team-Token: test_token`, `Content-Type: application/json`.
   - Body: `{"story": "s5", "to": "product-owner", "text": "Can you review this?"}`.
   - Expect 202 with `{"id": "t1", "status": "posted"}`.
   - Verify: `liaison/messages/t1.md` exists, begins with head `<!-- thread story=s5 at=<time> -->`, contains "Can you review this?".

2. **Watch wakes on liaison post (AC3):** POST to liaison: body `{"story": "s5", "to": "liaison", "text": "Any questions?"}`. Expect 202 with `{"id": "lp1", "status": "posted"}`. Call `agile-team watch --timeout 30` in another process/thread. Expect within 5s: `{"triggers": ["liaison_message"], "posts": [{"story": "s5", "text": "Any questions?", "at": <time>, "id": "lp1"}]}`.

3. **Liaison replies (AC3):** Call `agile-team reply s5 -` with text "Sure, all good." on stdin. Expect stdout `"replied lr1 on s5"`, exit 0. Verify: `liaison/replies.jsonl` has one line `{"story": "s5", "text": "Sure, all good.", "at": <time>}`.

4. **Thread in snapshot (AC4):** Call `GET /api/snapshot`. Expect `"thread"` array with 3 entries: t1, lp1, lr1, in time order. Expect `"events"` includes 3 `thread` events (ids `thread-t1`, `thread-lp1`, `thread-lr1`), no `message` event for the `reply` outbox line (if any).

**Coverage:** Verifies localhost + token gate (202), file writing, watch trigger, CLI reply, and snapshot merge.

See design `agile-team/docs/design/s84.md` (test checklist items 14–16, e2e), review round 2, ADR-0044.

## s83: E2E tests for Backlog tab (AC8, P1: node-harness and e2e tests pending)

Story shipped. Unit tests pass (coverage ≥95%, ruff clean). Code review done (all ACs pass except P1, which is your work). 

**Your work (P1): node-harness tests and e2e for dashboard reorder.**

### Node harness tests (`tests/dashboard_node.py`, four test functions)

**Setup:** Load fixture as `data.snap` with backlog stories (s5, s6 in sprint 1; s50, s51 in backlog).

1. **Expand/collapse (AC2):** `toggleRow("s5")` → expanded with story file content and state fields. `aria-expanded="true"`. `toggleRow("s5")` again → collapsed, details gone. Prelude's `fetch` rejects (offline), so story file shows `no story file`.

2. **Handles (AC4):** Backlog rows (s50, s51) have `<button data-move="up|down|top">`. Current-sprint rows (s5, s6) have no `data-move` buttons. Without TOKEN, no row has handles and note reads "read-only" text.

3. **`moveTarget` edges (B9):** From place P (1-indexed):
   - `moveTarget("up", 1, 2)` → null (already first).
   - `moveTarget("up", 2, 2)` → 1.
   - `moveTarget("down", 2, 2)` → null (already last).
   - `moveTarget("down", 1, 2)` → 2.
   - `moveTarget("top", 2, 2)` → 1.
   - Invalid place or action → null.

4. **`reorderNote` cases (B16):**
   - Pending: "waiting for the runner: moves apply between steps".
   - Applied: clears note (empty string).
   - Refused (generic): shows reason text.
   - Refused (STALE): shows reason + reload button with `data-reload` (calls `location.reload()`).
   - No token (403): "read-only: open the link the dashboard printed (it carries the token), on this machine".
   - Other HTTP error: status number (e.g., "404").
   - Network error: error message or generic "network error".

Bonus (from review D2): **No drag posts while pending.** Fixture has request with status="pending". `ui.reorder` set. Drop on another Backlog row posts nothing.

Bonus (from review D4): **Commits shown.** Give a fixture story a `commits: ["abc123"]`. Expanded details show it under state fields.

### E2E test for reorder request (REAL world, 30s timeout)

**File:** `tests/e2e/test_s83_reorder_e2e.py` (new).

**Setup:**
- Real runner in a scratch team repo (via `isolated_git` + `scratch_team`).
- State with sprint and backlog stories.
- Start dashboard with `--port 0 --token test_token`.
- Verify server is listening and token in URL.

**Test:**
1. Make a reorder POST from `127.0.0.1` to `http://localhost:<port>/api/reorder` with:
   - Headers: `X-Agile-Team-Token: test_token`, `Content-Type: application/json`.
   - Body: `{"story": "s50", "position": 1, "version": "<current_version>"}`.
2. Expect 202 response with `{"id": "r1", "status": "queued"}`.
3. Let router run one tick (call `router._tick()` or wait one heartbeat).
4. Check: `state.reorders["r1"] == "applied"`, order changed (s50 moved), event emitted with `source: "human (dashboard)"`.
5. Snapshot now shows `reorders[0].status == "applied"`, `reorders[0].story == "s50"`.

**Coverage:** Verifies request queueing (202), routing's apply (event, order, state), and snapshot reflects the change.

See design `agile-team/docs/design/s83.md` (test checklist items 18–23), review round 4, ADR-0043.

## s15: E2E tests for Markdown rendering (10 cases, all pass)

Story complete. Dashboard Markdown rendering via markdown-it now tested offline with vendored library copy. File: `tests/e2e/test_dashboard_markdown_e2e.py`.

**What to verify:**
- **Pin and copy agree (AC4):** Parse `MARKDOWN_URL` from page script, version matches `markdown-it-<v>.min.js` file.
- **Syntax (AC1):** All elements render (headings, paragraphs, lists, emphasis, code, tables, links) and output starts with `<div class="md">`.
- **Links (AC2):** https/http links get `target="_blank"` and `rel` with `noopener`, autolinks work.
- **Payloads inert (AC2):** 14 inputs (script, onerror, javascript:, data:, vbscript:, mailto:, relative, image, iframe, escaped quote) render with no `on*` attrs, no unsafe schemes in href, all tags in safe set, script input shows `&lt;script&gt;`.
- **Plain fallback (AC4):** Unloaded `md()` returns `<div class="md plain">` + escaped text; null/undefined give empty div.
- **Load failure (AC4, M8):** Node import fails (offline), promise resolves, markdown stays null, `md()` stays plain.
- **Questions use md (AC3):** Open/raised/answered questions render with Markdown (bold, code, lists in q-answer).
- **Timeline picks by kind (AC3, M10):** step-end/message/answer use md; gate/hold use esc.
- **One function, no copies (AC1, M1):** `markdownit(` once, `function md(` once, `.render(` on markdown once (regex `\bmarkdown\.render\(`).
- **Old rule updated:** E2E URL scan verifies exactly two pinned URLs (Mermaid + markdown-it).

Use `dashboard_node.run_page()`, vendor copy in tests/ with `useMarkdown(require(...))` (CommonJS under node). Parse HTML output with `html.parser`. No node? Hand off blocked; ask for file.

See design `agile-team/docs/design/s15.md` (rules M1–M12, test checklist), ADR-0042.

## s51: E2E test for router priority ranking (AC7 pending, unit and review complete)

Story complete on units (coverage 99.41%, ruff clean) and code review. E2E tests belong here. Design calls for one case: with started and not-started stories, router picks the started one first. File: (tbd) router e2e test. **Setup:** state with 4 stories (order=["s45", "s38", "s21", "s50"], s45/s50 not started, s38/s21 started with commits). **Test:** Router calls `dispatch.router()`, first routable story is s38 (not s45). When s38 held, s21 is next. When s38 released, s38 is next again. Covers AC1 (in-progress first) and AC4 (held story skipped).

## s65: Git confinement—build demos in the presentation workspace (AC9 e2e test, all pass)

Story accepted. Runner now isolates roles' git to prevent reaching the team repo. **For your presentations:**
- **Workspace location:** `.team/run/presentation/<story>/workspace`. Runner creates it with `git init` on first use, keeps it on bounce.
- **Where git works:** Build demos *inside* `workspace/`. Commands that work: `cd <ws> && git init demo`, `git -C <ws>/demo commit …`, `git -C <ws>/demo rebase main`, `git clone demo copy`, `git -C <ws>/demo checkout -b topic`. Commits and pushes all allowed inside workspace.
- **What's blocked:** Git targeting the team repo or outside the workspace is denied: `git -C <team> status`, `cd <ws> && git clone /etc /tmp/x`. Git outside the workspace is read-only in your cwd only: `git status`, `git log` in the cwd pass; `git commit` in the cwd is denied.
- **Environment:** Git can't climb above `.team/run` (ceiling set by runner). If your demo has no `.git`, `git status` fails with "not a git repository", not reaching the team repo.

See AC9 e2e test design, `agile-team/docs/design/s65.md`. Workspace is your story's sandbox; keep it clean between steps (ACM: you may wipe it by overwriting files, but only you do).

## s59: E2E tests for rebase at sprint start (AC6, five cases, carried to this step)

Story complete on units and integration. Unit tests cover pairing, remap, rebase, conflict, push guard, sync_from order, group_files. E2E tests (5 cases on real git) belong here. File: `tests/e2e/test_s59_rebase_e2e.py` (30s timeout).

**Five cases (design test checklist, lines 217–222):**
1. **All already upstream:** Team commits A, B. Origin/main has A', B' (rebased copies). Sync gives `rebased`, HEAD equals origin/main, tree equals origin/main's, state.json story commits map to origin/main's sha.
2. **Copies plus new content (m54 case):** Team has A, then B editing A's lines. Main has A' (copy) and unrelated U. Merge would conflict; sync gives `rebased`, history is linear (no merge commits), B's content is kept, U is present, B's recorded hash is rewritten.
3. **Real conflict:** Main changes a line differently from team. Sync holds `sync_conflict`, HEAD unchanged, no `.git/rebase-merge`, hand-over lists files grouped by directory with count.
4. **Hash rewrite in state.json:** After rebased, every `REMAPPED` field holds a commit reachable from HEAD; `upstream.checked` unchanged; `state.checkout.head` equals HEAD.
5. **Hand rebase after conflict:** After conflict, test rebases by hand in clone and calls continue. Second sync is `current` by HEAD but remaps from `sync_from`, so story hashes point to hand-rebased commits.

**Setup:** Bare origin + clone, `set_git_identity`, `isolated_git` fixture. Never touch real home directory.

See design `agile-team/docs/design/s59.md` § Test checklist, AC6 (e2e cases), ADR-0041.

## s81: E2E test for CI with stub gh on PATH (AC7, carried to this step)

Story accepted. All ACs pass except AC7 (e2e test), which is your work. New file `tests/e2e/test_s81_ci_e2e.py` (REAL world, 30s limit).

**What to build:**
1. Stub `gh` script in `tmp_path/bin`, first on PATH via `monkeypatch.setenv("PATH", ...)`.
2. Stub records its argv to a file.
3. Answers: `pr checks N --watch` (exit 1), `pr checks N --json …` (one fail check with Actions job link), `run view --job J --log-failed` (log with `FAILED tests/x.py::test_y` line).
4. Test: `CiWatch(GhPrs(command_runner(tmp_path)), 30).results([entry])` → RED with that failing line.
5. Assert stub argv: `pr checks N --watch`, `--json name,state,bucket,link,workflow`, `run view --job J --log-failed`.
6. Never touch real HOME.

**Setup:** `entry = StackEntry(pr=5, mode=PrMode.READY, branch="review", url="https://…#5")`. Command runner uses `tmp_path` repo.

The test is integration (real CLI-like gh stub), not unit. Covers the full wait/read/log path. Existing `test_ci_git_e2e.py` test name available if needed.

See design `agile-team/docs/design/s81.md` § Test checklist, AC7.

## Scope (unchanged)

E2E tests only. Run by file name (`pytest tests/e2e/test_s81_ci_e2e.py`). Never full suite or `--cov`. Real OS and clock; 30s timeout. No monkeypatch for `system.<name>` (use real calls). Moved tests from unit use `parents[4]` (one more parent level). Coverage ≥95%, ruff clean.
