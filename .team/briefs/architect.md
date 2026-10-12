# Architect: Current context and conventions

**Last updated:** 2026-10-12 (s72 done)

## s72: Timeout limits follow the world concept from s71

Per-test limits are data-driven: `LIMIT_INI[world]` maps s71's world enum to pytest-timeout's ini keys. FAKE world (unit tests) → 1 second; REAL world (e2e + LEGACY) → 30 seconds. One function `limit_of(item)` reads the limit from config; one function `mark(items)` applies markers at collection. Conftest registers the e2e limit ini so pytest doesn't warn. No code branches on paths or test names—the world decides the limit (O1 from s71). Consequence: when s76/s77 move LEGACY files out, they inherit 1s with no further change.

## s71: Unit tests run no OS calls — one seam with fake and audit (P1: files, clock)

All OS calls now flow through `agile_team/system.py`, a thin seam that unit tests swap for a fake. Architectural patterns:

**One module decides all OS:** `system.py` is the only place the real OS is touched. Thin functions with no logic (one call, maybe one line of shaping). Every function in `system.__all__` is swappable: `system.read_text(path)`, `system.run(command)`, `system.now()`, etc. This concentrates OS interaction in one place, making it auditable and testable.

**Import discipline:** Every other module does `from agile_team import system` (never `from agile_team.system import func`, which binds at import before the test can swap). Calls go through `system.func(...)` at the use site. This discipline will be enforced by ruff `TID251` in P3.

**Fake system for unit tests:** An autouse fixture installs a fresh `FakeSystem` (in-memory files, command scripting, package data) for every unit test. Files are normalised posixpaths with mtime and mode; the fake records every write in `ops` (useful for assertions). The fake can fail: `deny(path)` makes reads raise `PermissionError`; `fill_disk()` makes writes raise `ENOSPC`. Commands are scripted via a `reply()` rule table; unmatched commands return success by default.

**Audit hook + patches at runtime:** `sys.addaudithook(os_guard.hook)` fires on every OS audit event. While a unit test (not `tests/e2e/`) runs:
- If the event is audited and the caller is in `agile_team.*` or `tests.*`, raise `RealOsCall` with guidance: "inject it, or move the test to tests/e2e/".
- Exempt callers (import machinery, `coverage`, etc.) pass through.
- For calls with no audit event (pid, sleep, `platform`, `which`), a `PATCHED` table wraps them to raise for test code.
- Violations are recorded; if the test swallows the `RealOsCall`, the guard fails at teardown.

**Three phases keep the suite green:** P1 (s71) migrates P1 modules and tests; P2 (s76) migrates processes, signals, network; P3 (s77) migrates runtime, CLI, close. Until then, `LEGACY` files run on the real seam. Each phase removes LEGACY rows.

**Consequences:**
- Tests run in milliseconds; no tmp files left; clean isolation.
- Realistic OS failures (full disk, missing files, permissions, hung processes) are scriptable.
- Safe refactoring: moving OS calls or renaming functions is caught at test time.
- Package data (roles, presets, dashboard HTML) live in both fake and real worlds, so the same reader code works in all tests.

Pattern: One module (`system.py`) that all code uses. Two enforcement layers (fake at test time, audit hook + patches at runtime). Three phases to migrate without breaking. ADR-0036, design `agile-team/docs/design/s71.md` (rules O1–O17, modules per phase, test checklist).

## s70: Parallel test suite with pytest-xdist; gate cycle time drops to 1 minute

The runner's test suite now runs in parallel on multi-core machines. Cycle time drops from ~4 minutes to ~1 minute on 10 cores. Architectural patterns:

**Injection pattern:** The runner's own ids (pid, process group) are injected into `sandbox.stop_stale()` via `process_groups.RunnerIds`. This allows the test to pass fixed fakes and stay stable across xdist workers, while proving the runner never signals itself—even by accident.

**Test ID stability:** xdist refuses to run when workers collect different test IDs. One test was parametrized with `os.getpid()` and `os.getpgrp()` (live at collection time), creating different IDs in each worker. Fixed by using static labels (`ids=["pid", "pgrp"]`) and resolving live values inside the test body.

**Verification:** New `test_s70_ids.py` collects the suite in two processes at once and asserts both IDs are identical and non-empty. This catches any future parametrize that holds a live value by failing loudly on the difference.

