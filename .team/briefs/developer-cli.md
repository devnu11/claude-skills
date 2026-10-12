# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-12 (s72 done)

See `developer.md` for the base conventions.

## s72: A 1 second limit per unit test (configuration, no new dependency)

Every unit test (outside `tests/e2e/`) now times out at 1 second via pytest-timeout. e2e tests and LEGACY files keep 30 seconds. The limit is in one place: `[tool.pytest.ini_options]` in `pyproject.toml` (`timeout = 1` for unit tests, `e2e_timeout = 30` for the real world). New `time_limit.py` module (two functions, one table) picks the right limit based on s71's "world" concept. `conftest.pytest_collection_modifyitems` wires the marker. No test is skipped, deleted, or marked; slow tests are fixed via fake clock or moved to e2e. Coverage 99.68%, all passing. No ADR (pytest-timeout already a dev dependency).

## s71: Unit tests run no OS calls — single seam with fake and audit (P1: files, clock)

Every module now imports `system` as a module (`from agile_team import system`) and calls thin functions like `system.read_text(path)`, `system.now()`, `system.run(command)`. The P1 conversions cover `state`, `ledger`, `events`, `relay`, `watch`, `halt`, `config`, `keys`, `roles`, `health`, and `live`'s heartbeat read. You also added `system.hard_link()` for relay's draft publishing. Unit tests run in a fake OS: an autouse fixture swaps every function in `system.__all__` with an in-memory fake, and an audit hook fails any test that breaks the rule. The fake records writes, can simulate failures (full disk, permissions), and holds package data (built-in roles, presets, dashboard HTML). Twelve modules defer conversions to s76/s77; their tests stay in `LEGACY` until then. See ADR-0036, design `agile-team/docs/design/s71.md` (rules O1–O17, P1 module list).

## s70: The test suite runs in parallel with pytest-xdist

The runner's full test suite now uses pytest-xdist for parallel execution on multi-core machines. Gate cycle time drops from ~4 minutes to ~1 minute on 10 cores. Key changes in your code:

- **`RunnerIds` injection:** `sandbox.stop_stale()` receives the runner's own pid and process group via `process_groups.RunnerIds(pid, pgrp)`. The runner is never signalled, even by itself. The test passes fixed fakes so its IDs are stable across workers.
- **Test parametrization:** Any test using `os.getpid()` or `os.getpgrp()` in a `@pytest.mark.parametrize` id will create different test IDs in every xdist worker, blocking the run. Avoid live values in ids; use labels like `["pid", "pgrp"]` and resolve the live value in the test body.
- **Commands use `-n auto`:** `test`, `coverage`, and targeted runs now include `-n auto`. `addopts` stays without `-n` so a named test stays serial (faster).
- **No runtime change:** pytest-xdist is a dev dependency only. The installed CLI is unchanged.

See ADR-0035, design `agile-team/docs/design/s70.md`.

## s69: Only the runner runs the full suite; you have `run_tests` and `run_new_tests` tools

Full pytest and coverage runs are now denied to all roles except devops. The runner runs them at gates and shows results in your brief (`## Runner results`). You can still run named tests:
- **`run_tests` tool:** Pass test file paths or pytest node ids (e.g., `tests/test_x.py::test_y`). The runner runs them via `[[toolchain.targeted]]` config and returns output.
- **`run_new_tests` tool:** Runs only the story's new test files (committed in this story by unit-tester).
- **Bash:** Named tests allowed: `pytest -q tests/test_x.py::test_y` passes. Full suite or `--cov` denied.

Suite denial is enforced by a guard rule: `pytest` with no specific targets, or any `--cov` flag, is denied with a message pointing to these tools. See ADR-0034, design `agile-team/docs/design/s69.md` (rules S1–S9, R1–R10).

## s68: The implement gate runs coverage once, not test then coverage

The implement → quality gate now calls `run(commands["coverage"])` exactly once. Coverage run already runs tests and provides the exit code, so no separate test run is needed. Cycle time drops from 7–9 minutes to ~4 minutes.

**Test failure detection (C6):** Test failures are detected via regex patterns `TEST_FAILURES` in the output (pytest `N failed`, go `--- FAIL:`, etc.). If a pattern matches, the bounce text is `tests fail:\n{tail(out)}`. The constant `TESTS_FAIL` is shared with `green()` for DRY.

