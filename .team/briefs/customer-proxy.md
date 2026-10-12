# Customer Proxy: Current context and conventions

**Last updated:** 2026-10-12 (s71 done)

## s71: Unit tests touch no OS (P1 seam, files, clock)

The runner's unit tests are now isolated from the OS. What this means for you:

- **No test pollution:** Unit tests run in a fake OS in memory. No tmp files left behind, no real git commands, no process signals. Clean isolation.
- **Realistic failures:** Tests script disk-full, permissions, missing files, hung processes—scenarios hard to create in real tests.
- **Safe refactors:** Moving OS calls or renaming functions is caught at test time by an audit hook.
- **Real files separate:** Tests that need the real OS live in `tests/e2e/`. Acceptance tests are separate and always real.
- **Three phases:** P1 (s71, done) covers files and clock. P2 (s76) covers processes and network. P3 (s77) covers runtime. During migration, P1 and earlier tests run on the real seam (LEGACY flag).

If you find a test that shouldn't be isolated or should move to e2e, note it in your handoff. See ADR-0036, design `agile-team/docs/design/s71.md`.

## s44: Live spend meter and runner health manual testing (six items open)

Unit and E2E tests pass. Your manual acceptance testing verifies the smart pill, flow-box stats, and alerts work in a real run. From design section Manual test checklist:

1. **Smart pill live (P3):** During a real step, the pill shows `● {role} on {story} · {rate}/min {sparkline} · {age}` with health colour (green/amber/red), and its details show model, tokens, dollars, current tool, and last turn time.
2. **Flow-chart stats (F4–F6):** Boxes show `{model} · {tokens} · {cost}` totaling the ledger for Story/Sprint/Run scope. Active step box shows live rate, sparkline, turn number, and scope total. A role never touching the focus story is dimmed.
3. **Red alert on tab (A1):** When health turns red, tab title gets `⚠ ` prefix. When it clears, prefix is removed.
4. **Desktop notification (A2):** On `localhost` (secure context), clicking anywhere on the page asks for permission once; a change into red fires a notification with the reason.
5. **LAN fallback (A2, A7):** Over the LAN by hostname (not `localhost`), notifications are blocked by the browser (not secure). Instead, the tab title gets `⚠` (same as localhost). Both show the reason in the pill details.
6. **Graceful stop is neutral (D4, R15):** Use `agile-team stop` (not `stop --now`). The pill shows `● stopped` in plain (idle) colour with no `⚠`, no notification, no watch alert. A later `stop --now` or halt does show red.

Check:
- Pill text correct format, colour matches health level, hover shows details
- Flow boxes show right scope totals, active box has live sparkline and rate
- Tab title `⚠` on red, plain otherwise
- Notification (localhost) or tab title (LAN) on red, clears on green
- Graceful stop neutral; halt red

See ADR-0032, design `agile-team/docs/design/s44.md` (rules P1–P8, F4–F6, A1–A4, R15).

## s41: Sandbox cannot kill the runner; your Bash cannot kill by name or runtime

The runner found what SIGTERM'd a prior step: the agent's own `ps aux | grep` matched its CLI, so it ran `kill`. Two fixes now in code prevent this. For your acceptance testing:

**Runner side (AC2, AC3):** The sandbox signals only process groups it created (pgid == pid). Reused pids are detected via start time check and rejected. Test: `stop_stale` with old pid file mtime leaves process alive (reused pid); with runner's own pid sends nothing; with same-group pid sends nothing.

**Your side (AC4):** Bash commands with `pkill`, `killall`, `kill $(…)`, `kill <runner_pid>`, or `kill <same-group_pid>` are denied at dispatch with a clear error message. You cannot accidentally kill the runner or agent. Test: `kill <own pid>` denied (reproduces incident); `ps aux | grep python | awk '{print $2}' | xargs kill` denied as run-time target; `cmd & PID=$!` … `kill $PID` allowed.

**In acceptance:** Verify the guard works: try a denied command and check you see the error before it runs. Verify the sandbox safety: capture a `ps` output showing multiple processes, verify that `stop_stale` with an old pid file doesn't kill them (reused pid safety). See design `agile-team/docs/design/s41.md`, ADR-0031.

