# ADR-0039: DevOps test scoping and exemption boundary

**Status:** Accepted  
**Story:** s75  
**Date:** 2026-10-12  

## Context

In s69 (ADR-0034), the runner began denying full-suite and coverage runs to every role except DevOps, because onboarding asks DevOps to run every toolchain command and record the coverage baseline. This created an exemption for DevOps to fulfill that requirement.

The human (responding to round 1 questions) clarified that DevOps should keep the exemption, but scope its test runs: normally a single named test proves a change. This is a boundary: the exemption exists *only* to record the baseline during onboarding, not as a general license to run the full suite whenever.

## Decision

DevOps is exempt from the full-suite and coverage deny (rules S8–S10 in s69). This exemption applies only to the onboarding sprint, where DevOps records the baseline (`coverage` and `lint_warnings` in `.team/baseline.json`).

In all other work, DevOps must scope its test runs to what proves the change:
- Normally one named test (`pytest -q --no-header tests/test_x.py::test_y`)
- Never the full suite or a coverage run; the runner's gate produces those
- In boundary fixes: run the failing tests the brief names; the runner re-runs full checks
- For changes to test or coverage commands themselves: say in the summary that the change waits on the runner's next check

The boundary is enforced in the role file (`agile-team/runner/agile_team/roles/devops.md`), not in code. The runner's gate (not DevOps) produces suite and coverage evidence.

## Consequences

1. **Role file now documents the exemption and its boundary (s75 AC1, D1–D5).** The `## Test runs` section replaces the blanket exemption with a clear rule: run only what proves the change, normally one test. The `## Onboarding sprint` section explicitly says onboarding is the one step where DevOps runs the full suite and coverage command.

2. **Test coverage established (s75 AC2, D2–D4).** `test_devops_scopes_its_test_runs` in `tests/test_roles.py` asserts five key phrases from the role file, ensuring the rule does not drift if the file is refactored.

3. **Docs move with the behaviour (s75 AC3, D7).** `reference/protocol.md` (the "Every role but DevOps" bullet in s69), `SKILL.md` (the "Only the runner runs the full suite" rule), and `docs/customer/routing.md` (the "Who runs the tests" section) all mention the exemption and the boundary.

4. **No code change to enforce this (D6).** `suite_check.SUITE_RULES` keeps `"devops"` in both `FULL` and `COVERAGE` allowed sets. The exemption is a matter of role discipline, not gate enforcement. Runners that trust roles to read their documentation can rely on this boundary; runners that do not trust need additional code-level guards (out of scope).

5. **Future onboarding steps work as designed.** When a new onboarding sprint runs, DevOps can safely run the full suite and coverage command to record the baseline, and the gate will not deny it. After onboarding, DevOps returns to the scoped-test rule.

## Alternatives considered

1. **Code-level enforcement:** Make the gate deny the full suite and coverage to DevOps outside onboarding. This would require a notion of "onboarding mode" tracked in state. Rejected: the boundary is about intent, not enforcement. A role that reads the brief knows whether they are in onboarding or not. Adding state complexity is not worth it.

2. **No documentation, rely on prompt:** Leave the exemption undocumented and rely on the next human to understand s69. Rejected: s75 exists to make the boundary explicit and durable.

3. **Exempt DevOps entirely, no boundary.** Keep the exemption open-ended. Rejected: the human explicitly asked for scoping in response to round 1.

## Related decisions

- **ADR-0034:** "Only the runner runs the full suite"—establishes the s69 exemption for DevOps.
- **s69 design:** Rules S1–S10 define the full-suite and coverage deny; S8 carves out the DevOps exemption.
- **s67 design:** DevOps scope clarified in one of the context updates.

## Verification

- AC1: Role file text matches design exactly; placement right; nothing else in the file changed. ✓
- AC2: Test `test_devops_scopes_its_test_runs` asserts the five phrases; all present in whitespace-collapsed body. ✓
- AC3: Protocol, SKILL.md, routing.md all mention the exemption and rule; all three agree with each other and the role file. ✓
- Coverage 99.64% (runner, implement gate at `7d90a76`). ✓
- Ruff clean. ✓