**Coverage shortfall (C4) vs test failure (C5):** Non-zero exit can be:
- Shortfall only (coverage below threshold, no test failure detected) → bounce with coverage text
- Test failure (pattern detected) → bounce with tests fail text
- Unknown (no pattern, no coverage info) → bounce with tests fail (safe side)

**Changed methods:** `Checks.tests_green_and_covered()` now runs only coverage. `_failed_run(out)` handles non-zero exits. `green()` updated to use `TESTS_FAIL`. No gate interface change; bounce_to and event shape unchanged. See ADR-0033, design `agile-team/docs/design/s68.md`.

## s43: Gate commands have a timeout; hung tests are named, not waited on

Gate commands now run in their own process group under a time limit. When a test hangs, it is killed, its name is extracted and reported, and the gate bounces. Key decisions:

**Timeout (T1, T2):** `[gates] command_timeout_s` (default 300.0) in `.agile-team.toml` applies to all gate commands: tests, coverage, git operations, boundary checks. Each command gets its own full limit; the limit applies to every `CommandRunner` call.

**Process group isolation (T3, T4):** Commands start with `start_new_session=True` (their pgid is their pid). At the limit, `SIGKILL` signals only that pgid via `process_groups.signal_child_group()` (s41). Stdin is `/dev/null` (test gets EOF). Stdout and stderr are merged.

**Drain deadline (T5):** After the kill, `communicate(timeout=5.0)` collects output with a 5-second deadline. If that times out, captured output is `""` (nothing lost; Python keeps earlier reads).

