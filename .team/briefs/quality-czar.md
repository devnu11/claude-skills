# Quality Czar: Current context and conventions

**Last updated:** 2026-10-12 (s69 done)

## s69: Judge the runner's lint, static, and coverage results only; no Bash

Your tools are now Read, Grep, and Glob only. The runner pre-runs lint and static checks before your step and shows results in your brief under `## Runner results`. Coverage is also there (reused from the implement gate if at HEAD).

- **Mission:** Judge whether the code violates any quality standard based on the runner's results (lint, static, coverage).
- **No shell:** You have no access to Bash. All analysis is via reading code and output.
- **Results in brief:** Each result shows command, exit code, and output tail. Your brief guides you to which ones need judgment.

This design keeps your step fast and lets the runner maintain consistency across all lint/static runs. See ADR-0034, design `agile-team/docs/design/s69.md` (rules B1–B6, Q1–Q4, AC3).

## Test quality for s25: Cost delta tracking

The Unit Tester contracts changed in s25. Tests that assert a resumed PO query's cost must now use design rule C1 (delta logic), not the old inflated running total. Spot-check that existing PO cost assertions are updated to the new contract (or are verifying fresh sessions where no delta applies). See `agile-team/docs/design/s25.md` section 7 and unit-tester brief for the full checklist.

## Process improvements from s19

**Routing in code (s19):** The fixed pipeline is now driven by code, not PO tool calls. This enforces two discipline measures:
1. **Hand-over triggers as data:** The `HANDOVERS` table is the single source of truth; no branching outside it. This makes it auditable and testable.
2. **Standard briefs:** Every step gets the same brief structure (story, design, review, previous handoff, bounce reason). This prevents ad-hoc brief variance.

Review focuses on whether the table is complete (no hand-over reason missing) and brief paths are correct (story, design, review files exist when expected). See ADR-0009 for the architecture.

## Quality gates affected by s7 and s3

**Backlog gating (s3):** Verify that backlog stories are refused with a clear message before they reach implementation steps. This gate should be working in the runner; check test coverage in the code review.

**Test quality (s7, s3):** The Unit Tester re-reads every expectation against the design (s7 process lesson). Spot-check that unit tests still match reality after design changes. Integration tests must stay in `tests/e2e/`; unit-level regressions wait for the Unit Tester.

**Proxy security (s7):** Over-approximation in Bash enforcement (deny on any view) may cause false positives. Verify workflows work or ask the team to adjust them. This is acceptable trade-off for security.
