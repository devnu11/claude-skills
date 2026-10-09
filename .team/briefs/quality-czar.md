# Quality Czar: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## Quality gates affected by s7 and s3

**Backlog gating (s3):** Verify that backlog stories are refused with a clear message before they reach implementation steps. This gate should be working in the runner; check test coverage in the code review.

**Test quality (s7, s3):** The Unit Tester re-reads every expectation against the design (s7 process lesson). Spot-check that unit tests still match reality after design changes. Integration tests must stay in `tests/e2e/`; unit-level regressions wait for the Unit Tester.

**Proxy security (s7):** Over-approximation in Bash enforcement (deny on any view) may cause false positives. Verify workflows work or ask the team to adjust them. This is acceptable trade-off for security.
