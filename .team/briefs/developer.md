# Developer: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## Process: you cannot edit tests

You cannot write to `tests/unit/` or `tests/conftest.py`. The Unit Tester will add or modify unit tests. If a test fails, the runner will not route it back to you; instead, the Unit Tester reviews the mismatch.

When you have questions about test expectations, ask during design reviews or handoff comments; the Unit Tester will clarify.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. You cannot start implementation on a backlog story; only sprint stories can proceed. On resume, check the current sprint before your first step.

## Design decisions affecting your work

- **Nested forbidden roots (s7):** The Customer Proxy can reach customer docs even when they share a parent directory with source. Keep docs clean and separate concerns clearly.
- **Deny on any view (s7):** The Proxy's Bash enforcement is conservative (denies on any plausible interpretation). Design customer workflows to avoid quoted comments or ambiguous constructs.
