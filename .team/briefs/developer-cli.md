# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-11 (s47 done)

See `developer.md` for the base conventions.

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