## s43: Gate timeouts; hung tests named; wait rules enforced

Gate commands (tests, coverage, boundary checks) now have a timeout to prevent hung tests from hanging the runner. Key acceptance criteria:

**AC1:** Gate commands have a timeout set in `.agile-team.toml` with sensible default (300s). Command that outlives its timeout is killed (process group only), and gate bounces.

**AC2:** Bounce reason names the hung test (e.g., from faulthandler or per-test timeout), so developer and tester know what to fix. Timeout with no test names still bounces with command and time limit.

**AC3:** Per-test timeout set in pytest config (pytest-timeout, timeout = 30), so hanging test fails by itself instead of waiting for gate's timeout.

**AC4:** Bash commands with bare `until` or `while` loops (no deadline) are denied at dispatch. Developer must add `timeout` wrapper or bounded `for` loop.

**AC5:** The s29 hung test (`test_a_held_boundary_waits_when_a_question_is_open`) injects `sleep` instead of waiting on real wait. Test is present, not skipped or deselected.

See ADR-0030, design `agile-team/docs/design/s43.md` (AC1–AC6, test checklist).

## s62: Liaison commands in the runner; self-hosting available

The liaison now runs acceptance tests in a self-hosted copy of the runner, not the working repo. The human can use `agile-team tell` and `agile-team watch` as part of the standard tooling (not private scripts). For your acceptance testing, the key change is that the runner can be pinned, so the team can safely edit the runner while it is running on a pinned copy.

**For AC testing:**
- **AC1–AC2:** `tell` and `watch` commands work as documented in SKILL.md; test that messages queue and watch exits with JSON.
- **AC3:** Dirty tree after a halt is recovered on resume without a wrapper script.
- **AC4:** `pin-runner.sh` script builds and pins a runner copy; documented self-hosting pattern works.
- **AC5:** No new docs defects; `--frozen` on all uv commands, `--locked` in CI.
- **AC6–AC8:** Integration with s61 (checkout guard), s9 (salvage), and s47 (answer delivery).

See design `agile-team/docs/design/s62.md` (AC1–AC8) and ADR-0029.

## s61: Halt on external checkout changes

The runner now halts immediately when the checkout changes under it (branch switched, commit reset, HEAD detached, rebase in progress). This prevents silent corruption when the human or another script modifies the tree during a run.

**What you'll see:** Halt with status `checkout-changed` (red on the dashboard). Reason says what was expected and what was found, plus the reflog entry that moved HEAD. The human then either:
- Accepts the new state: `agile-team accept-checkout`, then `agile-team start --resume`
- Restores the branch/commit: `git checkout <branch>`, then `agile-team start --resume`

**In your acceptance tests:** Verify the halt mechanism works: that the runner stops before running further steps, that the question text is exact, that `accept-checkout` updates the record, and that the dashboard shows red. See design `agile-team/docs/design/s61.md` (rules K1–K10, AC1–AC7).

See ADR-0028.

## s4: Dashboard backend – snapshot builder, read-only SSE server

The dashboard backend is live. For acceptance testing, you need to understand the snapshot contract:

- **The snapshot is raw data:** The server returns exactly 11 keys: `generated_at, run, pipeline, roles, stories, requirements, events, ledger, messages, answers, upstream`. Each key holds arrays or objects as they are, with no aggregation.
- **Views are derived in the browser:** The dashboard's UI (`index.html`) reads the snapshot and computes board columns, flow stats, token totals, requirement coverage, and questions lists from the raw data.
- **What this means for your AC testing:** You test the snapshot format (AC1–AC3, AC4), the server routes and SSE (AC4), and the CLI (AC5–AC6). The UI rendering is tested by s5 (the live UI); you do not test views here.
- **Snapshot shape:** The fixture `agile-team/dashboard/fixtures/snapshot.json` is the API contract. After a JSON round-trip, value types and keys match the fixture. Missing run files give empty sections.
- **Server is read-only:** Three exact routes: `GET /` (index.html), `GET /api/snapshot` (JSON), `GET /api/stream` (SSE). Any other path is 404. No file paths built from requests.
- **CLI command:** `agile-team dashboard [--host 0.0.0.0] [--port 8765] [--no-open]`. Binds first, prints the bound URL (so `--port 0` shows the real port), opens the browser (unless `--no-open`), and serves.

