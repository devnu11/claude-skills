# Integration Tester: Current context and conventions

**Last updated:** 2026-10-11 (s30 done)

## s30: Dispute gate compares content, not commits

E2E tests for the dispute gate now verify that it compares the disputed test file's **content hash** (ignoring whitespace and comments) against a baseline stored at dispute raise time. Test cases: unchanged file bounces with exact reason text (test id, file, baseline[:12]); cosmetic fix (comments/blanks only) bounces; real fix passes; file now missing passes; confirmed disputes pass without reading. Also verify: path resolution through `git ls-files` (exact + suffix match), unresolvable files bounce to `implement` with `UNTRACKED` text and no `test-dispute` event, legacy disputes (before s30) pass with `LEGACY_PASS`. See design `agile-team/docs/design/s30.md` (E2E checklist).

## s11: Test disputes in e2e flows

Test disputes are a developer → tester → architect route for resolving test/design contradictions. Your e2e tests verify that:
1. A developer's dispute at `implement` (test id, rule, reason) sends the story to `tests` with no bounce.
2. Tester fixes the test (file changed, git diff exit 1) → story passes to `implement` (dispute cleared, no handover).
3. Tester confirms the test (changes_requested, next_role: architect) → story goes to `design` (dispute stage confirmed), architect rules, goes back to `tests`, then `implement`.
4. Free disputes: first `round_cap` disputes per story don't count rounds; later disputes cost 1 round each.
5. Rulings apply at any step; unapplied ruling shows why in report (no-story, done story cases).

See ADR-0018, design `agile-team/docs/design/s11.md` (test checklist section 7 covers end-to-end flows).

## s9: Interrupted steps—edits saved and offered in next brief

When a step is cut short, the runner saves its edits in a commit and reverts it. On resume, the runner offers the sha to the next step on that story via the brief. Your tests should verify the full cycle:

- **Interrupted step with edits:** A role writes both in-scope and out-of-scope files, then gets interrupted (error, limit, SIGTERM, or kill -9). Both files are in the saved commit; out-of-scope ones are quarantined again on cherry-pick.
- **Resume after interruption:** `start --resume` detects the in-flight step, saves it (cause matches the interrupt kind), and the resume prompt lists it with the sha. Status shows `interrupted: true, status: "interrupted"`.
- **Offer in next brief:** The next role on that story gets the brief line `Interrupted work: …` with the exact `git cherry-pick -n <sha>` command. It remains until the story's step settles.
- **Settlement clears the offer:** A clean settlement (any verdict) clears the interruption from that story; later steps do not see it.
- **Live scenario (AC5 verified):** Stale `runner.pid` with state `running` and `in_flight` set → `agile-team status` reports `status: "interrupted"`, `running: false`, with `in_flight` and `interrupted` shown. No process behind it.

Test areas from the design (checklist sections 2, 4, 5, 10, 11, 13):
1. Halt flow captures edits and clears in-flight on settlement.
2. Resume after kill detects stale pid and saves (cause `killed`).
3. Next brief on story includes the offer (with sha from state, not memory).
4. Status keys `in_flight`, `interrupted` appear in the report.
5. Snapshot in mock mode shows `in_flight`, `interrupted` fields.

See ADR-0017, design `agile-team/docs/design/s9.md` for exact strings and module changes.

## s40: Snapshot now includes priority and wait state

The snapshot and state.json now carry explicit priority information:

- **`state.json`:** `order` field holds the queue (list of unfinished story ids in priority order). Legacy files without it load with `[]`.
- **Snapshot stories:** Each story now has `position` (1-based int or null when done), `in_progress` (bool), `hold` (reason string or null), and `wait` ({reason, on} or null).
- **Observable on the board:** Stories show `#<position>` in the id line. Held or blocked stories show `⏸ <reason>` pill and `waits on:` line with the full reason they can't move.
- **Fixture updates:** `run.order` key added. Stories listed in ranking order (not creation order). At least one held story with open question naming it, showing the `wait` structure.

For your presentations, note that `state.order` is now part of the state, and stories' `position` and `wait` fields are observable on the board. See ADR-0016, design `agile-team/docs/design/s40.md` (rules D1–D5).

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

## s26: Self-contained presentations and the e2e gate trial

The e2e gate now tests service delivery liveness before the Proxy runs. Your presentation must be self-contained (no repo paths). Key changes:

- **Self-contained rule (L13):** The Proxy's sandbox can't read repo paths. Include only copies of what the customer needs (ADR, protocol section, files to try) and captured command output (test, ruff results with command and exit code). No repo paths in PRESENTATION.md.
- **Gate trial (L10):** For `web` deliveries, the gate runs a `Trial` from your presentation: starts the service, probes it, stops it. `NotUp` bounces to e2e (round +1, reason has command output). Port conflict holds (no round, hand-over to PO). Pass means something answered.
- **Clean up your own server:** If you start a service for your own testing, stop it before handing off. The gate will start one too; if your port is in use, the gate holds and the PO must fix it.
- **Web delivery recipe:** Same as cli (init, add state files). Before handing off: `agile-team dashboard --no-open --port 0` prints a URL; `curl <url>api/snapshot` returns 200 JSON.

See ADR-0013, design `agile-team/docs/design/s26.md` (rules L3, L10, L13, reason strings).

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. On resume, check the current sprint and story state before your first step.
