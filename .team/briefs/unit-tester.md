# Unit Tester: Current context and conventions

**Last updated:** 2026-10-10 (s13 done)

## Process constraint: developer cannot edit tests

The developer role cannot write to `tests/unit/` or `tests/conftest.py`. The runner will not route feedback from failed test runs back to the developer.

**Your responsibility:** Before finishing, re-read every test expectation against the actual design delivered. If a test passes but doesn't match what the developer built, update the test (not the feature). Ask the developer for clarification only if the design itself is ambiguous.

This is your checkpoint; no other role will catch it. Coverage, ruff, and the AC are necessary but not sufficient.

## s13: Team presents product in ready-made environment – test notes

Code review passed with no defects. Unit coverage for s13 is at 100%; overall stays at or above 95%.

Key test constructs and expectations:

| Aspect | Test cases | Notes |
|--------|-----------|-------|
| **E2: lay_out** | Wipes old dir, creates workspace with .git for kinds that need it, manual has no workspace, refuses `../x` before touching anything | Pitfall: pytest's `tmp_path` may be inside a git repo; use `GIT_CEILING_DIRECTORIES` |
| **E5: missing** | No dir, blank guide, guide but no workspace, workspace with only .git, complete, manual with guide only, no delivery (guide only) | Exact reason strings match design; guide checked before workspace |
| **E4: e2e done gate** | Bounce to e2e on missing, pass to acceptance on complete, `changes_requested` still bounces to named role, no acceptance step → pass without check | Rounds increment on bounce; gate checks only when acceptance step exists |
| **E6: Proxy unpresented** | Story returns to e2e (no round, no status change) on missing, gate event emitted with `verdict: "return"`, no prepare call, story stays at acceptance if complete | Refusals (backlog, done, blocked) come first; return applies only at acceptance |
| **E7: copy_into** | `shutil.copytree(symlinks=True)`, symlink stays a symlink, copy asserted inside fake runner before prepare | Symlink does not escape s7 guards (Read resolves to real path) |
| **E8: prompt_section** | With presentation: heading + path line + rule line + guide text; without: empty string | No unguarded read on stale dir (follow-up: handle FileNotFoundError gracefully) |
| **E9: Proxy read scope** | Can Read `.team/acceptance/s8.md`, denied `agile-team/runner/agile_team/cli.py`, read globs + allowed reads have new entries, `web`, `harness`, `manual` kinds have Read tool | Scope intersection: role has Read, kind has Read → tool available |
| **E11: init outside git** | `main(["--repo", str(tmp_path), "init", …])` outside git returns 1, stderr is exact `agile-team init: not a git repository: <tmp_path>; run git init first` | Use `GIT_CEILING_DIRECTORIES`; also test missing path |
| **Integration-tester write scope** | Can write `.team/run/presentation/s4/PRESENTATION.md`, denied other roles | Role scope Check |

## s8: Clean halt – test notes

Code review round 2 accepted the fixes and deferred three e2e regression tests to the Integration Tester (see their brief). Unit coverage for s8 is at 100% (halt.py, po_tools.py, dispatch.py, cli.py); overall stays above 95%.

Key test constructs:
- `conftest.RaisingQuery(exc, before=N)`: yields N messages, then raises exc (for mid-stream errors)
- Real `ResultError` must include `exit_code=1` to match SDK behavior; ` (exit code: 1)` is appended to str(exc)
- Fake limit error: `ResultError("Claude Code returned an error result: You've hit your session limit · resets 2:20pm (America/Edmonton)", data={…}, exit_code=1)`
- Trace all halt paths: PO level (cli._run), role level (Runtime._step_failed), both in one turn, resume after halt

Check that tests match the HALTS table values exactly: statuses `blocked`, `failed`, `stopped`; exit codes 75, 70, 143; note kinds and advice text.

## s5: Dashboard UI test notes

**Known gaps (by design, not defects):**
- No executable test for live dot animation, halo movement, or reconnect. These are DOM operations verified by hand in headless Chrome and in review. Add them in a follow-up story.
- No test for sparse event data handling (e.g., `sprint-start` with missing fields). The runner always writes complete data; test fixtures are the only place this happens. Consider a parametrized test for defensive rendering with `normalize()`.
- Escaping rule (ADR-0005): all snapshot strings in HTML must go through `esc()`. Tests check string presence, not injection prevention. Consider adding a test that verifies no unescaped interpolations exist in the shipping `index.html`.

Review round 1 found two defects (D1: bad Mermaid selector, D2: unescaped strings) that were fixed and verified by round 3. Round 4 fixed a crash on empty sprint-start data, verified by the customer. Tests are green at 100% coverage.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. On resume, check the current sprint and story state before your first step.
