# Unit Tester: Current context and conventions

**Last updated:** 2026-10-12 (s68 done)

## s68: Implement gate runs coverage once; test failure detected from output

**Gate change:** `tests_green_and_covered()` now calls `run(commands["coverage"])` once (C1). Coverage exit code 0 → pass with percentage. Non-zero → branch via `_failed_run()`:
- If `tests_failed(output)` is True (pattern in `TEST_FAILURES`) → bounce `tests fail:\n{tail(out)}`
- Else if coverage below threshold and no test failure → bounce `coverage {pct}% is below {req}%` (C4)
- Else → bounce `tests fail:\n{tail(out)}` (C5, safe side)

**Test failure detection (C6):** Regex patterns in `TEST_FAILURES` tuple (pytest/cargo/jest `N failed`, go `--- FAIL:`). Note `[1-9]`: `0 failed` does not count. Shared constant `TESTS_FAIL` used by both `green()` and `_failed_run()` for DRY (C7).

**Moved/updated tests:** Tests expecting old two-run contract (test command then coverage) now use coverage command only. `test_green_gate` and others make the coverage command fail. `PipelineRunner.failures` updated. Existing logic pins shared constant. See design `agile-team/docs/design/s68.md` test checklist; ADR-0033.

## s44: Live spend meter, heartbeat, and health (Python/UI tests done; E2E open)

Round 1: `test_s44_live.py`, `test_s44_round1.py`, `test_s44_wiring.py` (202 passed, 100% coverage on code), and `test_dashboard_live_ui.py` cover Python and UI (node). **Open:**

**N1 (regression):** `pillText` with no heartbeat lost the space. Test: call `pillText(view, now)` with `view.heartbeat = null` and an open step from `view.events`, assert text starts `▶ ` (space after arrow).

**E2E (integration-tester):** Six checklist items (design section E2E) are open: fake step silence (green→amber→red), SIGKILL (the runner is not running), graceful stop (idle stays neutral), scope toggle, URL lines, coverage/ruff.

Key test areas:
- **Live rules (R0–R15):** One test per RULES row. Halted run → red. Graceful stop with `halt_kind=None` → idle. Resting status hides stale heartbeat.
- **Chores and quiet clock (H5–H7):** `doing` context sets/restores `chore`. Quiet clock moves on turn/tool close/inner close/chore exit. PO meter not red after long role step.
- **Nested meters:** PO meter opens, role meter inside it, role closes, PO reading wakes.
- **Interrupted steps:** Every cause (error, limit, crash, sigterm, killed) emits `step-end` with `interrupted` status, turn/token counts, no `cost_usd`.
- **Config (R13):** `[health]` thresholds load; validation rules pass (positive, beat_s < stale_s, amber <= red_quiet_s).
- **Snapshot:** `turns` tail, `heartbeat` shape, `health` verdict, `generated_at` sync.
- **Watch (s62 integration):** health trigger fires on change to red, line carries level.

See ADR-0032, design `agile-team/docs/design/s44.md` (rules R0–R15, H1–H7, test checklist).

## s41: Signal only process groups the runner created; guard against kill by name/runtime

Sandbox and guard rules prevent the runner from killing itself and roles from killing the runner.

**process_groups (AC2, AC3):** New module with `signal_child_group`, `may_signal_child_group`, `leads_own_group`, `in_runner_group`, `parse_etime`, `started_at`, `Recorded` (rules G1–G6). Signals only groups with pgid == pid (children with own session), rejects non-leaders and reused pids (checked via start time). Tests 1–7: `signal_child_group` sends nothing to runner/same-group/stale pids; sends to new-session child or reaped-leader case; `leads_own_group`, `in_runner_group`, `parse_etime`, `started_at`, `Recorded.is_ours()` all tested with edge cases (reaped pids, overflow, bad time formats).

**sandbox (AC2, AC3):** Tests 8–11: `stop_stale` leaves new-session child alive when pid mtime is old (reused pid); sends nothing for runner/group pids; escalates SIGTERM→SIGKILL for live groups; re-checks `is_ours()` before SIGKILL (no SIGKILL if group dies between SIGTERM and deadline). Tests 10 (existing) stay green: stale leader killed, dead pid file deleted, non-leader never signalled.

**commands (AC2, AC3):** Test 12: `kill_group` with same-group proc sends nothing; new-session proc gets SIGKILL. s43 timeout tests green (both use `signal_child_group`).

**guard / kill_check (AC4):** New module with `kill_denial`, `kill_targets`, `target_denial` (rules K1–K5). Tests 13–18: `kill <pid>` where pid is runner/same-group denied (reproduces incident); `pkill`/`killall` denied by name; `kill $(…)` / backticks / `xargs kill` denied as run-time targets; `kill $PID`, `kill $!`, `kill %1`, new-session pid, reaped pid pass; `kill_targets` drops signal/`--` correctly; order check (`_check_kills` runs last, so git reason appears first if both apply).

**Config/quality:** Coverage ≥95% (99.67% on s41 code), ruff clean. See ADR-0031, design `agile-team/docs/design/s41.md` (test checklist 19 areas).

## s43: Gate command timeout; hung test naming and per-test timeout

