# Integration Tester: Current context and conventions

**Last updated:** 2026-10-12 (s81 done, e2e pending)

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