See ADR-0027, design `agile-team/docs/architecture.md` § "s4: Dashboard backend", and review `.team/reviews/s4.md` for AC coverage and captured-tests.txt for the 14 e2e test cases (99.68% coverage).

## Recent steps

## s58: Your sandbox can reach the local service

The runner now configures the OS sandbox to allow local binding (`network.allowLocalBinding: true`) for service deliveries (those serving on localhost). You can now curl the service from inside your sandboxed Bash commands without "connection refused". The service is fresh for each Proxy step (started by `plan()` in the `prepare_fn`). Docs updated: protocol.md, SKILL.md. See ADR-0026, design `agile-team/docs/design/s58.md`.

## s47: Halt notes show what run was waiting on when halted

When the runner halts (e.g., `stop --now`) while questions are open, the halt note now includes what it was waiting on: `…; waiting on answers: s40 waits on m42; the run waits on m43`. This helps you understand what needs answering before resuming. No change to the halt's exit code, status, or stored reason. See ADR-0025, design `agile-team/docs/design/s47.md` (W5).

## s46: Dispute brief now includes test output

When a test dispute is open, the brief shows the test command output captured when the dispute was raised. This helps the acceptance tester see what failed and decide if the test or the design needs to change. The output line appears only if the command produced output; if the test passed, the line says so. See ADR-0024, design `agile-team/docs/design/s46.md` (D1–D3).

## s45: Crash log now captures exceptions with tracebacks

Role steps that crash now write their tracebacks to `.team/run/crash.log` for diagnosis. Each crash goes to the log exactly once. This does not affect your acceptance testing; it is for the team to diagnose runner issues.

## s21: Dashboard features: toggle, live budget, Done column

Three dashboard features shipped. Your manual testing verified all ACs; note the caveat:

- **AC1 toggle:** Click "Tokens" or "Dollars" on the "Tokens by" chart; choice persists across live updates (do not refresh).
- **AC2 live budget:** Edit `.agile-team.toml`, change `budget_usd`, save; within ~1s the header and Spend tile show new value.
- **AC3 Done column:** At 1280px wide, board shows all columns (Backlog, 8 steps, Done) without scrolling; even with cards in every column.
- **Caveat:** Board tested with empty columns only. Full-board integration test at 1280px (all columns with cards) is pending in a follow-up story.

## s11: Test disputes in acceptance testing

Your acceptance tests may encounter stories with open test disputes (developer claimed test contradicts design). The brief will show `Test dispute (raised): {test} contradicts {rule}: {reason}` or `(confirmed)` if the architect has ruled. This does not affect your testing; it just means the story's tests are under review at the same time. See ADR-0018, design `agile-team/docs/design/s11.md`.

## s9: Interrupted steps—edits saved and offered to next role

When a step is cut short (error, limit, SIGTERM, kill -9), the runner saves its edits in a commit and reverts it. On resume, the prompt offers the sha to the next role on that story. Your acceptance tests should verify the lifecycle:

- **Status after interrupt:** When you start an acceptance step, `agile-team status` may show `status: "interrupted"` (instead of `running`). This means a prior step was cut short; edits are saved.
- **Interrupted work in your prompt:** If an earlier step on the story was interrupted, your brief includes `Interrupted work:` with a `git cherry-pick -n <sha>` line. Reuse the edits if they are relevant; cherry-pick will quarantine out-of-scope files.
- **Live AC5:** Verify that a stale `runner.pid` (dead process) is handled correctly: `status` reports `interrupted: true, running: false` with `in_flight` and `interrupted` data shown, not `running: true` with a dead pid.

Your presentation should include a state file (e.g., captured from `agile-team status`) showing:
1. `running: false, status: "interrupted"` when a step was cut short and the process is gone.
2. `in_flight: {role, story, brief}` when a step is in progress.
3. `interrupted: [{role, story, brief, cause, sha}, ...]` for the pending list.

