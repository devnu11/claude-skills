# Integration Tester: Current context and conventions

**Last updated:** 2026-10-12 (s59 done, e2e pending)

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
