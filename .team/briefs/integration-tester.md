# Integration Tester: Current context and conventions

**Last updated:** 2026-10-12 (s15 done)

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
