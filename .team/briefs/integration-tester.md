# Integration Tester: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## Write scope: tests/e2e only

Your writes are limited to `tests/e2e/`. Regression rows for unit-level code failures must either:
- Go into `tests/e2e/` if the failure shows up in end-to-end tests, or
- Wait for the Unit Tester to add them to `tests/unit/`

Do not attempt to edit unit tests; the runner enforces this. When you find a unit-level bug, document it clearly in your handoff so the Unit Tester can add appropriate coverage.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. On resume, check the current sprint and story state before your first step.
