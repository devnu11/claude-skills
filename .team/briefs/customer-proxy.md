# Customer Proxy: Current context and conventions

**Last updated:** 2026-10-11 (s61 done, s4 documented)

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