**Test coverage from design checklist:**

**commands.py (T1–T9):** `shell_runner(tmp)("echo out; echo err >&2; exit 4")` gives `(4, …)` holding both. Stdin `/dev/null` → `cat` returns `(0, "")` at once. Timeout (0.3s on `sleep 30`) gives `TIMED_OUT` (124) with tail ending in `NO_HUNG_LINE`. Faulthandler-style frame → `the hanging test: /x/tests/test_a.py::test_hangs (line 12)`. Kill group: grandchild gone afterward. Drain deadline (monkeypatch `DRAIN_S = 0.2`) with `setsid` child → returns `TIMED_OUT` with only reason lines. `KeyboardInterrupt` → `kill_group` called and propagates. `hung_test`: both formats, last dump wins, noise frames ignored, empty → `None`. `report_timeout` on empty output gives exactly two reason lines.

**gates.py (T9–T12):** `tests_red` with `(124, "…")` bounces with `"the command did not finish in time:"`. `tests_reworked` on timeout bounces. `green` timeout bounces, not `"tests fail:"`. `tests_green_and_covered` coverage timeout bounces, not `"could not read"`. `Pipeline.evaluate`: timeout at `implement` → bounce_to `implement`, at `tests` → bounce_to `tests`.

**config.py / cli.py (T14–T15):** Default is 300.0. `command_timeout_s = 90` is read. `0` and `-1` fail with `"gates.command_timeout_s must be positive"`. `make_pipeline(config).checks.run.__self__.limit_s == 90`. `make_runtime(...).shell(path).__self__.limit_s == 90` with configured value.

**fullcheck.py (T16):** Timeout check returns `code == TIMED_OUT` → why is `"timed out"`, tail holds reason lines.

**guard.py (T12, T17):** Denied with `WAIT_DENIED`: `until grep -q passed /tmp/run.log; do sleep 5; done`, `while true; do sleep 1; done`, `while ! grep -q x f; do sleep 1; done`. Allowed: `timeout 300 bash -c 'until …'`, `for i in $(seq 60); do …; done`, `cat f | while read l; do echo "$l"; done`, `while IFS= read -r l; do :; done < f`.

**pytest config (T18–T19):** `pytestconfig.getini("timeout")` is `"30"`. Reviewer check: `test_a_held_boundary_waits_when_a_question_is_open` present, injects `sleep` (fake posts answer, records `[5.0]`), no skip/xfail/deselect.

Coverage ≥95%, ruff clean. See ADR-0030, design `agile-team/docs/design/s43.md` (test checklist).

## s62: Tell/watch commands, resume from dirty tree, frozen uv, self-hosting

Test coverage from design checklist:

**Tell (T1–T6):** `Relay.tell("text")` writes `t<N>.md` exactly, race to `t<N+1>`, draft unlinked always. `t1, t5, msg-…` present → next is `t6`. `cmd_tell` with file/stdin, prints `queued <id> for the PO: <path>`, no state mutation. Whitespace-only → exit 1. Missing file → exit 1. Works in checkout-changed status.

**Delivery (T5–T7):** Router pass has `human_message` trigger, message line without text, state.told extended, never re-delivered. With answer + message → one pass, answer first. While waiting (s47 driver pattern) → message ends wait. Halted run → message on resume first prompt. AC6 checkout halt + tell + accept → message delivered. `status.queued_messages` before/after delivery.

**Watch (V1–V7, tested with fake Pace):** First watch with message + running → triggers `["message"]`, `was.status=null`. Second watch + timeout → heartbeat line. Message during sleep → fired at next poll. Torn line → no crash, next poll retries. Outbox shorter → every entry new. Unreadable `watch.json` → fresh. `cmd_watch` prints one JSON line, exits 0. TRIGGERS names are `("message", "status")` in order.

**Resume (R1–R4):** Killed run (dead pid, dirty tree) → `start --resume` salvages before preflight, stderr says `the last run was killed`. Checkout halt (dirty tree) + accept + resume → salvages with `unsaved=cause`, stderr says `halted (checkout)`. `PoRun.run` clears `unsaved` at start. Dirty tree + plain start → still refused.

**Pin script:** `.team/run/runner-pin/pyproject.toml` exists, `.commit` is sha + newline. Re-pin replaces tree, no `.new` left. P2 refusals: exit 2 on usage, exit 1 on others, existing pin unchanged. Each refusal exact (unknown commit, not-on-branch, no pyproject, runner live, not-a-repo). Run from subdirectory → still roots.

**Docs/CI (F1–F3):** Every `uv run --project …` in SKILL.md, protocol.md, self-hosting.md, README has `--frozen`. Test with self-check. Both workflows use `--locked` everywhere. `agile-team.yml` paths include F3 entries.

Coverage ≥95%, ruff clean. See ADR-0029, design `agile-team/docs/design/s62.md` test checklist.

## s61: Checkout guard halts when branch or commit changes externally