**Hung test naming (T7, T8):** On timeout, exit code is 124 (GNU `timeout`'s code). The bounce reason holds output lines, then `TIMEOUT_LINE` ("timed out after …"), then `HUNG_LINE` (test name or fallback). The reason goes **last** so `gates.tail` keeps it. `hung_test(output)` tries `HUNG_PATTERNS` rows (faulthandler `in test_x`, traceback `in test_x`); last match wins.

**Per-test timeout (T13):** `pytest-timeout>=2.4.0` with `timeout = 30` in `[tool.pytest.ini_options]` stops hanging tests by themselves. Test name appears in the `FAILED` line, suite continues.

**Guard on wait loops (T12):** Bash commands with `until` or `while` loops (no deadline) are denied at dispatch, unless a segment starts with `timeout` or `gtimeout`. This catches the s29 accident.

**Role rule (T11):** `roles/_shared.md` gets "Never wait without a deadline" section: run suites in the foreground, give every wait a deadline (`timeout N` or bounded `for` loop), name hung tests in your handoff.

See ADR-0030, design `agile-team/docs/design/s43.md` (rules T1–T14, exact strings, test checklist).

## s41: Signal only process groups the runner created; stop killing by name

The runner found what SIGTERMed a prior develop step: the agent's own `ps aux | grep "[p]ytest"` matched its CLI (system prompt on argv), so it ran `kill` on itself. Two fixes now prevent this, both enforced in code:

**Runner side (signal safety):** The sandbox signals only a group it created. New `process_groups.py` module ensures: (1) no `killpg` on the runner's own group or a non-leader, (2) reused pids rejected by checking start time (G1–G6). Sandbox's `_signal_group`, `_end_group`, and `stop_stale` all go through `signal_child_group`. Commands calls it too.

**Your side (guard on Bash):** Commands with `pkill`, `killall`, `kill $(…)`, `xargs kill` are now denied at dispatch (K1–K4). Also denied: `kill <runner pid>`, `kill <same-group child pid>`, `kill 0`, `kill -1`. Targets like `$PID` (saved variable) pass; run-time targets do not. Role rule in `roles/_shared.md`: "Stop only what you started, by the pid you saved: `cmd & PID=$!` … `kill $PID`."

**What you'll see:** If you try `ps aux | grep python` to find and kill a process, it will be denied with a message naming the problem and how to fix it. Save the pid upfront instead: `cmd & PID=$!` … `kill $PID`.

**Residual risk (documented):** A variable target like `kill $PPID` (which in your Bash is the agent CLI) cannot be resolved at parse time and passes. K1 and K4 block common forms. This is a rule to stop mistakes, not a hostile gate.

See ADR-0031, design `agile-team/docs/design/s41.md` (rules G1–G6, K1–K5, test checklist).

## s62: Liaison commands in the runner; self-hosting and frozen uv

The runner now has `tell` and `watch` commands, replacing private shell scripts. Message delivery goes through the router (no stop/resume needed). Watch polls files with no token cost. Resume from dirty trees works via a new `unsaved` state field. Self-hosting: `pin-runner.sh <commit>` builds a pinned runner copy; unattended jobs run the pinned version with `uv run --frozen`. All documented uv commands use `--frozen`; CI uses `--locked`. Modules:

- **`relay.py`:** `Told` dataclass (id, path); `Relay.tell(text)` queues messages in `t<N>.md` files with hard-link atomicity. `told()` lists files in number order. `unread(told_ids)` computes undelivered.
- **`watch.py` (new):** `Seen` (memory file with outbox count + status baseline), `Look` (one poll's outbox + status), `TRIGGERS` table (message, status), `Watcher.until(timeout_s)` polls until fired/timeout. `line()` builds V6/V7 JSON dict.
- **`state.py`:** `told: list[str]` (delivered ids), `unsaved: Cause | None` (salvage skip reason).
- **`router.py`:** `_unread()` lists undelivered, `_deliver(answers, told)` extends state fields, saves once, returns human_message pass.
- **`recovery.py`:** `recover_killed()` → `recover_cut(run_dir, git)` picks cause (KILLED > unsaved > None), salvages, clears unsaved.
- **`dispatch.py`:** `save_interrupted` sets `unsaved` when checkout moved; `PoRun.run` clears unsaved at start.
- **`cli.py`:** `cmd_tell(source)` reads file or stdin, stores `.draft-<pid>`, links to `t<N>.md`, exits 0 or 1 (errors printed with `agile-team tell:` prefix). `cmd_watch(args, pace)` calls `Watcher.until()`, prints one JSON line, exits 0 or 130 (Ctrl-C). `status_report` adds `queued_messages`. `_recover` uses `RECOVERED_LEADS` dict (Cause → reason text).
- **`pin-runner.sh` (new):** Extracts `agile-team/runner` from git at commit into `.team/run/runner-pin/`, writes sha to `.commit`. Validates: commit exists, on-branch, has pyproject.toml, runner not running. P2 refusals checked in order; exit 2 on usage.
- **Workflows:** `uv sync --locked --dev`, `uv run --locked …`. F3: paths include unattended files.

See ADR-0029, design `agile-team/docs/design/s62.md` (rules T1–T7, V1–V8, R1–R4, P1–P3, F1–F3).

## s61: Runner halts when checkout changes under it

The runner now guards the branch and commit it runs on. It records them in `state.checkout` and checks at every opportunity (start, resume, before/after steps, gates, commits). On any mismatch (external rebase, checkout, reset), it halts with status `checkout-changed` and escalates to the human. The human can accept the new state with `agile-team accept-checkout` or restore the branch and commit, then resume. Rules K1–K10 in `agile-team/docs/design/s61.md`. New `checkout.py` module (pure, no dispatch/recovery/cli imports); `state.CheckoutRecord`; `RunStatus.CHECKOUT_CHANGED`; `cmd_accept_checkout`; `Guard` class for start/accept outside a run. Steps that already ran cost money (not refunded). See ADR-0028.

## s4: Dashboard backend - snapshot builder, read-only SSE server, CLI

The dashboard service is built. Key decisions: the snapshot builder returns raw data only (no aggregation); the browser derives all views (board, flow, tokens, questions) in JavaScript. The API contract is the fixture (`snapshot.json`), not the views in AC1/AC2. Modules:

- **`dashboard/snapshot.py`:** `build(config, book)` reads explicit files (state, events, ledger, outbox, inbox, stories, requirements) and assembles sections (raw arrays/objects). Each builder is pure and under 8 lines.
- **`dashboard/server.py`:** Read-only HTTP + SSE. `Handler.do_GET()` routes three exact paths: `/` (index.html), `/api/snapshot` (JSON), `/api/stream` (SSE). Any other path is 404. No directory serving, no file paths built from requests. `_stream()` watches files and polls for changes, sending snapshots and keepalives.
- **`cli.py` `cmd_dashboard`:** Binds to host/port, prints URL with bound port, opens browser (unless `--no-open`), serves. Uses stdlib `ThreadingHTTPServer` and `webbrowser` only.
- **Config:** `stories_dir`, `requirements_dir` properties added.

See ADR-0027, design `agile-team/docs/architecture.md` § "s4: Dashboard backend" (rules S1–S7, section shapes).

## s58: Proxy sandbox reaches local services via allowLocalBinding

Service deliveries (kinds with `Start.BACKGROUND`) get `network.allowLocalBinding: true` in their sandbox settings via a data-driven mapping. Non-service kinds have no `network` key. Changes to `sandbox.py`: constants `LOCAL_SERVICE_NETWORK` and `NETWORK_BY_START` (after `DELIVERY_KINDS`), new private `_network(prepared)` helper, `_sandbox_section` merges result with `**_network(prepared)`. Network dict is always a fresh copy. `os_sandbox_settings` docstring updated to say what the e2e test verifies and that Linux is not verified. No changes to `dispatch.py` or `presentation.py`; service lifecycle unchanged by design. See ADR-0026, design `agile-team/docs/design/s58.md` (rules N1–N4, V1–V2, L1).

## s47: Show what the run waits on; wake logic unchanged

When the router waits on open questions, `status_reason` becomes `"waiting on answers: s40 waits on m42; the run waits on m43"` (W3). When a run halts while waiting, the halt note includes this suffix (W5). The wake logic is unchanged; polling picks up answers within one cycle. New methods on `Relay` (`waits()`, `waiting()`) and `Router` (`_show_wait()`, `_clear_wait()`, `_end_wait()`); modified `halt_run()` suffix logic. Docs updated: protocol, SKILL.md, customer/routing.md. See ADR-0025, design `agile-team/docs/design/s47.md` (rules W1–W6).

## s46: Code already in passes tests gate; advance ruling; dispute output

Code commits are now recorded on every developer step (K1). At `tests`, if commits are in the branch, use rework gate instead of the red gate (K3). New `advance` ruling moves stories forward one step (A1). Disputes now capture test output and show it in briefs (D1–D3). Modules:

- **`gates.py`:** `StoryState.code_commits: list[str]`, `Checks.code_in(story)`, `Checks.code_facts(story)`, `Checks.test_output(test)`, `OpenDispute.output: str`, `Pipeline.reworked(story)`, `Pipeline._move_for(story, ruling)`, `test_name()`, `excerpt()`.
- **`roles.py`:** `RULINGS` gains `"advance"`, `Handoff.ruling_reason: str = ""`, validation for `ruling_reason`.
- **`dispatch.py`:** `_record_code(plan, sha)`, `_rework_lines(story)`, `_story_lines(story, rework)` signature change, `_dispute_lines` appends output, ruling event logs `reason` field.

See ADR-0024, design `agile-team/docs/design/s46.md` (rules K1–K6, A1–A4, D1–D3).

## s45: Crash logging, fault rulings on any story, blocked release

Manager step crash fixed, crash log now captures all role-step exceptions, fault rulings work on any story, and `continue_story` blocks release of blocked stories. Key modules affected:

- **`dispatch.py` (`Runtime`):** `run_role` wraps `_run_step`, catches and logs any exception exactly once (C1); `_run_planned` wraps `settle` (C2); `_step_failed` handles non-limit errors (C3); `_rulings` takes fault path when `handoff.fault` or `story.repeated` set (M1); `_rule_after_fault` applies fault then ruling (M5); `_fault_refusal` checks in order (M2); `_fault` reads reason before clear (M4). Helpers: `_names_fault`, `_unapplied_ruling`.
- **`gates.py`:** `ruling_refusal(story, what)` parametrized; `setback_reason(story)` reads reason before clear; `continue_refusal(story)` blocks blocked-story release (B1); `Pipeline.apply_fault` clears hold (M3).
- **`po_tools.py`:** `Tools.continue_story` applies `continue_refusal` after story lookup.
- **`handover.py`:** M7 wording for `RUNNER_FAULT_NOTE`, `OFF_PIPELINE_FAULT`, `FAULT_NOT_APPLIED`.
- **Role prompts:** `manager.md` on fault naming any story; `product-owner.md` on blocked-story refusal.
- **Docs:** `reference/protocol.md` covers crash log (C1), fault path (M1–M6), continue_story (B1).

See ADR-0023, design `agile-team/docs/design/s45.md` (rules C1–C4, M1–M7, B1–B2).

## s38: Budget correction and ceiling

Corrected PO ledger entries and enforced budget ceiling (run halts when spend reaches budget). Key changes:

- **Ledger correction (K1–K3):** `ledger.corrected()` turns legacy PO running totals (before s25) into own costs with `SessionCost`. `Ledger.entries()` returns corrected; `_raw()` returns as-written. `budget_status` adds `"po_overcount_usd"`.
- **Ceiling enforcement (B1–B3):** `Runtime.enforce_ceiling()` halts when corrected spend ≥ budget. Checked after role steps land (`run_role`), after PO queries ledger (`_record`), at start before PO opens (`_turns`). Halt is normal: `HaltKind.BUDGET`, status `blocked`, exit 77.
- **Raise takes effect on resume (B6):** Raise and commit `.agile-team.toml`, then `start --resume` loads config afresh. No restart of anything else.

See ADR-007, design `agile-team/docs/design/s38.md` (rules K1–K6, B1–B9, M1).

The PO resumes one session, query after query. `ResultMessage.total_cost_usd` is a running total for the session, not per-query cost. The runner now ledgers only the **delta** from the previous query's running total. Key classes and methods:

- `SessionCost(session, reported)`: holds the last raw running total for one session.
- `SessionCost.own_cost(resumed, reported)`: returns `reported - base` (or `reported` if counter restarted or fresh session).
- `Ledger.last_cost(role)`: the last ledgered cost for a role (for legacy seed when state.json predates s25).
- `RunState.po_cost`: persisted `SessionCost | None`, loaded from state.json.
- `PoRun._own_cost()`: takes the delta, updates `po_cost`, returns modified result (does not save).
- `PoRun._seed_cost()`: seeds from old ledger if `po_cost` is None.

The provider rule applies after the delta, so a PO on `billing = "free"` stores the raw running total but ledgers 0.0. See ADR-004 and `agile-team/docs/design/s25.md` for rules C1–C9.

## Context reduction: Read little, no connectors (s23)

Your session has no Claude.ai connectors. Reduce re-sent context by being strategic with reads:

- **Find before read:** Grep with `-n` and content mode to locate what you need, then `Read` with `offset` and `limit`.
- **Design is your contract:** Each story has `docs/design/<id>.md` with rules, exact signatures, and modules to change. Read source only for what the design leaves open.
- **Never double-read:** If you already read a file, use grep again instead of re-reading.
- **Run quietly:** Test commands with `-q -x --no-header` flags; keep only the failures.

See ADR-0011 for the context reduction strategy.

## s11: Test disputes and rulings at any step

Developers can now hand off from `implement` with a `dispute` (test id, rule id, reason) to send a story back to `tests` without counting a bounce. Free disputes: the first `round_cap` disputes on a story cost no round; later disputes cost one round each. Rulings apply at any step, not just at round cap, with clear feedback if they can't apply. Key modules affected:

- **`roles.py`:** `Dispute` dataclass; `Handoff.dispute` field; `_handoff_from` builds dispute with reason fallback.
- **`gates.py`:** `DisputeStage` enum, `OpenDispute` dataclass with git base commit; `StoryState.dispute`, `StoryState.disputes` fields; `Verdict.DISPUTE`, `_raises_dispute`, `_dispute_gate`, `_dispute` methods; `ruling_refusal(story)` for T10.
- **`state.py`:** Nested load for `OpenDispute`.
- **`dispatch.py`:** `GATE_EVENTS` table, `_advance_and_log` emits `test-dispute` events, `_story_lines` shows dispute in brief, `apply_manager` returns ruling report (applied/why), `_manager_context` adds `test_disputes_since_last_review`.

Tests cover dispute route, free/capped/ruled disputes, ruling refusals (no story/done story), and e2e flows. See ADR-0018, design `agile-team/docs/design/s11.md`.

## s26: Liveness is data; absolute paths; service lifecycle

The runner now starts and probes service deliveries before the Proxy runs. Key changes:

- **Absolute paths (L1):** `cli.repo_of(args)` resolves `--repo` once. `Prepared.expand` resolves `{repo}` and `{sandbox}` so prepare commands never depend on cwd.
- **Port placeholders (L2):** `{host}` and `{port}` extracted from `url` in placeholders (saves to `config.toml` under `url` only).
- **Liveness is data (L3):** `Check(FILES | SERVICE)` enum, `Recipe(need, check)`, only `web` is `SERVICE`. No code branches on delivery name.
- **Service startup/probe (L4–L5):** `_serve`, `_start`, `_await_answer` start with output capture and probe up to 120 times. `http_answers` GET with 2s timeout, 200 + valid JSON.
- **Stale cleanup (L7):** `stop_stale` before layout; SIGTERM+SIGKILL escalation; pid file always deleted.
- **Teardown (L9):** `prepared.stop()` idempotent; all Proxy paths call it (new guard in `Runtime.plan`).
- **Gate trial (L10):** `Check.SERVICE` runs `Trial.liveness` from presentation sandbox; `NotUp` → bounce e2e (round +1), `PortBusy` → hold (no round).
- **Return on NotUp (L11):** Proxy's `prepare` raising `NotUp` returns to e2e with no round if e2e exists; never bills. `PortBusy` is refused.
- **Gate hold (L12):** `Trigger.GATE_HOLD` for port conflict; PO hand-over with exact error text.

See ADR-0013 for decisions. Design: `agile-team/docs/design/s26.md` (rules L1–L13, test checklist, reason strings).

## s27: Escalate repeated setbacks to the Manager

Stories that bounce or hold for the same reason (or back-and-forth between same steps) now escalate to the Manager instead of looping. Key modules and changes:

- **`loops.py` (new):** `NORMALISE` table (regex subs for timestamps, URLs, ports, paths, ids, counts), `Setback` dataclass, `normalise()`, `extend()`, `repeats()`, `bounces()`, `extend_run()`, `after_pass()`, `Manager` context builders.
- **`gates.py`:** `Verdict.ESCALATE`, `StoryState.streak/repeated/run/escalated_by`, `Outcome.rule/author`, `Pipeline.screen/fault_kind/apply_fault/_clear`, `dispatch_refusal` chains.
- **`dispatch.py`:** `_setback()` from gate outcomes, `_advance_and_log` screens for repeats/backstop, `_setback_fields` attaches event metadata, `_fault()` applies faults and emits events, `_rule_repeat` handles both, `_manager_context` adds `repeated_setback`.
- **`router.py`:** `_repeat_work` picks escalated stories before scribe, `repeat_brief()` formats the heading, `SENT_BACK_LINES["escalate"]`.
- **`handover.py`:** Three new rows (`runner_fault`, `off_pipeline_fault`, `fault_not_applied`) after `ruling_not_applied`.
- **`roles.py`:** `Handoff.fault` field, validation.
- **`events.py`:** `EventKind.ESCALATION`, `EventKind.FAULT`.
- **Dashboard:** `snapshot.repeated`, timeline events for `escalation` and `fault`, board pill for `needs_manager · repeat`.

**Rules:** L1–L18 for repeat detection; B1–B9 for backstop (back-and-forth). Key configs: `gates.repeat` (default 2, min 2), `gates.backstop` (default 4, min 2). See ADR-0014, design `agile-team/docs/design/s27.md`.

## CLI-specific context

**Team presents product in ready-made environment (s13):** New modules and changes:
- `presentation.py` (new): presentation directory structure, completeness check, sandbox copy, Proxy prompt section
- `gates.py`: `Verdict.RETURN` (moves back without counting round), e2e done gate checks presentation completeness
- `dispatch.py`: per-role setup (Integration Tester lays out presentation, Proxy receives copy), Proxy precondition returns on missing presentation
- `sandbox.py`: `Order` dataclass holds presentation source, `Preparer.prepare` copies before launching, Proxy read scope includes `.team/acceptance/**`
- `cli.py`, `git_ops.py`: init error handling outside git (no traceback, proper message)
- See ADR-0008 for the architecture.

**Clean halt on limits, crashes, SIGTERM (s8):** New modules and changes:
- `halt.py`: exception → `Halt` (kind, reason); `HALTS` and `LIMIT_PATTERNS` tables; `classify()` detector chain
- `dispatch.Runtime.halt_run()`: records first halt, saves status+reason, posts note
- `dispatch._step_failed()`: catches role-step exceptions, classifies limit vs. other errors
- `cli._halt_exit()`, `cli._finish()`: top-level halt handling
- `po_tools.PoRun._settle()`: skips settle when `runtime.halted_by` is set
- Partial edits after a halt are left uncommitted for the human and s9
- s9 will save interrupted step edits; s10 will record partial cost. This story only stops cleanly.
- See ADR-0007 for the data-driven strategy.

**Nested sandbox roots (s7):** The Customer Proxy reads customer docs and uses the installed CLI. Ensure CLI help and examples don't reference source code paths. Keep documentation output friendly to restricted sandboxes.

**Bash enforcement (s7):** Design CLI output and examples to avoid quoted comments or ambiguous shell constructs. The Proxy's check is conservative; when it blocks a legitimate command, refactor the example or workflow.
