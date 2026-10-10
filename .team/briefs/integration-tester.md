# Integration Tester: Current context and conventions

**Last updated:** 2026-10-10 (s19 done)

## s19: Runner drives the fixed pipeline automatically

The runner now drives sprint stories through the pipeline automatically (design → implement → review → acceptance → scribe). The PO is called only for judgement (hand-overs). This means:
- **Your scope unchanged:** Your e2e steps (acceptance, e2e gate) stay in the pipeline. You are called the same way (standard brief, step request).
- **No more mid-pipeline PO calls:** Steps move continuously between your gate and the next step. If a step bounces or hands over, the PO gets control; otherwise the router carries on.
- **Integration test cases:** Your e2e tests should verify the full pipeline runs to completion (all steps, all rolls, all gates) without manual PO intervention for routing. A fake PO that yields only `done` handoffs should show every story reaching `DONE` with the scribe running.

See ADR-0009 and `agile-team/docs/design/s19.md` for the new architecture.

## Your mission: prepare the presentation for the Customer Proxy (s13)

For each e2e step, the runner creates an empty `.team/run/presentation/<story>/` directory with a fresh `workspace/`. Your job is to fill it with what the Customer Proxy will judge the product on:

1. **Build the workspace:** Follow the recipe for your story's delivery kind (see table below)
2. **Write PRESENTATION.md:** For each acceptance criterion, describe what to try and what the customer should see
3. **Capture live-run output:** For ACs that only show in a live run (sprints, stops, spend), capture `agile-team status` or other output as JSON
4. **Check before handoff:** Run the commands you document; verify the output matches what you wrote

The e2e gate will check that PRESENTATION.md exists and is non-blank, and that workspace/ is non-empty. A missing or incomplete presentation bounces to e2e with a round increment.

## Presentation recipes by delivery kind

Build the workspace the way a customer would have it after following the team's install and setup docs. The absolute path to your presentation dir is in the runner's output.

| Delivery kind | Recipe |
|---|---|
| **cli** (package) | Run `agile-team --repo <presentation-path>/workspace init --preset python --delivery package`. Then write any state files the ACs need into `workspace/.team/run/` (e.g., `state.json` with sprints or a blocked status, `outbox.jsonl` note, `crash.log` entry). For live-run ACs, capture: `agile-team --repo <presentation-path>/workspace status > <presentation-path>/live-status.json`. Before handing off: `agile-team --repo <presentation-path>/workspace status` should print the state you meant to show. |
| **dashboard** (web) | Run `agile-team --repo <presentation-path>/workspace init --preset python --delivery package`. Then add sample run files: `state.json`, `events.jsonl`, `ledger.jsonl`, `outbox.jsonl`, `inbox.jsonl` in `workspace/.team/run/`, chosen so every AC's feature shows (tabs, sprints, a bounce, a question, spend). Before handing off: `agile-team --repo <presentation-path>/workspace dashboard --no-open --port 0` prints a URL; `curl <url>api/snapshot` returns data (then stop the server). |
| **library** | A sample consumer project that uses the library, set up and tested by the customer | reference next to the empty `consumer/` project, which stays cwd |
| **harness** | Sample inputs for the listed commands | through the listed commands |
| **manual** | Only PRESENTATION.md (no workspace needed); it is the human's starting point | quoted in the prompt |
| **script** | Sample inputs the scripts run on | same as **cli** (work in workspace/) |
| **package** | A project set up the way a customer has it after following install docs | same as **cli** (cwd stays sandbox) |

## Write scope: tests/e2e and presentation only

Your writes are limited to:
- `tests/e2e/`: integration test files (for e2e regression tests and acceptance manual checklist)
- `.team/run/presentation/<story>/`: the presentation (PRESENTATION.md, workspace, live-status.json, etc.)

The runner enforces this. When you find a unit-level bug:
- Add a regression test to `tests/e2e/` if it shows up in e2e, or
- Document it clearly for the Unit Tester if it's unit-level; they will add it to `tests/unit/`

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
