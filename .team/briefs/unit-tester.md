# Unit Tester: Current context and conventions

**Last updated:** 2026-10-10 (s8 done)

## Process constraint: developer cannot edit tests

The developer role cannot write to `tests/unit/` or `tests/conftest.py`. The runner will not route feedback from failed test runs back to the developer.

**Your responsibility:** Before finishing, re-read every test expectation against the actual design delivered. If a test passes but doesn't match what the developer built, update the test (not the feature). Ask the developer for clarification only if the design itself is ambiguous.

This is your checkpoint; no other role will catch it. Coverage, ruff, and the AC are necessary but not sufficient.

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
