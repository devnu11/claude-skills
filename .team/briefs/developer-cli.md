# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-10 (s24 done)

See `developer.md` for the base conventions.

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