**Coverage combination:** pytest-cov combines coverage across workers into one `TOTAL` line (controller output). Gate parser reads it unchanged. Combined coverage is 99.67%.

**Config pattern:** Commands opt in with `-n auto` (gate test/coverage, targeted runs, CI). `addopts` stays without `-n`, so a named test from a role's Bash stays serial (faster for one test). `python` preset unchanged (users may not have pytest-xdist).

See ADR-0035, design `agile-team/docs/design/s70.md`.

## s68: Single coverage run replaces test + coverage gate command pair

**Architectural pattern:** Gate command compression. The implement gate was calling two sequential commands (test, then coverage), each full-suite run. Coverage run already runs tests, so its exit code is redundant with the test command's exit code. New design: **one coverage run** proves both test pass and coverage figure.

**Test failure detection via patterns (C6):** Instead of relying on a separate test command, the gate detects test failures from the coverage command's output using regex patterns (`TEST_FAILURES` tuple). Known formats: pytest `N failed`, go `--- FAIL:`, etc. Unknown tools fall to the safe side: bounce `tests fail:` and keep the output tail.

**Branching (C4–C5):** Non-zero exit from coverage command:
- If test failure detected (pattern match) → bounce `tests fail:\n{tail}` (C5)
- Else if coverage below threshold → bounce `coverage {pct}% is below {req}%` (C4: shortfall-only case)
- Else → bounce `tests fail:\n{tail}` (C5: unknown, safe side)

**Consequence:** Cycle time ~4 minutes (one suite run) instead of 7–9 minutes. Known consequence: a repo with baseline coverage debt *and* a coverage command's own `fail_under` above that baseline will now bounce `tests fail` instead of passing (correct behavior; repo must fix its config).

**Gate interface unchanged:** bounce_to, round counting, and event shape all stay the same. Shared constant `TESTS_FAIL` for DRY bounce text. See ADR-0033, design `agile-team/docs/design/s68.md`.

## s44: Live meter, heartbeat, and health rules (decisions verified)

The runner measures every turn from the model stream, keeps a heartbeat file fresh via daemon thread, and judges health from one rule table. Key architectural decisions in ADR-0032:

**D2:** Heartbeat written by daemon thread, not asyncio task. Gate commands block the event loop for up to 300s; an asyncio task would stop and falsely turn red. Thread keeps beating through all runner work, stops only when process dies (the signal we catch).

**D3:** One health rule table in Python. `health.RULES` is the single source of truth. Verdict lives in snapshot. Server pushes on verdict change, even if files don't change (killed runner → stale heartbeat → red).

**D8:** Quiet clock (time since model last had the floor) resets when model gets it back: on turn, tool close, inner meter close, or chore end. Keeps PO meter from going red during long role steps.

All round-1 items verified (Python 100%, UI tests under node, no leftover copies). E2E tests and N1 regression fix open (developer/integration-tester scope).

## s41: Signal safety and guard rules prevent self-kill

Investigation and fix for the SIGTERM that killed s29's develop step. The agent's own `ps aux | grep` matched its CLI (system prompt on argv), and `kill` ran on itself. Root cause fixed twice over: runner-side signal safety and guard-side process name rules.

**Architectural pattern: one module decides all signals**

No code outside `agile_team/process_groups.py` calls `os.killpg` (G1). New functions:
- `may_signal_child_group(pid)`: gate check for sendability (child's session leader, not runner's own group, not stale reused pid)
- `signal_child_group(pid, sig)`: send the signal; never compute pgid from `getpgid` (always use `pid` as-is)
- `Recorded(pid, written)`: pid file value + mtime; `is_ours()` checks both leads own session and started before file written (reused pid detection via process start time)

**Consequence:** Sandbox calls `signal_child_group`, commands calls it, `Prepared.stop` delegates to it. Stale and reused pids are automatically rejected. SIGKILL escalation re-checks safety (G5) to catch races.

**Architectural pattern: guard rules block common kill mistakes**