See ADR-0017, design `agile-team/docs/design/s9.md` (rules I13–I14 for status shape).

## s40: Board now shows story priority order and hold reasons

The board shows the order stories will run in and why any are held:

- **Priority order:** Each story card shows `#<position>` (e.g., `#1`, `#2`) indicating its place in the queue. Smaller numbers run first.
- **Hold indicators:** A held or blocked story shows a `⏸` pill with the reason (questions, manager, round cap, held, or needs the human) and a line `waits on: <reason details>`. This tells you why the story isn't moving.
- **Observable behaviour:** Held stories keep their position number even when the router skips over them. Once released, they run from their original place in the order.

The order and hold state are now observable on the dashboard board view and in the snapshot. See ADR-0016, design `agile-team/docs/design/s40.md` (rules D1–D4).

## s19: Runner calls you automatically from the pipeline

The runner now automatically calls your acceptance step when a story completes review (no PO mediation). Your step is called with a standard brief (story file, design, review, previous handoff). The same goes for all other steps: the router drives them. You will see the PO only if a hand-over trigger matches (open questions, blocked story, quarantine, etc.). Otherwise, the runner carries on.

See ADR-0009 for the routing architecture.

## The team presents the product, not the environment (s13)

You cannot build, install, initialise or repair environments. The team's Integration Tester prepares every environment your step needs: a ready-made workspace with state the story's ACs require. You run acceptance tests against what is already there.

If the environment is missing or broken, stop and return `changes_requested` with `next_role: integration-tester`, saying what is wrong. Do not work around it.

## What the team presents (s13)

When you start an acceptance step, the runner copies the team's presentation to your sandbox:

- **Location in your sandbox:** `<sandbox>/presentation/`
- **What it holds:**
  - `PRESENTATION.md`: a guide written by the Integration Tester describing what to try for each acceptance criterion
  - `workspace/`: the ready-made project you work in (for `cli`, `dashboard`, `library`, `harness`, `package` kinds)
  - Other files: sample data files, live-status.json (captured from a live run), or reference projects
- **How to use it:** Follow `PRESENTATION.md`. For `cli` kind, work in `workspace/` as cwd. For `web` kind, use the browser at the URL in your prompt.

Missing or incomplete presentation: return `changes_requested` to `integration-tester` with a description. The runner will move the story back to e2e (no round counted) for the tester to build the presentation and re-run the gate.

## Read and write your acceptance report (s13)

You can read, write and rewrite `.team/acceptance/<story>.md` across steps:

1. When you start an acceptance step, if your report exists from a prior step, Read it first
2. Rewrite it with your updated findings
3. On a later step on the same story, you can read and update it again

This is enforced: Read requires that you have read the file before you can Write (no overwrite without context).

## Sandbox and forbidden roots

Your read/write sandbox and forbidden roots are tightly controlled:
- **Read:** sandbox, `.team/acceptance/` (your reports), `.team/stories/`, and `<docs-dir>/customer/`
- **Run:** the installed CLI from your sandbox
- **Write:** sandbox and `.team/acceptance/` (your reports only)
- **Forbidden:** source code and test directories; nested roots are handled—e.g., `agile-team/docs/customer/` is readable even though `agile-team/runner/agile_team/` is forbidden

Details: `reference/protocol.md` Enforcement section; s7 implemented nested root depth.

## s26: Service is already running; return without billing

For web deliveries, the runner has already started the service and tested it (gate trial). Your step runs the service that is already listening. Key changes:

- **Service already up (L4–L5, L10):** For `web` kind, the delivery's service is running when your step starts. Do not start, stop, or restart it—your `finally` block will.
- **If it stops answering (L11):** Return `changes_requested` with `next_role: integration-tester` saying what you saw. The runner won't bill you (return path with no round).
- **Returns are cheap (L8, L11):** If the runner's prepare fails, you don't run and nothing is billed. If your query runs and you return, the cost is ledgered (same as other steps).

See ADR-0013, rules L4–L5, L10–L11.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. Only sprint stories can run acceptance. On resume, check the current sprint and story state before your first step.
