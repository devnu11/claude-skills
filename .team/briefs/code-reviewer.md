# Code Reviewer: Current context and conventions

**Last updated:** 2026-10-11 (s29 done)

## Design decisions to verify

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