The runner now detects when the checkout changes under it (branch switched, commit reset, HEAD detached, or a git operation in progress). Test checklist from design section 8: `checkout.py` functions (read, operation, matches, check, last_move, answer_open, recorded), `Found` and `Drift` dataclasses, `Guard` class (on_start, accept); `CheckoutRecord` and `RunStatus.CHECKOUT_CHANGED`; halt table and budget advice; five parametrised runtime test cases (detached, branch switched, reset, foreign commit, rebase in progress); each halts before next step with no crash.log, no commit, no gate, reason exact. CLI tests: start --resume exits 78 twice with one question, restore answers, accept-checkout keeps HEAD and updates record, both refuse live runner / detached HEAD / operation. All coverage ≥95%, ruff clean. See ADR-0028, design `agile-team/docs/design/s61.md` test checklist.

## s58: Sandbox e2e test for local service binding on macOS

Write `tests/e2e/test_proxy_sandbox_e2e.py` with a `pytest.mark.skipif` for non-macOS platforms. Test uses a scripted model (stdlib HTTP server on a thread) and real bundled claude CLI. Build real sandbox settings with a `web` delivery, run with and without the `network` key, and assert: (1) with key: exit 0, tool result contains `200 exit=0`; (2) without key: tool result contains `exit=7`. Write `tests/test_sandbox.py` unit tests: `web` delivery has `network: {"allowLocalBinding": True}` (N1, V2), non-service kinds have no `network` key (N2), filesystem keys unchanged (N2), returned dict mutation leaves module constant unchanged (N3), docstring lacks "Not verified" and names the e2e test (V2). Write dispatch Proxy plan tests: `Prepared.stop` called once, after `query_fn` returns or raises (L1). Coverage ≥95%, ruff clean. See ADR-0026, design `agile-team/docs/design/s58.md` (test checklist).

## s47: Router wait (W1–W6); status_reason shows waiting; halt note suffix

Router wait is unchanged (W1); your tests verify a driver-level path with mocked sleep and answer hand-over. New `Relay` tests: `waits()` maps stories to ids in first-seen order, `waiting()` joins them with `WAITING_HEAD` prefix. `Router` tests: `_show_wait()` sets/saves reason only on change, `_clear_wait()` strips `WAITING_HEAD`, `_end_wait()` saves if cleared. Halt test: opened question adds "; waiting on …" suffix to note, stored reason stays halt reason alone. No change to stall lines. See design `agile-team/docs/design/s47.md` test checklist; ADR-0025.

## s46: Rework gate when code is in; dispute output in brief

Your gate at `tests` now checks whether code is already in the branch (K2, K3). If `implemented == 0` but a developer commit is an ancestor of HEAD, the story is reworked: green suite passes with `"tests": "confirmed"` claim, bounces without it. First-pass logic unchanged. While a dispute is open, your brief shows the test command output when it was raised (D2–D3), so you see what failed. Dispute brief adds a `Test dispute (…)` line with: test id, contradicted rule, reason. If output is set, the next line shows the command output. See ADR-0024, design `agile-team/docs/design/s46.md` (K3–K5, D1–D3, test checklist).

## s45: Crash logging, fault rulings, continue_story block

Crash log now captures all role-step exceptions exactly once, faults work on any story, and blocked stories cannot be released. Test areas (design section 7, test_s45.py):

1. **Crash log (AC3):** TypeError in `settle`, `_execute`, `plan` each gives one `crash.log` entry; through router and limit halt also log once; settle crash saves edits.
2. **Manager step (AC2):** Real `Runtime.emit` path (no mock) with each fault/ruling case (pipeline/off_pipeline/runner, capped story/repeated); old signature fails with `TypeError`.
3. **Faults on any story (AC5-AC6):** Blocked story with fault → moves, status changes, hold/rounds/disputes cleared; runner fault → stays blocked, held `runner_fault`; fault without story → `applied: false`; done story fault → `applied: false`; unknown fault → `applied: false` with new wording.
4. **Ruling after fault (M5):** Unapplied fault → ruling also unapplied with `RULING_AFTER_FAULT`; applied fault → ruling merges and wins.
5. **Continue_story blocked (AC7):** Blocked story (with or without hold) refused with `CONTINUE_BLOCKED`; active/done unchanged.

Existing tests (`test_s27_backstop.py`, others) may need M7 wording updates (RUNNER_FAULT_NOTE, OFF_PIPELINE_FAULT, FAULT_NOT_APPLIED). Change expected strings only. See ADR-0023, design `agile-team/docs/design/s45.md`.

## s38: Corrected budget numbers and ceiling

Budget correction on read + ceiling halts run. Test coverage from design section 8:

1. **`corrected()` function:** worked example (legacy PO running totals → own costs), non-legacy pass-through, empty list, missing `at` field (legacy), no mutations.
2. **`Ledger` changes:** `entries()` corrected, `last_cost(PO)` raw, `overcount()` difference, `budget_status` has `po_overcount_usd`.
3. **`halt.budget_halt()`:** below → None, at → Halt with exact reason, rounding matches `budget_status`.
4. **`Runtime.enforce_ceiling()`:** called after steps land, after PO ledgers, at start before opening; below → no halt, at/over → halt with one note.
5. **Role step reaches ceiling (B2a, B7):** step lands normally, run halts, next step refused.
6. **PO query reaches ceiling (B2b):** ledger entry halts run, no further query (renewal → no main query).
7. **AC4 sequence:** through `cli.main([...])`, real config load, preflight runs. Below/reaches/over at start/raise+commit/resume without raise.

