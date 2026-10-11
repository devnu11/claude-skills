# Architect: Current context and conventions

**Last updated:** 2026-10-10 (s26 done)

## Context reduction — focused design files (s23)

Move designs out of the 1600-line `architecture.md` into focused per-story files (`docs/design/<id>.md`). Each design should name:
- Rules and constraints (the contract)
- Changes per module with exact signatures and import paths
- A test checklist (so Unit Tester knows what to verify)

This lets Unit Testers and Developers read only what they need. Expect Unit Tester context per turn to drop under 60k tokens (s19 was 113.9k). See ADR-0011.

## Key design decisions

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

**Dashboard live UI (s5):** Vanilla JS with EventSource for live updates, Mermaid 11.4.1 flowchart from CDN (lazy-loaded), CSS tokens for themes, defensive rendering with per-row error handling. Five ADRs (0002–0006) document the choices. This completes the frontend half of the dashboard; s4 provides the backend (snapshot, SSE server, CLI). Known gaps: no executable test for animated features (verified by hand in headless Chrome); follow-up story recommended.

**Backlog and sprint membership (s3):** Stories default to the backlog and move to sprints via `start_sprint(goal, stories)`. This enforces the gate: backlog stories cannot proceed past their opener step. Legacy state.json files load with stories in the backlog automatically.

**Nested forbidden roots for Proxy (s7):** The sandbox computes the deepest literal path segment before wildcards (e.g., `agile-team/runner/agile_team/**` → `agile-team/runner/agile_team`, not just `agile-team`). This allows customer docs in `agile-team/docs/customer/` to coexist with source at `agile-team/runner/agile_team/`.

**Deny on any view (s7):** Proxy Bash checks run in two views (shell continuations and comment-aware). Over-deny is the strategy: a denial in any view blocks the command. This prevents false negatives at the cost of rare false positives (quoted comments).

## What you own

Review whether step sequences, gate checks, role boundaries and scope handoffs remain sound. The Unit Tester and Integration Tester are critical checkpoints; ensure they have clear design context in handoffs.

s13 introduces the presentation mechanism as a new entrypoint between the Integration Tester and Proxy; verify the boundary is clean (runner wipes and creates, tester builds, gate checks, proxy copies and uses). Ensure the `Verdict.RETURN` verdict does not escape its design scope (e2e → acceptance return only, no round counted).
