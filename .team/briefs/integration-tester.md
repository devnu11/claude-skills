# Integration Tester: Current context and conventions

**Last updated:** 2026-10-10 (s8 done)

## Write scope: tests/e2e only

Your writes are limited to `tests/e2e/`. Regression rows for unit-level code failures must either:
- Go into `tests/e2e/` if the failure shows up in end-to-end tests, or
- Wait for the Unit Tester to add them to `tests/unit/`

Do not attempt to edit unit tests; the runner enforces this. When you find a unit-level bug, document it clearly in your handoff so the Unit Tester can add appropriate coverage.

## s8: Clean halt – mandatory e2e regression tests

Code review (round 2) deferred three test cases to your scope because they need the full harness (fake query_fn, scratch git repo):

1. **D1 fixed:** Limit error reason strips ` (exit code: 1)`. Test: build a `ResultError` with `exit_code=1` (as the SDK does), include a trailing `errors` list, verify the exact AC1 reason (no exit code suffix, ends at semicolon if present).
2. **D2 fixed:** After a role step halts with a limit, both uncommitted in-scope and out-of-scope edits stay as-is. Test: role writes one file inside PO scope and one outside, then raises limit. Verify both files are uncommitted, HEAD unchanged, no QUARANTINE event, story step/rounds unchanged.
3. **Regression:** An empty limit error message. Test: a limit with no reset time or kind phrasing. Verify it classifies as a limit (not a crash) and reason is extracted (or defaulted).

## s5: Dashboard live UI – manual acceptance checklist

Customer-proxy reported s5 done (AC2–AC7 verified, AC1 reconnect by simulation, AC8 not runnable by them). Manual checks for you:

1. **Live updates:** Run `agile-team dashboard --port 0 --no-open`, open the URL, touch `.team/run/events.jsonl`. The page updates without a refresh (via EventSource).
2. **Reconnect:** Stop the server, restart on the same port. The status pill goes "reconnecting…" and back to "live" once the server is ready.
3. **Mock replay:** Open `/?mock` from the file (`index.html` as a local file). All five tabs render: Flow (Mermaid graph), Board (cards), Tokens (bars + chart), Questions (two lists), Requirements (tiles + matrix).
4. **Themes:** Toggle ◐/☀/☾ buttons. Dark mode is usable; colors match CSS tokens. `prefers-color-scheme` is respected by default.
5. **Error recovery:** Break a file in `.team/run/` (e.g., truncate `events.jsonl` mid-line). The dashboard reconnects and renders without crashing. A render error pill appears in the status row if needed.

Known gaps:
- No executable test for live dot animation or halo movement. These were verified by hand in headless Chrome (ADR-0003).
- Without internet, Flow shows source text instead of diagram (Mermaid off CDN). Other tabs work offline.
- Dashboard does not show AC1 (reconnect after server restart) in a way that automated tests can verify; simulation confirms it.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. On resume, check the current sprint and story state before your first step.
