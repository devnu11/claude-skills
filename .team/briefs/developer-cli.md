# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-11 (s11 done)

See `developer.md` for the base conventions.

## s9: Recover from an interrupted step—keep its edits

When a role step is cut short by an error, limit, SIGTERM, or kill signal, the runner now saves its edits in a commit and reverts it. On resume, the edits are offered to the next step on that story. Key modules:

- **`salvage.py` (new):** `Cause` (enum), `InFlight` and `Interruption` dataclasses, `save_tree`, `capture`, `offer`, `resume_section` functions, `label` and note templates.
- **`recovery.py` (new):** `Salvager` class with `save` method, `recover_killed` for resuming after a kill -9.
- **`state.py`:** `RunStatus.INTERRUPTED`, `in_flight: InFlight | None`, `interrupted: list[Interruption]`, `runner_pid()`, `pid_alive()`, `runner_alive()`, `shown_status()` functions.
- **`dispatch.py`:** `_take_off`, `_land` (track in-flight), `save_interrupted()` (public), `halt_note`, `_interrupted_lines`, `_story_lines` updated.
- **`po_tools.py`:** `_opening` takes interrupted steps first, `_take_interrupted`, `_joined` helpers.
- **`cli.py`:** `_recover` on `start --resume`, `status_report` includes `in_flight` and `interrupted`.
- **`dashboard/snapshot.py`, `index.html`:** `shown_status` in snapshot, `STATUS_TONE` for `interrupted` status.
- **`roles/product-owner.md` (built-in):** Documents the Interrupted steps section and cherry-pick guidance.

See ADR-0017, design `agile-team/docs/design/s9.md` (rules I1–I15, modules, test checklist).

**Note:** The e2e test `test_halted_role_step_leaves_tree_untouched` needs to be updated: s8's H15 (tree unchanged after halt) is superseded by I5 (tree clean, HEAD moved by two commits, edits in sha).

## s40: Story priority lives in code

The router now follows an explicit, ordered list of stories instead of creation order. Key modules:

- **`priority.py` (new):** `Priority` class with `key()` ranking rule: `(done, listed, not in_progress, natural(id))`. `natural()` for digit-aware sorting. `ranked()` and `queue()` builders. `order_refusal()`, `move_refusal()`, `with_first()`, `with_move()` helpers for validation and reordering.
- **`waits.py` (new):** `Wait` dataclass, `WaitReason` enum, `WAITS` table (data-driven). `wait()` function computes why a story can't move from hold, status, questions, and previous step.
- **`state.py`:** `RunState.order: list[str]` field (default `[]`). Legacy load with missing key takes default.
- **`dispatch.py`:** `Runtime.priority() -> Priority` returns the ranking for this run.
- **`router.py`:** `_story_work` and `_repeat_work` use `priority().ranked()` to pick stories by order, not creation order.
- **`po_tools.py`:** New tools `prioritise(stories, reason)` and `move_story(story, position, reason)`. `_begin_sprint` applies priority to sprint stories. `story_status` returns stories in ranking order with `order` key. `_reorder()` helper emits `priority` events. Exact tool descriptions in `SCHEMAS`.
- **`events.py`:** `EventKind.PRIORITY = "priority"`. Event data: change (set/move/sprint), order, moves (from→to), reason.
- **`dashboard/snapshot.py`:** `_priority()` builder, `_run` adds order, `_stories` uses ranking, `_story` adds position, in_progress, hold, wait fields.
- **`dashboard/index.html`:** `#${s.position}` in story id line. `WAIT_TONE` for hold colors. `priorityLabel()` formats timeline labels. Board never re-sorts (snapshot order is authoritative).
- **`roles/product-owner.md`:** Documents the new tools and how the router follows priority.

See ADR-0016, design `agile-team/docs/design/s40.md` (rules P1–P10, W1–W2, D1–D5, X1, test checklist).

## s29: Sync with upstream, verify review branches, and deliver stacked PRs

Sprint boundaries are now runner steps (boundary.py, boundary_runner.py, stack.py, fullcheck.py, upstream.py) that sync with upstream at start, rebuild and verify review branches at end, and manage stacked PRs. Key modules:

- **upstream.py:** Merges upstream main into the team branch (start), pushes review branches and manages the PR stack. Narrow interface: `Git.options`, `Git.attempt`, `Git.branch()`, `Upstream` (merge_in, target, push), `Prs` protocol (find, create, edit), `GhPrs` and `NoPrs` implementations.
- **stack.py:** Rebuilds review branches from scratch in a worktree (`.team/run/review`) by cherry-picking each sprint's commits onto the latest main, detects conflicts, records resolutions with `git rerere`.
- **fullcheck.py:** Runs full checks in order: lint, static, test, coverage, then e2e per delivery. Every check runs; none is skipped after a failure.
- **boundary.py:** Data and strings for boundary stages (sync, check, review, push), holds, failures, fixes, permissions.
- **boundary_runner.py:** Orchestrates the four stages, runs after_fix on DevOps reports, escalates repeats (s27).
- **config.py:** `UpstreamSettings(remote, branch, prefix)`, `Delivery.e2e`.
- **state.py:** Boundary, UpstreamState, StackEntry for persisting state.
- **dispatch.py, router.py, handover.py:** Boundary routing, refusals, escalation, hand-overs, permission asking.

See ADR-0015, design `agile-team/docs/design/s29.md` (rules U1–U27, modules, test checklist).

## s24: Rework gate and hold clearing

Stories coming back to `tests` after a ruling with code already in place now pass without bouncing. Key changes:

- **`StoryState.implemented: int`** (G1): incremented at each `implement` gate pass, never reset. Legacy load: 1 past implement, 0 otherwise (G2).
- **`Handoff.tests: "changed" | "confirmed" | None`** (G3): unit-tester claims either value; any other is malformed (`handoff tests must be one of ('changed', 'confirmed')`).
- **Rework gate** (G4–G7): At `tests` with `implemented > 0`, no dispute, `done` handoff: red suite → pass; green + claim → pass with reason; green no claim → bounce `REWORK_UNCLAIMED`. First-pass (`implemented == 0`) still uses `tests_red`. Dispute (s11 T6) always wins. Brief includes `REWORK_BRIEF` when rework conditions apply.
- **`Pipeline._forward`** (G1): increment `implemented` when passing `implement` before moving.
- **`continue_story`** (G8): no longer refuses done stories; clears their hold.

See ADR-0012 for decisions. Design: `agile-team/docs/design/s24.md` (rules G1–G9, modules, test checklist).

## Cost delta tracking — PO sessions and ledger entries (s25)

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
