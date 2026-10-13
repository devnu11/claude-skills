# Architect: Current context and conventions

**Last updated:** 2026-10-12 (s81 done)

## s81: CI stage at boundary; verdict rules data-driven (ADR-0040, extends s29)

New CI stage runs after the boundary pushes. Waits for `gh pr checks --watch` under `ci_timeout_s` deadline (default 1800s). Verdict is green only when every watched PR is green. Red or timeout holds the boundary until a bug story is recorded.

**Architectural decisions:**
1. **One new stage in pipeline:** `STAGES = (SYNC, CHECK, REVIEW, PUSH, CI)`. Runs after PUSH on every boundary that pushed, and at start only when restacking.
2. **Data-driven verdicts:** `Bucket` enum, `BUCKET_VERDICT` table (fail/cancel→red, pass→green, pending→pending), `CHECK_ORDER` = (red, pending, green), `PR_ORDER` = (red, pending, none, green). No branching on verdict type.
3. **Failing lines extracted:** Job id from link, log via `gh run view --job <id> --log-failed`. Match pytest/go patterns, max 20 lines, fallback last 10 non-blank.
4. **Only green marks ready:** Phrase "ready to merge" appears only in `ci_green` hand-over line and green report. Never from red, pending, none, local, or pushed reports.
5. **Hold until bug story recorded:** `record_ci_bug(tool)` writes `upstream.ci_bug`, closes the boundary with "checks failed, story sN opened". Bug story must be first in next sprint.
6. **No new dependency:** `gh` stays behind `Prs` interface. Unit tests fake it via `system.run` seam.

**Modules:** New `ci.py` (CiWatch class, verdict rules, text builders). Changed: `boundary.py` (stage, holds, state fields), `boundary_runner.py` (outcome methods), `upstream.py` (Prs protocol), `po_tools.py` (record_ci_bug tool), `config.py` (ci_timeout_s), `state.py` (loaders), `handover.py` (ci_green/ci_failed/ci_pending rules).

See ADR-0040, design `agile-team/docs/design/s81.md` (rules CI1–CI16).

## Seam completion (s77, no new ADR)

P3 closes s71 architecture. Six new `system.py` names: `home`, `which`, `on_signal`, `open_browser`, `async_sleep`, `HttpServer`. All 31 pre-P1 LEGACY tests migrated to fake or e2e. Ruff TID251 enforces `from agile_team import system` import discipline across all code.

**Consequence:** Seam is complete. Every OS interaction auditable and testable. All code follows one pattern. No branching on test type (world enum decides timeout). See ADR-0036 (s71 architecture).

## Key design principles (your domain)

- **Process in code, not prompt:** Gate rules, hold clearing, verdict logic, bounds are data tables or code functions, never prose agreements.
- **Data-driven over branching:** Tables (BUCKET_VERDICT, PR_ORDER, HALTS, WAITS, NORMALISE) let new cases be added without conditionals.
- **Single source of truth:** Snapshot carries raw data; browser derives views. Heartbeat carries both clocks; reader detects sleep. State.checkout is only branch record; check runs everywhere.
- **Blocking is safe:** CI stage blocks router up to 30 min; health stays green via `pulse.doing()`. Resume works (push saved before CI, resume reruns wait).

See ADRs 0007, 0009, 0013, 0015, 0027, 0040 for decisions on design patterns.

## Your focus (unchanged)

Review step sequences, gate checks, role boundaries. Ensure snapshot contract, state transitions, and error paths. Verify integration at role boundaries (tester → proxy, git ops seam, HTTP seam).
