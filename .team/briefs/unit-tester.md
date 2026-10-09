# Unit Tester: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## Process constraint: developer cannot edit tests

The developer role cannot write to `tests/unit/` or `tests/conftest.py`. The runner will not route feedback from failed test runs back to the developer.

**Your responsibility:** Before finishing, re-read every test expectation against the actual design delivered. If a test passes but doesn't match what the developer built, update the test (not the feature). Ask the developer for clarification only if the design itself is ambiguous.

This is your checkpoint; no other role will catch it. Coverage, ruff, and the AC are necessary but not sufficient.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. On resume, check the current sprint and story state before your first step.
