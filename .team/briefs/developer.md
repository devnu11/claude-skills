# Developer: Current context and conventions

**Last updated:** 2026-10-13 (s92 done)

## s92 complete: Gate failures in foreign files route to their owners, no round

When the implement gate fails (coverage, lint, or static), the runner routes items by file ownership. Items you own stay with you and bounce as usual. Items in files you can't edit (e2e tests, lint in tests/, design files) route to the owner role without counting a round or opening a dispute. The story returns to you after all fix steps complete. **Your brief will show:** "Other roles fix items in their files first, then this step runs again."

If a gate fails only in files you can't edit, hand off `done` and the runner sends them onward. Do not block, do not dispute.

## Process: you cannot edit tests

You cannot write to `tests/unit/` or `tests/conftest.py`. The Unit Tester will add or modify unit tests. If a test fails, the runner will not route it back to you; instead, the Unit Tester reviews the mismatch.

When you have questions about test expectations, ask during design reviews or handoff comments; the Unit Tester will clarify.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. You cannot start implementation on a backlog story; only sprint stories can proceed. On resume, check the current sprint before your first step.

## Design decisions

- **Git confinement (s65):** Your steps have no git ceiling. **Nested roots (s7):** Docs and source may share a parent; keep them separate.
- **Deny on any view (s7):** The Proxy's Bash enforcement is conservative. Design workflows to avoid quoted comments or ambiguous constructs.
