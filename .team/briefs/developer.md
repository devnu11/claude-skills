# Developer: Current context and conventions

**Last updated:** 2026-10-10 (s19 done)

## s19: Runner calls you automatically with a standard brief

The runner now automatically calls each developer step with a standard brief that includes story, design, review, previous handoff (if returning), and bounce reason (if bounced). You will not see the PO except in rare cases where a step hands over (open questions, blocked, round cap). The architect names your specialisation (e.g., `developer-cli`, `developer-gui`) in a `"developer"` field; the PO can override it per story with `set_developer`.

See ADR-0009 for the routing architecture.

## Process: you cannot edit tests

You cannot write to `tests/unit/` or `tests/conftest.py`. The Unit Tester will add or modify unit tests. If a test fails, the runner will not route it back to you; instead, the Unit Tester reviews the mismatch.

When you have questions about test expectations, ask during design reviews or handoff comments; the Unit Tester will clarify.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. You cannot start implementation on a backlog story; only sprint stories can proceed. On resume, check the current sprint before your first step.

## Design decisions affecting your work

- **Nested forbidden roots (s7):** The Customer Proxy can reach customer docs even when they share a parent directory with source. Keep docs clean and separate concerns clearly.
- **Deny on any view (s7):** The Proxy's Bash enforcement is conservative (denies on any plausible interpretation). Design customer workflows to avoid quoted comments or ambiguous constructs.
