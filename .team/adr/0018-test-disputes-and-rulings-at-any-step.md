# ADR-0018: Test disputes and rulings at any step

**Date:** 2026-10-11  
**Status:** Accepted  
**Deciders:** Developer (s11 implement), Customer-proxy (s11 tests & review), Product-owner (Scribe)

## Context

In s7 and s4, developers found tests that contradicted the design but could not fix them:
- Developers cannot edit tests (scope/quarantine).
- A `changes_requested` handoff from `implement` bounced back to `implement`, costing a round.
- The Manager's `revise_design` ruling worked only at round cap, not mid-story.

Both cases required manual intervention (m6).

## Decision

1. **Test disputes:** A developer at `implement` can hand off `changes_requested` with a `dispute` object (test id, design rule id, reason) to send the story back to `tests` without a bounce.

2. **Free disputes bounded:** The first `round_cap` disputes on a story cost no round; later disputes cost one round each, like any bounce. Rulings reset the dispute count.

3. **Rulings at any step:** A Manager ruling applies at any step (implement, tests, design, etc.), not only at round cap. If a ruling cannot apply (e.g., story is done), the report shows why with no change to the story.

4. **Dispute tracking:** `StoryState` adds `dispute: OpenDispute | None` (test, rule, reason, base commit, stage: raised/confirmed) and `disputes: int` (count).

5. **Dispute visibility:** While a dispute is open, it appears in the brief at every step (unit-tester, architect, manager). The stage changes from `raised` to `confirmed` when the tester escalates to the architect.

## Consequences

- **For developers:** One-line test slips no longer stall the story or need manual edits. Disputes are free if upheld by the tester, but cost a round if confirmed to be correct.
- **For testers:** Disputed tests require explicit action: fix the test, or confirm it with `changes_requested` to escalate to the architect.
- **For architects:** Rulings are now available mid-story to resolve disputes, not just at round cap.
- **For the manager:** Rulings give fine-grained control over stuck stories; disputes are tracked per-story and per-role to spot patterns.
- **For the runner:** The route is new (`implement` → `tests` via dispute), with safeguards against dodging rounds: free disputes reset only on rulng; the diff gate ensures no one can satisfy the dispute alone.
- **Code:** 56 new lines in design, ~430 new/changed lines in runner (roles, gates, dispatch, events, insights, state, handover, dashboard, role files). Coverage stays at 99.94%; ruff clean.

## Related decisions

- ADR-0012 (s24): Gate and hold clearing—provides the foundation for rulings at any step.
- ADR-0014 (s27): Escalate repeated setbacks—Manager context now includes `test_disputes_since_last_review`.
- ADR-0017 (s29): Interrupted step commit—disputes are preserved across runner restarts.