Coverage ≥95%, ruff clean. See ADR-007, design `agile-team/docs/design/s38.md` test checklist.

## s21: Dashboard fixes — toggle, live config, responsive board

Dashboard page tests (`tests/test_dashboard_ui.py`), snapshot and server tests. Key test areas:

1. **Fresh config (F5):** `test_build_rereads_budget_and_round_cap` rewrites `.agile-team.toml` with same `Config` object, asserts new values; `test_build_falls_back_when_file_missing_or_unparsable` covers missing, invalid TOML, and asserts `fresh is config` (fallback).
2. **Watched files (F6):** `test_watched_files_lists_inputs_only` updated to expect config file at position 6; server test `test_config_file_is_watched_and_budget_is_live` bumps mtime, checks fingerprint and budget update.
3. **UI toggle (F1):** Script holds `data-unit`, `ui.unit`, `UNITS` keys, `renderUnit`, `barRows`, `costRow`, `costLegend`, `tokenLegend` functions; click handler uses `closest("[data-unit]")` and calls `render()`.
4. **Only that chart (F2):** Cut bodies of `renderSpend`, `renderTiles`, `renderTables`, `renderHeader` — none contain `ui.unit`; `renderBars` (or `barRows`) does.
5. **Survives updates (F3):** `test_unit_survives_live_updates` greps `normalize`, `connectLive`, `render`, `boot` for no `ui.unit =` assignments; exactly one in click handler.
6. **Board layout (F7–F9):** `.board` rule has `display: flex`, no `overflow-x`, no `190px`. `.col` has `flex: 1 1 0; min-width: 0; overflow: hidden`. `.col.empty` is `flex: 0 0 44px`. `.story` has `overflow-wrap: anywhere`. Test arithmetic: 10 empty × 44px + 9 gaps × 8px ≤ 1280 − padding.

See ADR-0021, ADR-0022, design `agile-team/docs/design/s21.md` test checklist.

## s30: Dispute gate now checks content, not commits

The dispute gate (s11 T6) now compares the disputed test file's **content hash** against the baseline stored when the dispute was raised, ignoring whitespace and comments. A real change passes; cosmetic (comment/whitespace only) or no change bounces with reason including file and baseline hash. New: test file paths are resolved to repo root at raise time; unresolvable paths are rejected with `UNTRACKED`. Test checklist (design section 7): fingerprint tests (comments, blanks, indents, assertions, strings), resolution (exact + suffix matching, git ls-files), raise (resolve, baseline capture, unresolvable bounce), gate (real/cosmetic/no change, confirmed, legacy, no git command), repeat escalates. See ADR-0019, design `agile-team/docs/design/s30.md`.

## s9: Interrupted steps—save and offer edits, not stash them

When a role step is cut short, the runner saves its edits in a commit + revert. On resume, the edits are offered to the next step on that story. Test coverage checklist (16 areas from design section 7):

