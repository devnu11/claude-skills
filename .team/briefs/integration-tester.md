# Integration Tester: Current context and conventions

**Last updated:** 2026-10-13 (s85 P1 pending; s84 P1 pending; s83 P1 pending)

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