New module `agile_team/kill_check.py` (K1–K5):
- K1: `pkill`/`killall` denied (match by name; agent's argv holds whole prompt)
- K4: `kill <0, -1, runner_pid, same-group_pid>` denied; also deny run-time targets (`$(…)`, backticks, `xargs` fed)
- Pass: saved pids (`$PID`, `$!`, `%1`), new-session children, stale pids

**Consequence:** Guard hook runs last (after git, checkout, syntax checks); first denial wins. Role rule in `roles/_shared.md` (K5) names the fix: "Stop only what you started, by the pid you saved."

**Residual risk (documented):** Variable targets like `kill $PPID` cannot be parsed (PPID resolves at runtime in role Bash to agent CLI). Requires either rule change or follow-up story to deny specific variables.

Pattern: Two tight modules (process_groups, kill_check) + guard hook enforce safety in code. The rules are reinforced in prompts and docs but enforced by code, not trust. See ADR-0031, design `agile-team/docs/design/s41.md` (G1–G6, K1–K5).

## s43: Process group timeouts; hung test naming

A hung test in s29 showed that subprocess timeout didn't work: the runner killed the shell but then read from `communicate()` with no deadline, so child processes still holding the pipe would hang the runner indefinitely. Design fixes this with two architectural decisions.

**Process group isolation:** Each gate command runs in its own session (`start_new_session=True`), so its pgid is its pid. On timeout, the runner signals only that group with `SIGKILL` via `process_groups.signal_child_group()` (s41). This is safe: the guard prevents signaling the runner's own group, and processes that left the group themselves (`setsid`) are not chased. Consequence: hung tests do not hang the runner.

**Drain deadline:** After the kill, `communicate(timeout=5.0)` reads remaining output with a 5-second deadline. Python keeps what was read before the timeout, so nothing is lost. If an escaped process holds the pipe, the read times out and the runner continues (with empty string for that chunk). Consequence: even an escaped process does not hang the runner beyond 5 seconds.

**Hung test naming:** When a timeout fires, `hung_test(output)` tries patterns from `HUNG_PATTERNS` (faulthandler and traceback formats). The last match (latest stack dump) wins. If no test is named, a fallback message says so. The bounce reason ends with this message, so `gates.tail` keeps it. Consequence: developers see which test hung and can fix it without guessing.

**Guard enforcement:** Bash commands with `until` or `while` loops are denied unless a segment starts with `timeout` or `gtimeout`. The check runs on every view (shell and comment-aware), so the s29 accident (`until grep -q … ; do sleep 5; done` with no deadline) is caught before dispatch. Consequence: developers cannot accidentally leave bare waits in their commands.

**Configuration is explicit:** `[gates] command_timeout_s` (default 300.0) is human-owned in `.agile-team.toml`. Role edits are quarantined (cannot bypass). Timeout values are auditable in git history. Consequence: the limit is transparent and can be adjusted without code changes.

Pattern: Problem (hung test, no name, second hang) → architectural solution (process groups, naming, guard) → enforced in code, not prompt.

See ADR-0030, design `agile-team/docs/design/s43.md` (rules T1–T14).

## s62: Message delivery, watch polling, unsaved-state recovery, frozen resolution

Four architectural decisions working together to eliminate private scripts and enable self-hosting.

**Message delivery through router (T1–T6):** Messages queued via `tell` are not delivered via a separate alert; they join the inbox feed and become a `human_message` pass after checkout check (same flow as answers from s47). Consequence: delivery is atomic with the checkpoint system, no race between answer and message, message text never reaches the command line (safe from `pkill -f`).

**Watch as free polling (V1–V8):** File-based memory (`watch.json`) with poll state (outbox count + status baseline). `Seen` + `Look` dataclasses track what to fire on. `TRIGGERS` table (data-driven) defines when to report. Consequence: liaison gets status changes instantly (2s poll), outbox appends are caught, no tokens spent, memory survives resume.

**Unsaved state for dirty recovery (R1–R4):** When salvage is skipped (moved checkout in s61 K5), the cause is saved in `state.unsaved`. On resume via `recover_cut()`, if no INTERRUPTED status, check `unsaved` for the cause to salvage. Consequence: both killed runs (INTERRUPTED status) and checkout halts (moved checkout) recover cleanly from dirty trees without wrapper scripts.

**Frozen resolution for self-hosting (P1–P3, F1–F3):** Pin script builds a git archive at a commit (no symlink, no state sharing). Pinned runner uses `uv run --frozen`, which locks to the pinned `uv.lock` without re-resolution. Documented `uv` commands all use `--frozen`, so users' dotfiles never get `uv.lock` rewrites that halt shell loops. CI uses `--locked` to enforce version alignment. Consequence: unattended jobs stay stable even when the runner is being updated in the repo.

Each decision follows the team principle of "process in code, not scripts":
- Messages in files, not on command line.
- Watch state in JSON, not in a shell variable.
- Recovery via flagged state, not wrapper logic.
- Pinning via git archive, not manual scripts.

See ADR-0029, design `agile-team/docs/design/s62.md` (rules T1–T7, V1–V8, R1–R4, P1–P3, F1–F3).

## s61: Checkout guard prevents silent corruption

The runner now records the branch and commit it expects and halts immediately when either changes without the runner's own git operation. Key architectural patterns:

**Single-source-of-truth:** `state.checkout` (branch, head) is the only record. Written only by: (1) first passing check when unrecorded (K1), (2) `Runtime.record_checkout()` after every runner git write (settle_tree, save_interrupted, merge_in, recover_killed), (3) `accept-checkout` command (K7). No record → no check until first match (K6).

**Deterministic checks:** K2 predicates are pure: attached (via `symbolic-ref`), no operation in progress (paths in `.git/`), branch and head match record. K3: checked at start/resume, before/after every step, before gates, every router tick (including waits).

**Immediate halt:** K4–K5: Mismatch halts with kind `CHECKOUT` and status `checkout-changed`. `CheckoutChanged` exception in `run_role` before generic Exception (not crash.log). Salvage skips moved checkouts (K5).

**Clear escalation:** K8: reason names expected (branch or "unrecorded"), found (branch/detached + operation), and last HEAD move from reflog. K6: at start, post question only when no exact duplicate is open.

**Human control:** K7: `accept-checkout` refuses while runner is alive, detached, or operation in progress. Else: record, set status (if checkout-changed), log event, answer questions, exit 0.

Pattern: role Bash is read-only (s7), so any HEAD move is foreign. Budget advice (K10) routes through the acceptance flow. See ADR-0028, design `agile-team/docs/design/s61.md` (rules K1–K10, modules).

## s58: Network sandbox settings by delivery kind; e2e verified on macOS

Service deliveries (Start.BACKGROUND) get `network.allowLocalBinding: true` via data-driven mapping `NETWORK_BY_START`. Non-service kinds have no network key. Fresh dict per call prevents state pollution. E2E verification runs macOS only (Seatbelt); Linux (bubblewrap) not verified and documented as such. Service lifecycle pattern (s26) unchanged: trial starts and stops, Proxy gets fresh from `plan()`. Consequences: Proxy curl'ing local services no longer gets "connection refused"; sandbox settings are code-driven, not per-delivery magic strings. See ADR-0026, design `agile-team/docs/design/s58.md` (rules N1–N4, V1–V2, L1).

## s47: Waiting status is explicit; wake logic data-driven; halt notes include context

Two visibility rules: `status_reason` while waiting (W3) and halt-note suffix when halting with open questions (W5). Wake logic unchanged (W1); polling reads inbox first. Implementation: `Relay.waits()` lists one line per story an open question names (`"s40 waits on m42"`), then one for unnamed questions (`"the run waits on m43"`). `Relay.waiting()` joins with `WAITING_HEAD` prefix. `Router._show_wait()` sets reason, saves only on change. `_clear_wait()` and `_end_wait()` manage lifecycle (W4). `_deliver` calls `_clear_wait` first; `_step` calls `_end_wait` (avoiding double save). `halt_run` builds note with `_waits_suffix()` (W5). Stall lines unchanged; `_idle` never stalls while waiting (W6). Data-driven: `WAIT_LINE`, `RUN_WAIT_LINE`, `WAITING_HEAD` constants. See ADR-0025, design `agile-team/docs/design/s47.md` (W1–W6, modules).

## s46: Code already in passes tests gate; advance ruling

Code commits are recorded on every developer step and checked at the tests gate. When code is in the branch, the rework gate applies; no failing test needed. New `advance` ruling moves stories forward one step, clearing loops (A1–A3). Dispute output is captured and shown in briefs while open (D1–D3). Modules affected: `gates.py` (code_in, reworked, code_facts, dispute output), `roles.py` (advance ruling, ruling_reason field), `dispatch.py` (record commits, show output in brief, ruling event logs reason). Role files (`unit-tester.md`, `manager.md`) updated in follow-up s54. See ADR-0024, design `agile-team/docs/design/s46.md`.

## s45: Crash logging, fault rulings on any story, blocked release

Three architectural decisions: crash logging pipeline, fault ruling extension, and blocked-story release safety.

**Crash logging (C1–C4):** Single logging point in `Runtime.run_role` wraps `_run_step` in try/except. Every exception after refusal is logged to `crash.log` exactly once by `halt.log_traceback()`, then re-raised. Settle moves inside try in `_run_planned` (C2). Limits caught in `_step_failed`, logged there, converted to halted report (C3). Router and PO loop unchanged (C4). One entry per call; traceback included.

**Fault ruling extension (M1–M7):** Fault path taken when `handoff.fault` is named OR `story.repeated` is set (M1). Same refusal checks for both (M2). Applied fault clears state uniformly (M3). Reason read before clearing repeated (M4). Ruling conditional on fault (M5). Report structure identical to dispatch (M6). Wording for runner/off-pipeline/not-applied faults (M7).

**Blocked-story release (B1):** `continue_story` refused on blocked stories, regardless of hold. Reason tells PO to run Manager. Consequence: stories cannot silently stall when blocked by a runner fault or other escalation.

Pattern: Three problems (crash logging, fault scope, release safety) from one sprint's incident (s29 held). Each is now enforced in code (not prompt). See ADR-0023, design `agile-team/docs/design/s45.md` (rules C1–C4, M1–M7, B1–B2).

## s37: Unattended wake time and reason sources

Two consistency rules prevent stale wake times and lost reset deadlines in the unattended service:

**N1: Single place to clear wake state:** `JobState.mark(status, reason)` clears both `next_wake` and `wake_on` when setting a new status. Every status change (running, waiting, done, etc.) goes through `mark` and clears both fields. Timed waits (limit, rate-limit) then call `mark` and set both fields after, defining when the wait ends. Consequence: `_cycle` (resume) and `_finish` both clear stale wake fields automatically via `mark`.

**R1: Reason sources in priority order:** The supervisor tries to read a limit reason from four sources in order: (1) agile-team's halt line to stderr, (2) the status file agile-team writes atomically with the halt, (3) free text in the output with `RESET_NOTE` pattern (R2), (4) default reason. Each source is checked only if the earlier ones found nothing, so when the halt line is present (even if stdout is buffered after it), the PO's text is never read. This prevents "resets the count" from blocking a 9pm reset time.

**R2: Readable time required:** `RESET_NOTE` is built from a shared `RESET_CLOCK` fragment that requires `H[:MM]am|pm` (plus optional date and zone). Patterns like "resets soon" or "resets the count" no longer match, so a reason with no parseable time falls back to `wake_on: FALLBACK` (now + default wait) with explicit status indication, rather than silently guessing a 5-hour wait.

**N2: Offline wait state:** An offline wait (detecting network loss) calls `_mark_offline()`, which marks the job WAITING (clearing wake state via N1) then sets `wake_on = NETWORK`. The human sees `next_wake: null` and `wake_on: "network"`, making it clear the job is waiting for network, not a time. When the network returns and `_cycle` marks RUNNING again, both wake fields clear, ensuring no stale time leaks into the next wait.

Architectural patterns: wake state metadata (`WakeOn` enum, `Wake` dataclass) makes decisions explicit and auditable. Reason sources (data-driven table) apply the priority rule everywhere without branching. Both changes follow the team's principles of data-driven code and single-source-of-truth (ADRs 0007, 0009).

See ADR-0020, design `agile-team/docs/design/s37.md` (rules N1–N2, R1–R3, S1, L1).

## s38: Corrected budget numbers and the ceiling is a hard stop

The budget is no longer a soft target; it is now a hard ceiling that halts the run. Ledger entries are corrected on read, so all consumers see the same true spend. Key architectural patterns:

- **Correction on read (K1, K4):** One function `ledger.corrected()` walks PO entries written before s25 and turns running totals into own costs using `SessionCost`. All readers go through it: `Ledger.entries()`, snapshot builder, `budget_status`. The ledger file stays append-only and never rewritten.
- **Ceiling is code-driven (B1–B3):** `Runtime.enforce_ceiling()` calls `halt.budget_halt()` and checks corrected spend rounded to 4 decimals. Called consistently at 3 points: after role steps land, after PO ledgers, at run start. First halt wins; later calls re-assert the same halt (one liaison note).
- **Legacy boundary (K2):** `PO_DELTAS_FROM = 1791694950.0` (2026-10-11 05:02:30 UTC) between lines 310 and 312 of the ledger. Any PO entry before this timestamp is legacy (pre-s25 code). No guessing; the boundary is a wall-clock time.
- **Halt is normal (B3):** `HaltKind.BUDGET` (new; adds to `salvage.Cause`). Exit code 77 (`EX_NOPERM`): budget stop needs human permission. Preflight clean-tree unchanged. Human edits `.agile-team.toml`, commits, resumes. Config reloads; no restart needed.

Rules K1–K6, B1–B9, M1 in design; ADR-007 for decision rationale and options considered.

## s30: Content-based dispute resolution and manual escalation

The dispute mechanism (s11) is now fully functional. Baseline is the file's content hash (not a commit), stored at raise time, compared at the gate. Path resolution happens at raise; unresolvable files are rejected. Repeat bounces escalate to the Manager via s27 logic. New `pass_tests()` tool lets the PO move stuck stories when suite is green (no manual state edits). Design rules F1–F12 in `agile-team/docs/design/s30.md` govern path resolution, fingerprinting (whitespace/comment normalization), raise/gate/repeat/legacy logic, and tool implementation. See ADR-0019.

## s9: Save interrupted steps in commits, not stashes

When a step is cut short (error, limit, SIGTERM, kill -9), the runner now saves its edits in a commit and reverts it (not in a stash). The design decision (ADR-0017) covers the full rationale and flow; key architectural points:

- **Commit + revert, not stash:** Edits stay reachable by sha forever; roles can reuse them with `git cherry-pick -n` (which they already know).
- **State tracks in-flight steps:** `state.in_flight` records the role, story, and brief of a running step. On settlement, it clears. On crash, it tells the human what was cut short.
- **Status shows liveness:** `shown_status()` returns `INTERRUPTED` when state says `RUNNING` but the pid is dead. Stale pids are harmless and ignored.
- **Recovery on resume:** `start --resume` detects a dead pid and saves the edits (cause `killed`), then the resume prompt is the same as after any halt.
- **Next brief offers the sha:** Until the step on a story settles, the brief includes `Interrupted work:` with the exact cherry-pick command. Settlement clears it.

**Note:** AC6 (documentation update) is flagged as not checked. `reference/protocol.md` and `agile-team/SKILL.md` should document the new resume and status behaviour; `roles/product-owner.md` (built-in) is updated with the Interrupted steps section.

See ADR-0017 for the decision; `agile-team/docs/design/s9.md` for rules I1–I15, modules, test checklist, exact strings.

## s40: Story priority is explicit and code-driven

The order in which stories are worked is now an explicit list the PO sets, the router follows, and the board shows. This replaces creation order as the priority mechanism.

Key architectural choices:
- **`state.order`:** A list of story ids (unfinished stories, in priority order) persisted in state.json. Legacy files load with `[]`.
- **Single ranking rule:** `Priority.key()` = `(done, listed, not in_progress, natural(id))` breaks all ties deterministically. Explicit position beats in-progress; in-progress breaks ties among unlisted stories.
- **PO tools are explicit:** `prioritise()`, `move_story()`, and `start_sprint()`'s list order set the queue. Refusals are clear (unknown, done, empty, bad position). Every change emits a `priority` event (logged and visible on timeline).
- **Hold keeps position:** A held story is skipped by the router but keeps its position number. Once released, it runs from that position.
- **Wait system is data-driven:** `WAITS` table (exact order matters) determines why a story can't move. The board marks each with `⏸ <reason>` and `waits on:` details.
- **Snapshot carries priority:** `run.order` = queue, stories in ranking order, each story has `position`, `in_progress`, `hold`, `wait` fields.

This completes the move from implicit ordering (creation order, prose agreements) to explicit, auditable, code-driven priority. See ADR-0016, design `agile-team/docs/design/s40.md` (rules P1–P10, W1–W2, D1–D5).

## s11: Rule on confirmed test disputes

When a story lands at `design` with `story.dispute` set and `dispute.stage = confirmed`, the tester has verified the test is correct (not a mistake). Your role: either the rule stands (test must change to match design) or the rule changes (design must be updated).

Hand off `done` either way. The dispute clears and the story returns to `tests` (dispute cleared, no further round). Brief line (T9): `Test dispute (confirmed): {test} contradicts {rule}: {reason}`. See ADR-0018, design `agile-team/docs/design/s11.md` (T8, AC3).

## s29: Sync and stacked PR delivery

Sprint boundaries are now runner code: at start, the runner syncs by merging upstream main into the team branch (never rebasing it); at end, it rebuilds review branches in a scratch worktree by cherry-picking each sprint onto the latest main, verifies they work, and pushes them as a stacked PR per sprint. Only the bottom PR is ready for review (others are drafts); CI skips drafts. Permission to push is asked once. Conflict resolutions are recorded with git rerere and replayed.

Key architectural choices:
- **Team branch immutable:** Hashes recorded in state stay valid forever; only merges touch it.
- **Review branches derived:** Cherry-picked fresh each time in a worktree; fixes land on the team branch, not the review branch.
- **Boundary is code:** Sync, check, review, push are runner steps the PO can hold or continue; the router picks them before sprint stories.
- **Escalation applies:** Same failure at a boundary repeats and goes to the Manager (via s27 logic).
- **Narrow interfaces:** `Upstream` (git), `Prs` (gh), both testable with fakes; the runner works without a remote.

See ADR-0015, design `agile-team/docs/design/s29.md` (rules U1–U27, modules).

## Context reduction — focused design files (s23)

Move designs out of the 1600-line `architecture.md` into focused per-story files (`docs/design/<id>.md`). Each design should name:
- Rules and constraints (the contract)
- Changes per module with exact signatures and import paths
- A test checklist (so Unit Tester knows what to verify)

This lets Unit Testers and Developers read only what they need. Expect Unit Tester context per turn to drop under 60k tokens (s19 was 113.9k). See ADR-0011.

## Key design decisions

**Escalate repeated setbacks to the Manager (s27):** Stories that bounce or hold for the same reason (normalised) now escalate to the Manager instead of looping. A backstop rule also catches back-and-forth between the same two steps (regardless of reason). The runner detects this via `Pipeline.screen()` before advancing. The Manager rules on the fault, which clears the bounce history and resets counters. Three new hand-over rows (`runner_fault`, `off_pipeline_fault`, `fault_not_applied`) surface fault decisions to the PO. Normalisation is data (`NORMALISE` table), so adding a pattern requires one row. Rules L1–L18 and B1–B9 in `agile-team/docs/design/s27.md` govern the implementation. ADR-0014.

**Liveness is data; absolute paths; service lifecycle (s26):** Service deliveries are tested before the Proxy runs. The runner starts, probes, and stops them from the presentation (same sandbox the Proxy gets), so a gate pass guarantees readiness. Stale services are cleaned up with SIGTERM+SIGKILL escalation; all paths call `prepared.stop()`. Paths are absolute (no cwd dependency). Liveness check, probe attempt count, and port are data (Check enum, Recipe, PRESENTATIONS table). Returns are possible without billing when the Proxy's prepare fails. Port conflicts hold (no round, hand-over to PO). Presentations must be self-contained (no repo paths). Design: `agile-team/docs/design/s26.md` (rules L1–L13). ADR-0013.

**Ledger each PO query's own cost (s25):** The PO resumes one session, and `total_cost_usd` is a session running total. The ledger now records deltas: `own = reported − previous` for resumed sessions, full amount for fresh sessions. `SessionCost(session, reported)` and `SessionCost.own_cost()` compute the delta; `RunState.po_cost` persists it. Rules C1–C9 in `agile-team/docs/design/s25.md` govern the implementation; C6 handles legacy seeds. ADR-004 documents the finding, decision, and one-off correction ($256.93 for old entries).

**Routing in code — runner drives the pipeline (s19):** The fixed pipeline (design → implement → review → acceptance) is now code-driven. The architect names each story's developer specialisation via a `"developer"` field in the handoff (e.g., `"developer": "developer-cli"`); the runner uses it for implement steps. ADR-0009 and `agile-team/docs/design/s19.md` document the architecture.

**Team presents product in ready-made environment (s13):** The runner enforces the handoff in three layers:
1. **Presentation structure** (E1–E2): `.team/run/presentation/<story>/` with `PRESENTATION.md`, `workspace/`, and optional files. Runner wipes and creates workspace before Integration Tester step.
2. **e2e gate** (E4–E5): checks completeness (guide non-blank, workspace non-empty) before acceptance. Incomplete → bounce to e2e with round +1.
3. **Proxy precondition** (E6): missing presentation → return to e2e with `Verdict.RETURN` (no round, no cost). Copy presentation to sandbox (E7) before prepare. Proxy gets Proxy prompt section (E8) with absolute path and guide quoted in full. Proxy can read/write own report (E9). Init outside git prints error and exits 1 (E11).

Five related changes:
- `presentation.py`: single definitions for lay_out, missing, copy_into, prompt_section
- `gates.py`: `Verdict.RETURN` + e2e done gate checks presentation
- `dispatch.py`: per-role setup (tester lays out, proxy receives copy), Proxy precondition returns on missing
- `sandbox.py`: `Order` holds presentation source, `Preparer` copies before launching, Proxy read scope includes `.team/acceptance/**`
- `cli.py`, `git_ops.py`: init error handling (no traceback)

Impact: s4, s5, s8 (legacy, at acceptance) return to e2e on missing presentation (no round), tester builds presentation, gate passes, Proxy accepts. Same pattern scales to harness, manual, library, web kinds. ADR-0008 documents the strategy.

**Clean halt on limits, crashes, SIGTERM (s8):** Data-driven halt handling via `HALTS` table (kind → status, note_kind, exit_code, advice) and `LIMIT_PATTERNS` table (regex, template). `classify()` returns the detected halt; first halt wins in a process. Partial edits left uncommitted so human can see what was in progress. Exit codes: 75 (EX_TEMPFAIL limit), 70 (EX_SOFTWARE crash), 143 (SIGTERM). s9 will save interrupted step edits as a commit; s10 will record partial cost. ADR-0007 documents the strategy.

**Dashboard backend: snapshot as raw data contract (s4):** The snapshot builder (`snapshot.py`) returns raw, unaggregated data directly from run files. The UI (`index.html`) derives all views (board, flow, tokens, questions) in the browser from this raw data. The fixture (`snapshot.json`) is the API contract, not the views named in AC1/AC2.

Key architectural choices:
- **Pure snapshot building:** `build(config, book)` reads only explicit files (state, ledger, events, outbox, inbox, stories, requirements). No writes, no git, no network. Consequence: snapshot is stateless and always fresh.
- **No Python aggregation:** Board columns, token totals, requirement coverage are computed in JavaScript. Consequence: server is simple; UI can evolve without server changes.
- **Exact routes:** Three literal paths (`/`, `/api/snapshot`, `/api/stream`). No file paths built from requests. Consequence: no directory traversal risk.
- **SSE file watching:** Server polls file fingerprints (mtimes, sizes) every 1 second; sends snapshots on change, keepalives otherwise. Consequence: clients stay live without polling.
- **Stdlib only:** Uses `ThreadingHTTPServer` and `webbrowser` from the stdlib. No new runtime dependencies.

This separates concerns cleanly: the runner focuses on reading files correctly and building a canonical snapshot; the UI focuses on presenting that data. See ADR-0027, design `agile-team/docs/architecture.md` § "s4: Dashboard backend" (rules S1–S7).

**Dashboard live UI (s5):** Vanilla JS with EventSource for live updates, Mermaid 11.4.1 flowchart from CDN (lazy-loaded), CSS tokens for themes, defensive rendering with per-row error handling. Five ADRs (0002–0006) document the choices. This completes the frontend half of the dashboard; s4 provides the backend (snapshot, SSE server, CLI). Known gaps: no executable test for animated features (verified by hand in headless Chrome); follow-up story recommended.

**Backlog and sprint membership (s3):** Stories default to the backlog and move to sprints via `start_sprint(goal, stories)`. This enforces the gate: backlog stories cannot proceed past their opener step. Legacy state.json files load with stories in the backlog automatically.

**Nested forbidden roots for Proxy (s7):** The sandbox computes the deepest literal path segment before wildcards (e.g., `agile-team/runner/agile_team/**` → `agile-team/runner/agile_team`, not just `agile-team`). This allows customer docs in `agile-team/docs/customer/` to coexist with source at `agile-team/runner/agile_team/`.

**Deny on any view (s7):** Proxy Bash checks run in two views (shell continuations and comment-aware). Over-deny is the strategy: a denial in any view blocks the command. This prevents false negatives at the cost of rare false positives (quoted comments).

## What you own

Review whether step sequences, gate checks, role boundaries and scope handoffs remain sound. The Unit Tester and Integration Tester are critical checkpoints; ensure they have clear design context in handoffs.

s13 introduces the presentation mechanism as a new entrypoint between the Integration Tester and Proxy; verify the boundary is clean (runner wipes and creates, tester builds, gate checks, proxy copies and uses). Ensure the `Verdict.RETURN` verdict does not escape its design scope (e2e → acceptance return only, no round counted).
