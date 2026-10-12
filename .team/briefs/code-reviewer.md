# Code Reviewer: Current context and conventions

**Last updated:** 2026-10-12 (s77 done)

## s77: Ruff TID251 enforcement—system import discipline (P3 of s71, no new ADR)

The seam import rule is now enforced by ruff. Every module does `from agile_team import system` and calls `system.func(...)`, never `from agile_team.system import func`. Ruff `TID251` banned-api rule in `pyproject.toml` (DevOps step) bans all `from agile_team.system import …` imports. Review check (Z3, Z12): No module imports `ThreadingHTTPServer` directly (use `system.HttpServer` type); `http.server.BaseHTTPRequestHandler` stays in `server.py` only. All six P3 names in `system.__all__` (Z2): `home`, `which`, `on_signal`, `open_browser`, `async_sleep`, `HttpServer` type. Functions thin (one-liners), no logic. Two `per-file-ignores` rows for `test_os_guard.py` (its own tests check real names pass) and `dashboard_node.py` (e2e node driver). Coverage 95%+, ruff clean. See design `agile-team/docs/design/s77.md` (Z2, Z3, Z12, ruff config).

## s76: Unit tests touch no process/signal/network (P2 of s71, no new ADR)

Phase P2 (s71 P1 done in s71): All P2 modules (process_groups, commands, sandbox, kill_check, guard, git_ops, upstream, dashboard/server, cli) now call `system.<name>` for process, signal, network, HTTP. No module imports OS calls directly. Key review points: (J2) All 13 P2 names in `system.__all__` (signatures exact), (J3) only `system.py` calls `os.killpg`, (J4) `live.py` now uses `system.now()`, `system.monotonic()`, `system.pid()`, `system.wait_event()` (no `Pace` class), (J7) test patching fixed: `system.killpg`, not `process_groups.os.killpg`. Design changes per module: `sandbox.py` (`system.resolve`, `system.remove`, `system.wait_event`), `live.py` (no `Pace`, `__post_init__: system.now()`, `_log: system.append_text`, `write: system.write_text / system.replace`), `dashboard/server.py` and `cli.py` (`system.open_server`), etc. Moved 4 test files to e2e (paths +1 parent). Coverage ≥95%; ruff clean. No new ADR; extends ADR-0036 (s71). See design `agile-team/docs/design/s76.md` (J1–J9, changes per module).

## s64: Delivery names validated—verdict ship round 2 (stray test file deleted, no defects)

Scope: `config.py`, `po_tools.py`, test_s64_delivery.py, docs (`SKILL.md`, `protocol.md`, `product-owner.md`). Changes: `Config.delivery_refusal(name)` (V1–V5) returns None or reason; `Tools._open_refusal(args)` (V6) checks duplicate then delivery; `Tools.open_story` calls `_open_refusal` (V7–V8); `SCHEMAS["open_story"]` updated (AC2); docs state the rule and refusal (AC6). Exact error messages (UNKNOWN_DELIVERY, NO_DELIVERY) pinned by test. V8 (only setter is open_story) verified via grep. V9 (no hard-coded names) checked. All nine rules V1–V9 satisfied. Coverage 100% (config, po_tools), 99.64% overall; ruff clean. Round 1 D1 (stray test file) fixed. No other defects. See design `agile-team/docs/design/s64.md`, review `.team/reviews/s64.md`.

## s78: Health resilience, sleep detection, excuse logic — verdict ship (no defects)

**Verdict: ship.** Scope: s78 commits `1cbb109`, `7340abd`, `a6b5d34`, `3dbe2fb` (s82 `sandbox.py`, `presentation.py`, `test_s82.py` reviewed separately in s82). Changes span `live.py`, `health.py`, `dispatch.py`, `dashboard/snapshot.py`, docs. Coverage 99.68%, `health.py` at 100%. Ruff clean.

**Design review (H1–H10, R16–R20):** Beat thread resilience (H7): `_beat()` catches exceptions and logs first to crash.log via `_report()`, then keeps running. Monotonic stamps (H8): `Pace.mono`, `Clock` reads both times, `Vitals.slept` detects sleep. Excuse logic (R17): stale beats are amber when work (tool/chore) is declared and machine is awake and beat age ≤ 10 min. Sleep red (R16): `slept > stale_s` → red with "slept for…" reason. Gate chore (H9): `Runtime.gate` runs evaluate inside `pulse.doing(GATE_CHORE)`. Tool activity (H10): unchanged, tested. Both sources match (R20): watch and snapshot use same `health.judge(Vitals.read(clock))`.

**Function review:** `Pulse._beat()`, `_report()` logic sound; `Clock(wall, mono=None)` safe; `Vitals.slept` returns None for missing/non-numeric/bool mono; `sleet_over` boundary is `>`; `stale`, `busy`, `excused` properties correct; `RULES` table R16/R18/R19 exact; heartbeat key order pinned; gate chore format exact; snapshot passes both clocks. No cycles (`halt` imports only `system` and `state`).

**Tests:** All rule cases pinned: tool activity (amber), gate activity (amber), sleep (red), dead runner (red), stale no activity (red), beyond red_quiet_s (red), version-1 beat (red), non-numeric mono. Pulse thread test checks resilience on exception. Both sources compared. No test deleted or weakened.

See `.team/reviews/s78.md`, ADR-0038, design `agile-team/docs/design/s78.md` (rules H7–H10, R16–R20).

## s74: Dashboard pill fixes reviewed and shipped (no defects)

