# Architect: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## Key design decisions

**Backlog and sprint membership (s3):** Stories default to the backlog and move to sprints via `start_sprint(goal, stories)`. This enforces the gate: backlog stories cannot proceed past their opener step. Legacy state.json files load with stories in the backlog automatically.

**Nested forbidden roots for Proxy (s7):** The sandbox computes the deepest literal path segment before wildcards (e.g., `agile-team/runner/agile_team/**` → `agile-team/runner/agile_team`, not just `agile-team`). This allows customer docs in `agile-team/docs/customer/` to coexist with source at `agile-team/runner/agile_team/`.

**Deny on any view (s7):** Proxy Bash checks run in two views (shell continuations and comment-aware). Over-deny is the strategy: a denial in any view blocks the command. This prevents false negatives at the cost of rare false positives (quoted comments).

## What you own

Review whether step sequences, gate checks, and role boundaries remain sound. The Unit Tester and Integration Tester are critical checkpoints; ensure they have clear design context in handoffs.
