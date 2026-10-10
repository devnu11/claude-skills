# Architect: Current context and conventions

**Last updated:** 2026-10-10 (s13 done)

## Key design decisions

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