**Verdict: ship.** Changes in `agile_team/dashboard/index.html`: `STATUS_TONE.stopped` from `"warning"` to `""`, `pillText` fallback with space after `▶`, new `statusPills(view, now)` pure function. Design updated protocol.md § Health. Node UI tests pass (three new, existing green). Python unchanged; coverage 99.68%; ruff clean. No defects. The pill-tone change affects only `status=stopped` (timeline step-end statuses are handoff/verdicts, not `stopped`). See `.team/reviews/s74.md`, ADR-0037.

## s82: Service stop waits for group and port release—verdict ship (no defects, no ADR)

**Verdict: ship.** Diff reviewed: `sandbox.py`, `presentation.py`, `tests/test_s82.py`, `protocol.md`, `architecture.md`. Coverage 99.68%; sandbox.py and presentation.py at 100%; ruff clean. No defects. The fix is sound: (Q1) `stop()` now waits for the whole group to end, not just the leader (proven in design's cause section). (Q2–Q5) Sequence: SIGTERM 10s, SIGKILL 5s, port wait 5s; returns note on timeout; (Q3) no signal sent to already-reaped leaders (reused pid safe). E2E test reproduces the race (dash leader dies at SIGTERM, server sleeps 1s) without Linux. Linux proof only via CI on PR #14; macOS e2e cannot show dash behavior. Constants (KILL_WAIT_S, PORT_WAIT_S, POLL_EVERY_S, STOP_WAIT_S) pinned by test. Extends ADR-0013 (lifecycle); keeps ADR-0031 G1 (signals through process_groups only). No new dependency. See `.team/reviews/s82.md`, design `agile-team/docs/design/s82.md`.

## s72: Per-test time limit (1s unit, 30s e2e) — no code branches, one table

Configuration: `[tool.pytest.ini_options]` → `timeout = 1` (unit), `e2e_timeout = 30` (e2e/LEGACY). New module `time_limit.py` with:
- **`LIMIT_INI`:** table (World → ini key); `FAKE` → `"timeout"`, `REAL` → `"e2e_timeout"`.
- **`limit_of(item)`:** reads `float(item.config.getini(LIMIT_INI[world_of(item)]))`.
- **`mark(items)`:** adds `pytest.mark.timeout(limit)` to each item.
`conftest.pytest_addoption` registers `e2e_timeout` ini; `pytest_collection_modifyitems` calls `time_limit.mark()`. No marker added outside `time_limit.py` (L6). Pytest-timeout's `signal` method (L5) means the limit covers setup, call, teardown; message names the test and limit. Coverage 99.68%, ruff clean. No defects; ship. Two nits for later (e2e checklist not yet written; AC1 partial until s77 empties `LEGACY`).

## s71: Unit tests run no OS calls — single seam with fake and audit (P1: files, clock)

All OS calls now flow through `agile_team/system.py`, a thin seam that unit tests swap for a fake. Code review focus:

- **Import discipline:** Every module does `from agile_team import system` and calls `system.func(...)` at the use site. `from agile_team.system import x` is banned (binds the real function at import, defeats swap). Ruff `TID251` will enforce this in P3.
- **System module:** Only `system.py` touches the OS. Functions are thin one-liners wrapping exactly one OS call each (e.g., `read_text(path)` → `path.read_text()`, `run(command)` → `subprocess.run(…)`). Every function in `system.__all__` is swappable.
- **Fake and audit:** Unit tests install a `FakeSystem` (in-memory files, command scripting, package data) and an audit hook that fails any unit test reaching the real OS with guidance. The fake records write operations in `ops` (useful for test assertions) and can simulate failures (disk full, permission denied).
- **LEGACY table:** Pre-s71 test files not yet migrated stay in `os_guard.LEGACY` and run on the real seam, unaffected. Each phase removes rows.
- **P1 scope shipped:** `system.py` (P1 functions + `hard_link`), conversions of P1 modules (`state`, `ledger`, `events`, `relay`, `watch`, `halt`, `config`, `keys`, `roles`, `health`, and `live`'s heartbeat read), migrated tests (`test_state`, `test_ledger`, `test_events`, `test_relay`, `test_keys`, plus `test_system_fake`, `test_os_guard`, `test_s71_seam`, `test_s71_tell`), test infrastructure (`tests/fake_system.py`, `tests/os_guard.py`, conftest wiring).
- **Deferred to s76/s77:** Twelve modules and their tests stay in `LEGACY`; conversions pair with test migrations in P2/P3.
- **Code quality:** Coverage 99.56% (uncovered lines are e2e-only `system` wrappers, will be covered by `tests/e2e/test_system_e2e.py`). Ruff clean.
- **Nits (non-blocking):** Fidelity gaps on `hard_link` (copies instead of shares; design justifies) and file permissions (read-check for denied files when real OS doesn't need it; same gap as `replace`). Noted in review.

See ADR-0036, design `agile-team/docs/design/s71.md` (rules O1–O17, modules per phase, test checklist).

## s70: Parallel test suite with pytest-xdist; gate runs with `-n auto`

The suite now runs in parallel on multi-core machines via pytest-xdist. Gate cycle time drops to ~1 minute (from ~4 minutes). Review key changes:

- **`RunnerIds` injection:** `process_groups.RunnerIds` holds the runner's pid and process group. `sandbox.stop_stale()` receives it and never signals the runner itself. Test uses fixed fakes (`RunnerIds(4242, 4243)`) with static ids, stable across workers.
- **Test ID safety:** The new `test_s70_ids.py` collects the suite in two processes at once and asserts both lists are identical, catching any parametrize with a live value.
- **Commands use `-n auto`:** `test`, `coverage`, and targeted runs add `-n auto`. The gate parser reads the single combined `TOTAL` line unchanged.
- **Shared constant `TESTS_FAIL`:** Moved to module level in `gates.py` for DRY (shared by `green()` and `_failed_run()`).
- **Config updated:** pytest-xdist added as dev dependency (no runtime change); `.agile-team.toml` and CI workflows updated with `-n auto`.
- **Coverage 99.67%** (all tests pass under xdist).

See ADR-0035, design `agile-team/docs/design/s70.md`. Non-blocking cosmetic nit: `&&uv` spacing in `.agile-team.toml` coverage line.

## s69: Read tests; runner's coverage is in your brief; no test runs allowed

You cannot run any tests, including targeted runs. The runner runs the test suite at gates and the coverage command before your step. Your brief under `## Runner results` shows coverage output; read it to verify coverage is adequate.

- **Read tests:** Read the test code to understand intent and coverage strategy.
- **Deny on test runs:** Any attempt to run tests (even by name) is denied with a message explaining the rule.
- **Judge from brief:** The brief carries the coverage result from the implement or quality gate. Coverage % is already computed; you judge whether it is adequate given code changes.

This rule makes your review faster and audit-proof: all tests run through the same runner path. See ADR-0034, design `agile-team/docs/design/s69.md` (rules S7–S8, AC3).

## s68: Implement gate runs coverage once; test failure from output patterns

Reviewed and shipped: `gates.py` (implement gate, constants, helper). Key decisions (C1–C7):
- **C1:** Gate calls `run(commands["coverage"])` exactly once; timeout unchanged.
- **C3:** Exit 0 → `_coverage_outcome(parse_coverage(out))`, unchanged.
- **C4:** Non-zero + low coverage + no test failure → shortfall bounce, unchanged text.
- **C5:** Non-zero + test failure detected (or unknown) → `tests fail:\n{tail(out)}`.
- **C6:** `tests_failed(output)` True if `TEST_FAILURES` patterns match; `[1-9]` guards against `0 failed`.
- **C7:** Shared constant `TESTS_FAIL` used by `green()` and `_failed_run()` (DRY).
- **Known consequence:** Repo with baseline + `fail_under > baseline` now bounces `tests fail` (correct; config fix is repo's problem).

Diff reviewed: tests moved to coverage command path; coverage stays 100%; ruff clean. See ADR-0033.

## s44: Live spend meter, heartbeat, and health rules (all decisions verified)

The runner measures every turn, keeps a heartbeat file fresh, and judges health from one rule table. Key design decisions (D1–D9) recorded in ADR-0032:

- **D2:** Heartbeat by daemon thread (survives blocking gates) not asyncio task.
- **D3:** One health rule table in Python (`health.RULES`, R2–R11); verdict in snapshot.
- **D4:** Halted run red; graceful stop neutral (`halt_kind=None` vs `set`).
- **D8:** Quiet clock resets when model gets the floor (turn, tool close, inner close, chore end).
- **D9:** Wait for human is a chore (silences quiet rules but not dead-runner rules).

All round-1 items verified: Python tests 100%, UI tests under node, no leftover copies (C1–C6 fixed). E2E and N1 regression open (developer/integration-tester scope). See ADR-0032, design `agile-team/docs/design/s44.md` (D1–D9, H1–H7, R0–R15).

## Design decisions to verify

**Signal only groups the runner created; stop killing by name (s41):** Verify process_groups and kill_check rules enforce safely:
- **G1–G6:** `signal_child_group(pid, sig)` sends `os.killpg` only when `may_signal_child_group(pid)` holds: `pid > 1`, `pid != os.getpgrp()`, and either `getpgid(pid) == pid` (child leads own group) or lookup raises `ProcessLookupError` (leader exited, reused pid impossible). Never uses `getpgid(…)` for target. Tests patch `os.killpg` to record calls; no real signals sent (except where tests use `Popen` with `start_new_session=True`). Function names match: `leads_own_group`, `may_signal_child_group`, `signal_child_group`, `in_runner_group`, `parse_etime`, `started_at`, `Recorded.is_ours()`.
- **G3:** Pid from pid file (via `Recorded`) is signalled only if both `leads_own_group(pid)` AND `started_at(pid) <= written + STARTED_SLACK_S` (2.0s: etime has 1s resolution). Stale/reused pids rejected.
- **G4:** `started_at(pid)` runs `ps -o etime= -p <pid>` with stdlib subprocess; timeout 5.0s; any error returns `None`. `parse_etime` handles `[[dd-]hh:]mm:ss` format.
- **G5:** `_end_group(recorded)` sends SIGTERM, waits up to `STOP_WAIT_S`, polls with `killpg(pid, 0)`, then sends SIGKILL only if `recorded.is_ours()` still true. Re-check prevents racing.
- **G6:** `_signal_group(process, sig)` → `signal_child_group(process.pid, sig)`. `commands.kill_group(proc)` → `signal_child_group(proc.pid, SIGKILL)`.
- **K1–K5:** `kill_denial(words)` in guard; denies `pkill`/`killall` (by name), `kill $(…)`/backticks/`xargs kill` (run-time), `kill <0, -1, runner_pid, same-group_pid>` (protected targets). Passes: `$PID`, `$!`, `%1`, new-session pid, stale pid.
- **Coverage/quality:** `process_groups.py` line 32–33 (PermissionError branch) uncovered; follow-up test noted. `leads_own_group` misses `OverflowError` (same gap as old code; runner only writes pids via `sandbox.py:359`). No mutation of constants; fresh dicts on `_network`. See review at `.team/reviews/s41.md` (verdict: ship, three non-blocking follow-ups).

**Gate command timeout and hung test naming (s43):** Verify that timeouts work, hung tests are named, and guard rules are enforced:
- **T1–T3:** `[gates] command_timeout_s` configurable (default 300.0); all gate commands use it. Commands start with `start_new_session=True`, stdin `/dev/null`, stdout+stderr merged.
- **T4–T5:** On timeout, `SIGKILL` via `process_groups.signal_child_group()` (s41); `communicate(timeout=5.0)` drains with a deadline. Code returns 124, reason is last line.
- **T7–T8:** `hung_test(output)` tries `HUNG_PATTERNS` rows; last match wins. Output formats: faulthandler (`in test_x`, no comma), traceback (`in test_x`, comma). Fallback: no test named.
- **T9, T12:** `timed_out(code, output)` bounces with `TIMED_OUT_BOUNCE` when `code == TIMED_OUT`. `tests_red`, `green`, `tests_green_and_covered` check it before other outcomes. `_check_waits()` denies `until`/`while` unless segment starts with `timeout`/`gtimeout`.
- **T13–T14:** `pytest-timeout` in dev dependencies, `timeout = 30` in config. `test_a_held_boundary_waits_when_a_question_is_open` injects `sleep`, not waiting on real sleep; no skip/xfail/deselect in config.
- **Config/validation:** `command_timeout_s > 0` rule. `make_pipeline` and `make_runtime` pass the configured limit. `[gates]` is human-owned (no role edit escapes).
- Functions by function: `commands.py` (HungPattern, hung_test, hung_line, kill_group, drain, CommandShell.run, report_timeout, shell_runner), `gates.py` (timed_out, Checks methods), `fullcheck.py` (_run_one uses TIMED_OUT), `guard.py` (_check_waits, _open_wait, _reads_stream), `config.py`/`cli.py` (command_timeout_s field, rule, make_pipeline, make_runtime).
- Round 1 additions (architect `c1603cb`): `commands.kill_group` now calls `process_groups.signal_child_group()`. E2E tests: real pytest hang → names test, `tests_red` bounces; no nameable test → `NO_HUNG_LINE`, fallback; group kill → grandchild gone, foreign process lives; guard → `until grep` denied, `while true` denied, `for i in $(seq 60)` allowed.
- See ADR-0030, design `agile-team/docs/design/s43.md`.

**Liaison commands, self-hosting, frozen uv (s62):** Verify that messages, watch, resume, and pinning work as designed:
- **T1–T7:** `tell` stores unstripped text in `t<N>.md` with hard-link atomicity (no race overwrites), never on command line. `unread(told_ids)` filters to non-delivered. Router delivers in `human_message` pass after checkout check (T5), with path repo-relative.
- **V1–V8:** `watch` polls every 2s, exits on trigger fire or timeout (heartbeat). `Seen` remembers count + baseline. Triggers table (message, status) in order. Torn JSON → retry. `line()` builds exact V6/V7 dict (triggers, messages, status, status_reason, was).
- **R1–R4:** `state.unsaved` tracks why salvage was skipped (moved checkout). `recover_cut(run_dir, git)` prefers KILLED > unsaved > None. Message via `RECOVERED_LEADS`. `unsaved` cleared at `PoRun` start.
- **P1–P3:** `pin-runner.sh <commit>` checks in order (usage, repo, commit, ancestor, pyproject, runner.pid), builds to `.new`, replaces atomically, writes `.commit` last. No re-resolution on later runs (frozen uv).
- **F1–F3:** Every `uv run --project …` in docs (SKILL, protocol, self-hosting, README) has `--frozen`. CI workflows use `--locked`. `agile-team.yml` paths updated.
- See ADR-0029, design `agile-team/docs/design/s62.md` (rules T1–T7, V1–V8, R1–R4, P1–P3, F1–F3).

## Previous design decisions to verify

**Checkout guard halts on external changes (s61):** Verify that the checkout record and guard are safe and comprehensive:
- **K1–K2:** `state.checkout` persists branch and head; written only by runner (record, record_checkout, accept-checkout). Checkout matches when attached, no operation in progress, and (with record) branch/head equal recorded.
- **K3–K4:** Checked at start/resume, before/after every step, before gates/commits; in-run mismatch posts question and halts with kind `CHECKOUT`, status `checkout-changed`, exit 78. `CheckoutChanged` exception caught in `run_role` before generic Exception (no crash.log). 
- **K5:** `save_interrupted` returns None on moved checkout (no salvage). Step cost still ledgered. K6–K10: Guard for start/accept, accept command validation, reason text exact, status/dashboard red, budget advice.
- Every runner git write followed by `record_checkout`: `settle_tree` (K3), `save_interrupted` after salvage, `_merge_in` after MERGED, `recover_killed` after salvage. No salvage on moved checkout (K5).
- Function by function: `checkout.py` (Found.text, Drift.reason/halt, operation, read, last_move, matches, check, recorded, answer_open, Guard.on_start/accept), state changes, halt table (CHECKOUT kind), status (CHECKOUT_CHANGED), dispatch/router/po_tools/boundary/recovery changes, cli (cmd_start guard, cmd_accept_checkout, status_report checkout field), dashboard STATUS_TONE. See ADR-0028, design `agile-team/docs/design/s61.md`.

## Previous design decisions to verify

**Proxy sandbox local service binding (s58):** Verify that service deliveries get the network setting and the e2e test is sound:
- **N1–N4:** `LOCAL_SERVICE_NETWORK` and `NETWORK_BY_START` constants; `_network(prepared)` returns fresh dict; `_sandbox_section` merges with `**_network(prepared)`. Non-service kinds have no `network` key.
- **V1–V2:** E2E test `pytest.mark.skipif(sys.platform != "darwin", ...)` with stated reason. Scripted model and real service on separate ports. Real settings, real CLI. With key: exit 0 + `200 exit=0`. Without key: `exit=7`.
- **L1:** `Trial.liveness` starts and stops; Proxy gets fresh service from `plan()`. No code changes to lifecycle; documented to clarify design.
- Service lifecycle unchanged by design (s26 already established it). See ADR-0026, design `agile-team/docs/design/s58.md`.

## Design decisions to verify

**Waiting status shows what run waits on (s47):** Verify that `status_reason` reflects open questions while waiting and halt notes include the waiting context:
- **W1–W3:** `Relay.waits()` lists one line per story/question (stories first in outbox order, unnamed last). `Relay.waiting()` joins with `WAITING_HEAD` prefix or `""`. `Router._show_wait()` sets reason, saves on change only.
- **W4–W5:** `_clear_wait()` strips `WAITING_HEAD`. `_end_wait()` saves if cleared (first call in `_step`). `_deliver` calls `_clear_wait` first; existing save handles persistence. Halt note: `halt_note(…) + "; waiting on …"` when a question is open, unchanged when no question.
- **W6:** Stall lines unchanged; `_idle` never stalls while a question is open.
- Tests cover empty, one story, multiple stories, outbox order, unnamed, answered-excluded, story-named-twice, unchanged reason not re-saved, new question updates reason, halt with/without question, leave non-waiting reason. See ADR-0025, design `agile-team/docs/design/s47.md`.

## Design decisions to verify

**Dashboard fixes (s21):** Verify that the toggle, live config, and board layout work correctly:
- **F1–F4:** Toggle between tokens and dollars; choice in `ui.unit` persists; only "Tokens by" chart reads it; bars sort by unit total, legend and title change (ADR-0021 context).
- **F5–F6:** Each `snapshot.build()` re-reads config via `fresh_config()`; missing or unparsable file falls back to startup config; config file in `watched_files` triggers SSE push.
- **F7–F9:** Board layout uses flexbox (`flex: 1 1 0; min-width: 0; overflow: hidden` per column); empty columns 44px strips with vertical headings; card text wraps (ADR-0022 context).
- **Contract unchanged:** Server, CLI, config, snapshot fixture do not change. Role book built once at startup (docs_dir changes need restart).

## Previous design decisions to verify

**Budget correction and ceiling (s38):** Verify that ledger entries are corrected on read, the ceiling is enforced consistently, and the human can raise the budget:
- **K1–K3:** `ledger.corrected()` walks legacy entries with `SessionCost`, turning running totals into own costs. `_own_share()` checks `at < PO_DELTAS_FROM`. Only `cost_usd` changes; other fields stay. Input never mutated.
- **K4–K5:** One code path: `Ledger.entries()` → `corrected()`. All readers go through it or `_raw()` (only `last_cost`). `budget_status` carries corrected spend + `po_overcount_usd`.
- **B1–B3:** `Runtime.enforce_ceiling()` halts when `round(total, 4) >= budget_usd`. Checked (a) after steps land (b) after PO ledgers (c) at start before opening. Normal halt: `HaltKind.BUDGET`, exit 77, one liaison note.
- **B5–B6:** Reason exact: "budget reached: spent $X,XXX.XX of $Y,YYY.YY". Advice: "raise team.budget_usd in .agile-team.toml and commit it, then run `agile-team start --resume` ". Raise + commit + resume loads config afresh. No restart needed.
- **B9:** Clean-tree preflight unchanged. Advice tells human to commit. Uncommitted raise → preflight refuses.
- **M1:** Manager gets `budget.spent_usd` (corrected), `budget_usd`, `remaining_usd`, `pct_used`, `by_role`, `po_overcount_usd` in runner context.

Function by function: ledger (`corrected`, `_own_share`, `Ledger.entries`, `.last_cost`, `.overcount`), halt (`budget_halt`, `HALTS[BUDGET]`, `Cause.BUDGET`), dispatch (`enforce_ceiling`), po_tools (skip opening, `_turn` no query), snapshot (`_ledger`). See ADR-007, design `agile-team/docs/design/s38.md`.

## Previous design decisions to verify

**Unattended wake time and reason sources (s37):** Verify that wake state is cleared consistently and reset times are read from the right source:
- **N1:** `JobState.mark()` is the only place `next_wake` and `wake_on` are cleared; every status change (running, waiting, done, blocked, failed, stopped) clears both. Timed waits set both after calling `mark`.
- **N2:** Offline wait (via `_mark_offline()`) marks WAITING with `wake_on=NETWORK`, then `next_wake` remains `None` (cleared by `mark`). Resume calls `_cycle()` → `mark(RUNNING)` which clears both again.
- **R1:** `REASON_SOURCES` tuple (data, ordered): halt_reason → status_reason → text_reason → default. First truthy source wins; later ones not read. Halt line regex anchored at `^`, covers block-buffer case via status file.
- **R2:** `RESET_NOTE` pattern requires readable time (H[:MM]am|pm with optional date/zone). `RESET_CLOCK` fragment shared between `RESET_TIME` and `RESET_NOTE` (DRY, both built from one grammar).
- **R3:** `Waits.after_limit()` returns `Wake(reset+grace, RESET)` or `Wake(now+fallback, FALLBACK)` depending on whether a readable time was found.
- **S1:** Status/list/wait report `"wake_on"` (reset/fallback/backoff/network/null) right after `"next_wake"`. Wait event carries `"on"`.
- **L1:** `from_json` loads missing or null `wake_on` as `None` (legacy files supported). String loads as `WakeOn` via `_wake_on()` helper.
- Tests: AC5 exact case, reason source order, offline with null wake throughout, all rule cases covered. See ADR-0020, design `agile-team/docs/design/s37.md`.

## Previous design decisions to verify

**Test disputes and rulings at any step (s11):** Verify that the dispute mechanism is safe and rulings apply correctly:
- `Dispute` and `OpenDispute` dataclasses: `test` (pytest id), `rule` (design rule id), `reason`, `base` (HEAD at dispute time), `stage` (raised/confirmed). Handoff validation: both test and rule are non-empty strings.
- `Pipeline._raises_dispute()` checks only at `implement` with `tests` enabled; STOPPED_HANDOFFS checked first so blocked disputes still hold. `_dispute_gate()` at `tests`: settled (git diff exit 1, or confirmed) → pass; otherwise bounce with exact reason, round +1.
- `_bounce()` sets `confirmed` before moving if leaving `tests` with `next_role: architect`. `advance` on DISPUTE: free while `disputes <= cap`, above cap use `_bounce()` (counts round). Close dispute when reaching `implement`.
- `apply_ruling()` resets `rounds`, `disputes`, `dispute` together. `ruling_refusal()` rejects no story / done story with exact text; applied ruling emits `ruling` event and report (applied: true, now_at, ruling). Unapplied ruling emits no event, just report (applied: false, why).
- Event: `TEST_DISPUTE` (not `gate`), with `verdict: "dispute"`, test, rule, disputes count, rounds. Dashboard TIMELINE row colors warning tone, body is reason, meta is count/round.
- Test coverage: free/capped/ruled disputes, ruling refusals (all paths), e2e round-trip no bounce + no handover. See ADR-0018, design `agile-team/docs/design/s11.md`.

**Interrupted steps saved in commits, not stashes (s9):** Verify that interrupted steps are recovered consistently:
- `salvage.py`: `Cause` enum (ERROR, LIMIT, CRASH, SIGTERM, KILLED), `InFlight` and `Interruption` dataclasses, `save_tree()` commits all changed paths + reverts, `capture()` creates `Interruption` or `None`, `offer()` and `resume_section()` build exact text templates.
- `recovery.py`: `Salvager` class with `save()` method calls `capture()`, records via `state.interrupt()`, emits `step-interrupted` event. `recover_killed()` loads state, checks `shown_status()`, salvages, saves state, returns interruption.
- `state.py`: `in_flight: InFlight | None` (set on step start, cleared on settlement), `interrupted: list[Interruption]` (pending list), `runner_pid()`, `pid_alive()`, `runner_alive()` (pid liveness checks), `shown_status()` returns `INTERRUPTED` when `status==RUNNING` but pid is dead.
- `dispatch.py`: `_take_off()` sets `in_flight` and emits `STEP_START`, `_land()` clears `in_flight` (supersedes direct emit), `save_interrupted()` is public, `halt_run()` calls `save_interrupted(Cause(kind.value))`, `_step_failed()` calls `save_interrupted(Cause.ERROR)` before re-raising.
- `po_tools.py`: `_opening()` calls `_take_interrupted()` first, building `resume_section()` (head + items + tail), clears `state.interrupted`, joins with opening prompt.
- `cli.py`: `_recover()` on `start --resume` detects `shown_status() == INTERRUPTED`, calls `recover_killed()`, prints sha to stderr if found.
- Every halt saves: `halt_run`, `_step_failed` (non-limit error), `recover_killed` (kill -9). Tree clean; `in_flight` cleared. Brief offers sha until settlement clears it.
- `story.interrupted: Interruption | None` persists the offer until settlement clears it.
- Snapshot: `run.in_flight` and `run.interrupted` added, `STATUS_TONE["interrupted"] = "critical"`, `shown_status()` in snapshot builder.
- Exact strings: `chore(team): interrupted step by {label}`, offer template, resume section (head, items, tail).
- Rules I1–I15, test checklist (16 areas) in `agile-team/docs/design/s9.md`. See ADR-0017.

**Story priority in code (s40):** Verify that priority is explicit, auditable, and data-driven:
- `state.order: list[str]` persists the queue; legacy files load with `[]`.
- `Priority.key()` = `(done, listed, not in_progress, natural(id))` is the single ranking rule. No creation order, no implicit ties.
- Router `_story_work` and `_repeat_work` use `priority().ranked()`, not `state.stories.values()` order.
- `prioritise()` and `move_story()` validate ids and positions; refusals are exact. `start_sprint()` treats list as priority.
- `_reorder()` helper emits `priority` events (change: set/move/sprint, order, moves [1-based from→to], reason).
- Hold does not change order: `_movable` skips held stories; position never changes.
- `waits.wait()` returns first matching `WAITS` row (data-driven, ordered). Board shows `⏸ <reason>` and `waits on:`.
- Snapshot: `run.order` = queue, stories ranked, each has `position`/`in_progress`/`hold`/`wait`. Fixture matches.
- Dashboard: `#${s.position}` in story id, `WAIT_TONE` for hold colors, `priorityLabel()` for timeline labels, no re-sorting board.
- `story_status` returns stories ranked with `order` key. `story_status_data` iterates `ranked()`.
- Contract changes: Tools have exact descriptions in `SCHEMAS`. `start_sprint` emits `priority` event after `sprint-start`. See ADR-0016, design `agile-team/docs/design/s40.md`.

**Sync with upstream and stacked PRs (s29):** Verify that sprint boundaries are code (not prompt) and that all git and PR operations go through narrow interfaces:
- Boundary steps (sync, check, review, push) are router-picked before sprint stories; they cannot be skipped by a prompt.
- `Upstream.merge_in()` and `Upstream.push()` use `Git` with options; `Prs` is a protocol with `GhPrs` and `NoPrs` implementations.
- Review branches are built once per boundary stage by cherry-picking in a worktree (`.team/run/review`), never edited by hand; every `git rerere` resolution is tested on a fresh rebuild.
- The stack is kept in `state.upstream.stack` as `StackEntry` objects; merged entries are dropped by comparing picks against `git cherry-pick` logic (not by marking them).
- Permission is asked once and stored in `state.upstream.push` (yes/no/unasked); the PO tool `set_push_permission()` is the only way to change it.
- Dashboard snapshot gains `upstream` section with stack, boundary state, team branch, remote, and report.
- Escalation context (U13) adds `repeated_boundary` to the Manager's context when the same failure repeats (integrates with s27 logic).
- Rules U1–U27 and exact strings in `agile-team/docs/design/s29.md`; see ADR-0015.

**Repeated setback escalation and backstop (s27):** Verify that loops are broken when a story bounces for the same reason or ping-pongs between two steps:

**Repeated setback escalation and backstop (s27):** Verify that loops are broken when a story bounces for the same reason or ping-pongs between two steps:
- `loops.NORMALISE` table (data-driven): regex patterns strip timestamps, URLs, host:port, paths, ids, shas, counts in order. Stored keys are recomputed on load (never trusted).
- `Setback` dataclass: `step`, `to_step`, `role`, `verdict`, `author`, `reason`, `event`, `key` (set in `__post_init__`). `Setback.pair` is a property, not saved.
- `Pipeline.screen(story, setback)` returns `Outcome(ESCALATE, …)` when repeat rule fires (`len(streak_same_key) + 1 >= repeat`) or backstop fires (bounces between same pair `+ 1 >= backstop`). Repeat wins if both fire.
- `Pipeline.advance` on `ESCALATE`: step/rounds unchanged, `status = NEEDS_MANAGER`, `repeated = reason`, `escalated_by = rule`. Streak and run are extended before escalation.
- `Pipeline.apply_fault(story, fault)`: clears `rounds`, `disputes`, `dispute`, `streak`, `run`, `repeated`, `escalated_by`. Sets step and status by `fault_kind`.
- `Pipeline._clear` is also called by `apply_ruling`; old reset lines replaced with a single call to `_clear`.
- Router `_repeat_work` picks escalated stories (story with `repeated` set) before Scribe; respects holds and open questions.
- Manager context `repeated_setback` includes `count`, `key`, `author`, `reason`, `history` (earlier setbacks with ids), `rule`, `pair`, `events` (all logs from first on). Built from `trail(story)` based on rule.
- Fault report: `"fault": {"fault", "kind" ("runner"|"pipeline"|"off_pipeline"), "applied": true/false, "reason", "now_at"}`.
- Three new hand-over rows (after `ruling_not_applied`): `runner_fault`, `off_pipeline_fault`, `fault_not_applied`. `round_cap` no longer matches escalate verdicts.
- Escalation and fault are logged as `escalation` and `fault` events (not `gate`), with metadata: `step`, `reason`, `author`, `count`, `history`, `key` (escalation only), `rule`, `bounces` (gate events too).
- Dashboard: story dict gains `repeated` field; board shows `needs_manager · repeat` pill and reason line; timeline has `escalation` (`repeat`/`backstop`) and `fault` events.
- Rules L1–L18 and B1–B9 in `agile-team/docs/design/s27.md` and ADR-0014.

**Cost delta tracking (s25):** Verify that PO query costs are correctly deltas, not running totals:
- `SessionCost.own_cost()` logic: `reported − previous` for resumed same session; full `reported` for fresh session or counter drop.
- `RunState.po_cost` persists across queries and is saved with each ledger entry.
- `PoRun._own_cost()`: takes delta before pricing, does not save (pair it with `_record`).
- Legacy seed (C6): `po_cost = None` → look up last PO entry cost and session from ledger.
- Role steps: `plan.options.resume is None`, own cost = reported cost (test pins this).
- Readers unchanged (C8): dashboard, budget_status, checkpoint all read deltas from the ledger, no new field.
- No rewrite: old entries stay as they were; ADR-004 gives the one-off correction.
- See ADR-004 and `agile-team/docs/design/s25.md` for full spec.

**Routing in code — hand-over triggers as data (s19):** Verify that the router and hand-over logic are data-driven:
- `handover.HANDOVERS` table is the single source of truth for when to hand over (no branching outside it)
- Table rows match in order; when multiple rows match, all triggers are handed over
- `BRIEF_PATHS` table and `standard_brief()` apply the same logic to every step (story, design, review paths checked in order; previous/note lines added only when applicable)
- `ROLE_HINTS` tuple defines role selection order (R3); `step_role()` applies it and always finds a role (fallback to `developer`)
- `Router.PICKERS` tuple defines work order: Manager, Scribe, movable story (rule R2); `next_work()` returns the first non-None
- `Router.advance()` loop respects stop/halt at entry and after each turn; `_ended()` is the only halt check
- `_scribable()` allows unheld stories or `DONE` stories (D1 fix); R12 blocking by open questions still applies to done stories
- `note_step()` sets holds from the report's trigger names; `continue_story` refuses done stories (by design)
- Rules R1–R18 are well-covered by tests (design's test checklist section 7); verify coverage claim
- See ADR-0009 for the full strategy.

**Team presents product in ready-made environment (s13):** Verify that the handoff is enforced in code:
- `presentation.py` has single source-of-truth functions: `lay_out()` (wipes, creates workspace, git init), `missing()` (exact reason strings), `copy_into()` (symlinks preserved), `prompt_section()` (heading + path + guide)
- e2e `done` gate checks presentation completeness via `Pipeline._done_gate()` (only when acceptance step exists)
- Proxy precondition checks via `Pipeline.unpresented()` returns story to e2e with `Verdict.RETURN` (no round, no cost)
- Sandbox copy runs via `Preparer.prepare()` → `_copy_presentation()` after wipe, before prepare launch (E7 order)
- Proxy read globs and allowed reads add `.team/acceptance/**` and `<repo>/.team/acceptance` (report access)
- Proxy write scope unchanged: sandbox + `.team/acceptance/**`; `Read` added to `web`, `harness`, `manual` tools
- `git init` outside git: `Git.is_repo()` probes, `_require_init_inputs()` checks first, raises `CliError` with exact message (no traceback)
- Story id safety checked in `lay_out()` before wiping (refuses unsafe id with `SandboxError`)
- See ADR-0008 for the full strategy.

**Dashboard backend snapshot and read-only server (s4):** Verify that the snapshot builder is pure and the server is secure:
- **S1–S2:** `build(config, book)` returns exactly 11 keys in order (`generated_at, run, pipeline, roles, stories, requirements, events, ledger, messages, answers, upstream`). Pure function: only reads files (state, events, ledger, outbox, inbox, stories, REQs). No writes, no git, no network (only `time.time()`).
- **S3:** No aggregation in Python; views (board, flow, tokens, questions) are derived in the browser from raw snapshot keys.
- **D3–D4:** Missing files give empty sections or defaults. Blank/malformed JSONL lines skipped. Torn lines at end are normal.
- **D5:** Routes are exact literal lookups: `/` (index.html), `/api/snapshot` (JSON), `/api/stream` (SSE). Any other path 404. No file paths built from requests. No directory serving.
- **D6:** SSE polls file fingerprints (mtimes, sizes) every 1 second. On first tick or change, sends snapshot. Otherwise keepalive. Loop ends on socket errors.
- **D7:** `default_host()` returns `0.0.0.0` except Windows (`127.0.0.1`). All-interfaces URL uses `socket.gethostname()`. `--port 0` finds free port and prints actual. `--no-open` skips browser. Bind error → exit 1 with exact message.
- **Fixture as contract:** `snapshot.json` defines the API contract (not AC1/AC2 view names). Each snapshot build matches the fixture shape and types after JSON round-trip.
- **Known gaps (accepted, not blockers):** Typed input validation, some socket errors, hostname resolution. See ADR-0027, design `agile-team/docs/architecture.md` § "s4: Dashboard backend".

**Clean halt on limits, crashes, SIGTERM (s8):** Verify that halt handling is data-driven:
- `HALTS` table (kind → status, note_kind, exit_code, advice) with no code branches outside it
- `LIMIT_PATTERNS` table (regex, template) strips the SDK's ` (exit code: N)` suffix before matching; reset text copied from message, not computed
- `classify()` uses a detector chain (limit_halt, sigterm_halt, crash_halt); first non-None wins
- First halt recorded and re-asserted; later halts do not post a new note
- `_settle()` skipped when `runtime.halted_by` is set (partial edits left uncommitted)
- See ADR-0007 for the full strategy.

**HTML escaping in dashboard (s5):** Every `${…}` that places a snapshot field into HTML must be wrapped with either `esc()` (for HTML) or `mmdText()` (for Mermaid labels). Grep for suspicious patterns: `${ *[a-z.-]+\}[^)]`, `innerHTML *=.*\$`, unquoted attributes. See ADR-0005 for the rule and safe patterns. Exception: values from code, not snapshots (regex matches, map results of escaped strings).

**Mermaid graph edge selectors (s5):** Review that `findEdge(from, to)` queries SVG ids by prefix `L_<from>_<to>_` (Mermaid 11 convention, not v10's `LS-`/`LE-` classes). Round 1 defect D1 was this selector failing silently. Verify the fix and ask for a runtime test (headless Chrome) as a follow-up.

**Over-approximation in security (s7):** The Proxy Bash enforcement denies on any plausible view of a command (shell or comment interpretation). Review that this over-deny does not break legitimate workflows; ask the Customer Proxy to rephrase if it does.

**Backlog gating (s3):** Ensure the `_story_refusal` check is working: story-bound steps must refuse on backlog stories with a clear message.

**Test expectations (via Unit Tester):** The Unit Tester re-reads every test against the design. You are a secondary check for misalignments between code and tests.