1. **In-flight tracking (I1–I2):** During a role step, `in_flight = {role, story, brief}` (brief is the request's brief, no runner additions). After `settle`, it is `None`. A refused step never sets it.
2. **Save tree (I3, AC7):** Interrupted step with one in-scope and one out-of-scope file: both in commit, revert follows, tree clean, subject `chore(team): interrupted step by <label>`, no `QUARANTINE` event. `story.commit`, step, rounds unchanged.
3. **Capture (I4):** No step in flight + clean tree → `None`. In flight + clean tree → interruption with `sha=None` (pending list, not story). No step in flight + dirty tree → `product-owner` with no story.
4. **Limit halt (I5, AC2):** Note text = `message()` + suffix with sha from state; stderr unchanged. Second `halt_run` records nothing new.
5. **Halt at top level (I5, SIGTERM, crash):** In-flight role set. Tree clean after exit. Cause `sigterm` or `crash`.
6. **Error (I6):** Non-limit exception still propagates (s8 holds). Tree clean. Story has `interrupted` with cause `error`. `state.interrupted` empty.
7. **Salvage robustness (I8):** `git.commit` raises → halt completes, tree dirty, `GitError` in `crash.log`, nothing recorded.
8. **Resume after kill (I9, AC7, AC3):** State `running`, `in_flight` set, dead pid in `runner.pid` (and separately, no `runner.pid`), dirty tree. `start --resume` saves cause `killed`, preflight passes, stderr names sha.
9. **Still refused (I9, AC7):** Dirty tree with status `idle`; `running` + live pid; `running` + dead pid + plain `start --task`. Each exits 1, no commit.
10. **Offer in next brief (I10, AC8):** For each cause (error, limit, crash, sigterm, killed): next role on story gets exact offer with sha from `state.json`. After step settles, offer gone. Later interruption no sha keeps earlier offer.
11. **Resume prompt (I11, AC4):** Session resumed, no `--task`, pending interruption → first query is PO turn (not router pass) with `## Interrupted steps` section, role, story, brief, cherry-pick line. `state.interrupted` empty after. With `--task`, section after "New from the human". No session → after `first_prompt`. Empty list → unchanged.
12. **Liveness (I12, AC5):** `runner_pid` handles missing file, `"abc"`, `"0"`, `"-5"` → `None`. `pid_alive` maps `ProcessLookupError` → `False`, `PermissionError` → `True`. Monkeypatch `os.kill`.
13. **Shown status (I13, AC5, AC7):** State `running` + dead pid → `"status": "interrupted"`, `"running": false`. State `running` + live pid → `"running": true`. Others pass through. `state.json` stays `running` (never stored).
14. **Status keys (I14):** `status_report["in_flight"]` and `status_report["interrupted"]` right after `"running"`. Stories carry their `interrupted` field in `asdict`.
15. **Legacy state (I15):** Load `state.json` without `in_flight`, `interrupted`, story `interrupted` → defaults to `None` / `[]`. Cause string round-trips via `Cause(cause)`.
16. **Coverage ≥95% (currently 100%); ruff check and ruff format clean (AC7).**

Contract changes: Fixture has `in_flight` and `interrupted` fields; `status_report` keys are new. See design checklist for exact strings and cause values. ADR-0017.

## s40: Story priority ranking and explicit order

The router now ranks stories by an explicit priority order instead of creation order. Test coverage checklist:

1. **Ranking rule (P2):** `Priority.key()` = `(done, listed, not in_progress, natural(id))`. Done stories last. Explicit position beats in-progress. In-progress breaks ties among unlisted stories. Natural id sorts digit runs as numbers (s9 < s10).
2. **Order state (P1, P7):** `RunState.order` persists in state.json. Legacy load without it takes `[]`. After any change, order holds the full unfinished queue.
3. **PO tools (P5–P8, AC2):** `prioritise(ids, reason)` sets order and refuses unknown/done/empty. `move_story(story, position, reason)` moves to 1–queue_length, refuses unknown/done/bad position. `start_sprint` treats list as order.
4. **Router by order (AC3):** `_story_work` and `_repeat_work` pick first movable story in `priority().ranked()`, not creation order.
5. **Hold semantics (P4, AC6):** Held story skipped by router; position never changes. `continue_story` releases it to run from original position.
6. **Waits (W1–W2, AC6):** `waits.wait()` returns first matching `WAITS` row (blocked→needs human, needs_manager + repeated→manager, needs_manager→round cap, questions hold, any hold, open asking). Board shows hold pill and reason.
7. **Events (P9, AC5):** `priority` event on every change: set/move/sprint, full order, moves (1-based from→to), reason. Timeline shows label and meta.
8. **Snapshot (D1–D5, AC4):** `run.order` = queue. Stories in ranking order. Each story: `position` (int/null), `in_progress` (bool), `hold` (str/null), `wait` ({reason, on}/null).

Fixture gains `order` key, story `position`/`in_progress`/`hold`/`wait` fields, and at least one held story with open question matching it. Timeline has one `priority` event with move.

Contract changes: `story_status` returns `order` key, `story_status_data` iterates `ranked()`. `start_sprint` emits `priority` event after `sprint-start`. Tests bouncing a story twice need `repeat=2` config or change reasons. Coverage ≥95%; ruff clean. See design `agile-team/docs/design/s40.md` (test checklist).

## s11: Test dispute gate and test-dispute events

When a developer hands off from `implement` with a `dispute`, the story goes to `tests` with `story.dispute` set. Your gate is now `checks.dispute_settled(dispute)` while it's open:
- `done` + file changed (git diff exit 1) → pass to `implement` (dispute cleared)
- `done` + file unchanged → bounce to `tests` (reason: "the disputed test file {file} has not changed…", round +1)
- `changes_requested` + `next_role: architect` → move to `design`, set `dispute.stage = confirmed`, round +1

Your brief line (T9): `Test dispute (raised): {test} contradicts {rule}: {reason}` while open, `(confirmed)` after architect is scheduled. Test coverage: dispute settled gate (exit codes 1/0/128), confirmed status, `changes_requested` → architect, unchanged file bounce reason exact, tests_red not called while dispute open. See ADR-0018, design `agile-team/docs/design/s11.md`.

## s29: Boundary runner tests (sync, rebuild, check, push, stacked PRs)

Sprint boundaries are runner steps that execute at start and end. Key test areas from the design checklist:

1. **Skip conditions (U4):** No remote, empty remote, fetch fail, no target → one `skipped` event, no other stage.
2. **Merge in (U5):** Upstream commit merges (HEAD moves), no commit on no new upstream, recompute all shas as ancestors, merge conflict → hold `sync_conflict`, tree unchanged, exact hand-over text.
3. **Full checks (U7):** Order: lint, static, test, coverage, then e2e per delivery. Every check runs; none skipped. Coverage baseline applies. Reason format exact.
4. **Team fix (U9–U11):** Fail on team branch → `failure` set, next work `devops` with brief quoting output. After done, `rounds==1`, check reruns, pass moves on.
5. **Stack and rebuild (U6, U8, U15–U16):** Entries added at end, ranges drop merged entries. Cherry-pick loop handles real conflicts and empty picks. Rerere replays recorded resolutions. Bottom and top checked once each (skipped if `checked==head`).
6. **Push (U17, U19):** Permission `unasked` → hold `push_permission`, branches listed, hand-over exact. Permission `no` → `local` report, done. Permission `yes` → branches pushed with lease, no team branch or main push.
7. **PRs (U18):** Bottom created `ready` with base main, others `draft` with base = previous branch. Body has `STACKED_LINE` (not on bottom). Rerun edits only what differs. After bottom merges, next PR's base → main, mode → ready. Closed PR left alone with `CLOSED_NOTE`.
8. **Finish (U22):** End boundary finishes with `done`, `closed==sprint`, report set. Sprint-end note includes `Review: <report>`. Start boundary without restack finishes after `check`.
9. **Errors (U3):** Exception in stage → hold `error`, traceback in `crash.log`, `boundary_error` hand-over, `continue_boundary` reruns.
10. **Permission tool (U20):** `set_push_permission("yes"|"no")` emits `boundary` event, clears hold, refused on other values.
11. **Continue tool (U21):** `continue_boundary(note)` refuses on no boundary or unheld; clears hold, failure, streak/rounds on escalated/reviewed.
12. **Dashboard (U25):** Snapshot has `upstream` shape (stack, boundary), fixture keys match builder, Review stack card renders from fixture, timeline has `boundary` rows.

Contract changes: `start_sprint` opens a boundary (one step, event); sprint-end note lines may include `Review:`. See design `agile-team/docs/design/s29.md` (test checklist section) and ADR-0015.

## s24: Reworked stories and test claims

When a story returns to `tests` with code from an earlier pass (ruling, review, or dispute), the brief says `Code from an earlier pass is in`. The suite may already be green. If so and you've updated tests, hand off `done` with `"tests": "changed"`. If existing tests already cover the new design, hand off `done` with `"tests": "confirmed"`. Without a claim, a green suite bounces once with `tests pass on code from an earlier pass; write a failing test, or hand off "tests": "changed" or "tests": "confirmed"`. On a first pass (no brief line), the old rule holds: green bounces with `tests pass before implementation; write a failing test`.

See ADR-0012; design `agile-team/docs/design/s24.md` (rules G1–G9, unit-tester's role file).

## Context reduction: work lean (s23)

Your session context is reduced by disabling Claude.ai connectors and following guided reads:

- **No connectors:** You cannot use Claude.ai integrations during your step (other roles don't either, except PO and Proxy). Focus on code.
- **Start from design:** Each story has a focused `docs/design/<id>.md` with rules, exact signatures, and a test checklist. Read only helpers you reuse; read source only for what the design leaves open.
- **Read little:** Find with Grep before reading. Use `Read` with `offset` and `limit` to target lines. Never `cat` long files; avoid double-reads. Run tests quietly and fail-fast.
- **Write lean:** Write test files in one go with `Write`, fix with `Edit`. See the design's test checklist for what to cover.

Target context per turn: under 60k tokens (s19 was 113.9k). See ADR-0011.

## s25: Cost delta tracking – test notes

s25 fixed PO cost overcounting by ledgering only the delta from the previous running total per session. Key test cases (design checklist section 8):

1. `SessionCost.own_cost()`: 7 cases (fresh, same-session delta, other session, equal, drop, default store, `None` mismatch).
2. `Ledger.last_cost()`: role lookups, ignoring other roles' entries, empty ledger → 0.0.
3. `RunState` round-trip: `po_cost` persists as `SessionCost`; missing key loads `None` (legacy files).
4. **Resumed session deltas:** three PO turns reporting running totals 1.0, 1.5, 2.25 ledger as 1.0, 0.5, 0.75.
5. **Across processes:** `po_cost` from saved state is used; new process with same session gets the delta.
6. **Handoff renewal:** `po_cost` from old session, fresh session ID → entry is full amount.
7. **Legacy seed (C6):** `po_cost = None`, `po_session = "old"`, ledger has PO entries → delta against last PO cost.
8. **Drop (counter reset):** `po_cost` higher than reported → entry is just reported.
9. **No result:** `ResultMessage` is None → `po_cost` unchanged, ledger 0.0.
10. **Free provider:** `po_cost.reported` stores raw total; ledger entry is 0.0.
11. **Checkpoint:** real spend (not running total) triggers checkpoint.
12. **Role steps:** `resume=None` always; own cost equals reported cost.

A contract change: tests that assert a resumed PO entry's cost must now use design rule C1. `conftest.FakeQuery` returns the same cost/session per call; for deltas, use a fake that returns a list `[1.0, 1.5, 2.25]`. See design section 7 "Test checklist".

## Process constraint: developer cannot edit tests

The developer role cannot write to `tests/unit/` or `tests/conftest.py`. Before finishing, verify every test matches the design. If a test passes but doesn't match what the developer built, update the test (not the feature).

## s19: Routing in code – test notes

Code review passed with one blocking defect (D1: done stories with holds were not scribed) found and fixed in round 2. Final coverage 99% (router and handover at 100%), all 964 tests pass.

Design's test checklist (section 7 of `agile-team/docs/design/s19.md`) calls for 12 areas:
1. **Automatic advance** (AC1): one `run_po` runs architect through pipeline to done, scribe, then hands `SPRINT_END` to PO; assert step order and PO query count (2).
2. **Standard brief** (AC1, AC3): each BRIEF_PATHS case (design file/architecture fallback, review present/absent), previous with/without summary, bounce/return verdicts, pass suppresses "Sent back", note line, scribe and Manager headings.
3. **Hand-over triggers** (AC2): parametrized test per HANDOVERS row; multi-match gives all in order; clean `done` gives none. Router: `HUMAN_MESSAGE`, `SPRINT_END`, `STALLED` cases, wait (R8), quiet end (R9), round cap.
4. **Holds** (R6): report → hold, router skips held story, `continue_story` clears hold and note, PO step clears hold, refused PO step leaves state untouched.
5. **Bounce briefs** (AC3): `changes_requested` with `next_role: developer-gui` → next step runs that role with "Sent back" line. Red gate → same developer reruns with test tail.
6. **Specialisation choice** (AC4): parametrized over ROLE_HINTS; `po_developer` beats bounce, bounce beats architect pick, retry keeps `previous.role`. Architect sets `story.developer`, other roles do not. Bad `developer` field is a bad handoff. Three `set_developer` refusals.
7. **Automatic Scribe and Manager** (AC5): done story queues `scribe_due`, router runs scribe next with scribe heading. Scribe entry cleared on bad handoff (which hands over). Done story blocked by open question is skipped until answered. Held done story is scribed (D1 fix: `_scribable` allows unheld or DONE). `manager_due` makes router run manager story-less before any story step.
8. **Driver ends** (R10): stop file, limit halt in router step (no PO turn, exit 75), `notify_user` sprint-end (each end the run). Status ends `idle` only when still `running`.
9. **Errors** (R18): step raises RuntimeError → `error` report, crash logged, story held. Limit halts (not Exception), so not caught.
10. **State** (R16, legacy): old state.json loads with new fields defaulting to None/[]. `previous` round-trips. `delivered=None` → every existing answer id (old answers never handed over).
11. **Event** (R17): each hand-over turn preceded by one `handover` event with correct trigger/story/step counts.
12. **Coverage ≥95%** (target 100%), `ruff check` and `ruff format` clean (AC7).

Pitfall for round-trip tests (previous, delivered, scribe_due): nested dataclasses and lists; use `NESTED` dict to deserialize.

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

## s4: Dashboard backend – snapshot builder and read-only server

Test the snapshot builder (`build(config, book)`) against the fixture shape (AC3). Each section builder is under 8 lines and reads only its source files: `state.json`, `ledger.jsonl`, `events.jsonl`, `outbox.jsonl`, `inbox.jsonl`, story frontmatter, requirement files. Missing files give empty sections; torn JSONL lines are skipped (D3, D4). Coverage areas:

1. **Fixture match (AC3):** `test_build_matches_fixture_shape` checks all 11 keys exist in correct order and value types match after round-trip.
2. **Section builders (S2):** Each builder is pure (no writes, no git, no network except `time.time()`). Test: run from temp dir, no side effects.
3. **Missing files (D3):** Missing `state.json` → `RunState()` defaults; missing story file → frontmatter empty; missing REQ → row with defaults; torn ledger line → skipped.
4. **Server routes (AC4, D5):** Three exact routes: `GET /` (index.html from package), `GET /api/snapshot` (JSON), `GET /api/stream` (SSE). Any other path → 404. No file paths built from requests.
5. **SSE file watching (AC4, D6):** Fingerprint (mtimes, sizes) triggers on first tick and when changed, otherwise keepalive. 5 concurrent clients, each gets fresh snapshot on connect, both reconnect without hanging.
6. **CLI host/port (AC5, AC6, D7):** `default_host()` returns `0.0.0.0` except Windows (`127.0.0.1`). `--port 0` finds free port. Hostname URL when all-interfaces. `--no-open` skips browser. Bind error → exit 1 with exact error message.
7. **Coverage ≥95%, ruff clean.**

Known gaps (accepted at review, not contract changes): typed input (`covers: 5`), some disconnect errors, hostname resolution on the network. See ADR-0027, design `agile-team/docs/architecture.md` § "s4: Dashboard backend" (rules S1–S7).

## s26: Service lifecycle and liveness testing

s26 added service startup, probe, and liveness testing. Key test areas:

1. **Absolute paths (L1):** Relative `--repo` resolves to absolute; `expand` with relative repo gives absolute `{repo}` and `{sandbox}`.
2. **Placeholders (L2):** `{host}` and `{port}` from `http://127.0.0.1:8799/`, from `http://h/` (default 80), no url.
3. **Liveness data (L3):** `PRESENTATIONS["web"].check is Check.SERVICE`; others are `FILES`; SERVICE ⇔ BACKGROUND `Start` kind.
4. **Start and probe (L4–L5):** Fake `popen` with live process, probe true on 3rd call → prepare returns, sleep twice, pid/log files exist. Probe fail: process exited → `NotUp` "exited with code X", never answers → `NotUp` "did not answer…within Ys". **Real hung process test:** `exec sleep 60`, `attempts=2` → "did not answer…within 0.5s", never "exited with code -15" (reason before stop).
5. **Stale cleanup (L7):** Start real sleep, write pid, `stop_stale` → gone, file gone. Dead pid → silent. **SIGKILL escalation test:** trap TERM, `STOP_WAIT_S=0.2`, assert `-SIGKILL`.
6. **Port conflict (L8):** `listening` true → `PortBusy` exact text, `popen` never called. `port_in_use` true for bound socket.
7. **Teardown (L9):** `Prepared.stop` idempotent, deletes pid file. `Runtime.plan` exception after prepare → `stop` called.
8. **Gate trial (L10):** Missing files → bounce (liveness never called). Files ok + `liveness` pass → pass. `NotUp` → bounce e2e, round +1. `PortBusy` → hold, rounds unchanged. `Check.FILES` never calls prepare.
9. **Return (L11):** Fake `prepare_fn` raising `NotUp` → returned, no round, no query. No e2e → refused.
10. **Gate hold (L12):** Report with `hold` verdict → `GATE_HOLD` line with reason. Blocked → `STOPPED`.
11. **Make pipeline:** Wires `Trial(config).liveness`.
12. **HTTP probe (L5):** Real `ThreadingHTTPServer`: 200 JSON → true, 204/201 → false, 500 → false, nothing listening → false.

Coverage 100%, ruff clean. See design `agile-team/docs/design/s26.md` test checklist.

## s27: Repeated setback escalation and backstop

s27 detects when a story bounces for the same reason and escalates to the Manager instead of looping. Key test areas:

1. **Normalisation (L2):** `test_loops.py` asserts each NORMALISE pattern exactly; same reason with different numbers/ports/paths/ids/times/shas gives one key; stored keys recompute on load.
2. **Streak (L3):** `extend` appends on same key, restarts on different; `repeats` is 0 for empty or different last key, else `len(streak)`.
3. **Repeat rule (L4–L5):** With `repeat=2`, first setback bounces (move, +1 round); second same-key setback → `ESCALATE`, step/rounds unchanged, `NEEDS_MANAGER`. With `repeat=3`, escalation on third. Different reason resets. A pass in between does **not** reset. Dispute never counts.
4. **All setback kinds (L1):** `changes_requested` bounce, command-gate bounce, `blocked` hold, `NotUp` return, malformed handoff — each lands in `streak` with gate event id. On repeat, each escalates.
5. **Escalation event (L5):** `escalation` event (not `gate`) carries `step`, `verdict: "escalate"`, `reason`, `now_at` (=step), `story_status: "needs_manager"`, `rounds` (unchanged), `key`, `author`, `count`, `history` (earlier event ids). Repeat escalation has `rule: "repeat"`.
6. **Zero rounds (L6):** Before/after escalation equal. Manager adds none. After applied fault: `rounds==0`, `disputes==0`, `streak==[]`, `repeated is None`.
7. **Manager hand-over (L7):** Escalated story queues Manager with `REPEAT_HEADING` (count 2) in brief, `repeated_setback` in context. Router picks it before Scribe. Held escalated story waits for `continue_story`. Open question blocks it too.
8. **Fault (L8):** `fault: "integration-tester"` → step `e2e`, `active`, `fault` event kind `pipeline`, applied true. `fault: "devops"` → step kept, `off_pipeline_fault` hand-over. `fault: "runner"` → `blocked`, event kind `runner`, outbox note, `runner_fault` hand-over.
9. **Fault refusal (L9):** Missing → `FAULT_MISSING`. Unknown name → `FAULT_UNKNOWN`. Story unchanged, ruling not applied, `fault_not_applied` hand-over.
10. **Fault + ruling (L10):** `fault: "developer-cli"` + `ruling: "revise_design"` → step `design`, both in report. On non-repeated story, `fault` ignored.
11. **Backstop (B1–B4):** `extend_run` appends on same pair (different reasons OK), restarts on new pair. `bounces` is 0 for empty/different pair/hold/in-place, else `len(run)`. With `backstop=4`, fourth bounce between same steps escalates with `rule: BACKSTOP`, regardless of reason.
12. **Pass reset (B3):** `after_pass(run, upper)` returns `[]` when upper step just passed; `after_pass(run, lower/other)` returns `run` unchanged. Both fault and ruling clear `run` and `escalated_by`.
13. **Backstop vs. repeat (B5):** Both fire; repeat wins. Neither resets the other.
14. **Config/state (L16):** `gates.repeat ≥ 2` (default 2), `gates.backstop ≥ 2` (default 4). `streak`, `repeated`, `run`, `escalated_by` round-trip in `state.json`; older files load with `[]`/`None`.
15. **Dashboard (L17, B9):** Snapshot stories have `repeated`. Board shows `needs_manager · repeat`, reason line. Timeline: `escalation` event (`repeat` or `backstop`), `fault` event. Replay handles both.

Contract changes: `Pipeline(...)` gains `repeat` and `backstop` (both with defaults). Tests bouncing the same reason 2+ or same pair 4+ times must adjust these or change the reason to keep intent.

Coverage ≥95%; ruff clean. See design `agile-team/docs/design/s27.md` test checklist (18 areas).

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. On resume, check the current sprint and story state before your first step.
