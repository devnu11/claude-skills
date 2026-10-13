# Customer Proxy: Current context and conventions

**Last updated:** 2026-10-12 (s81 acceptance complete)

## s81: Sprint boundary waits for PR's CI; you'll see outcomes in docs

Story accepted. All ACs verified. AC2–AC6 outcomes observed via customer docs: green CI marks PR "ready to merge with Rebase and merge"; red CI marks PR "NOT ready" with failing test lines and job names; pending CI waits (NOT ready yet); no CI reports "no CI result exists". AC1: config `[gates] ci_timeout_s` documented (default 1800s). AC7 (e2e test with stub gh) is integration-tester work. AC8: docs updated.

**For your acceptance of future stories:**
- If the boundary hand-over is `ci_green`, the PR is ready; the human can merge it.
- If `ci_failed`, the PR is NOT ready; the human must wait for a bug fix (story listed first next sprint).
- If `ci_pending`, NOT ready yet; boundary is waiting.
- If no CI hand-over (boundary done with `ci: none`), no checks reported (old behavior, not ready).

**Your scope unchanged:** No new sandbox rules. Service deliveries still started before your trial. Presentation.md still required. No changes to your interaction with the runner or the human.

See design `agile-team/docs/design/s81.md`, ADR-0040.

## Your role

Verify the team's delivered product in a sandbox. Test acceptance criteria. Report evidence. You cannot break the boundary check (runner code), but you verify CI outcomes make sense (green when they should, red with clear error lines).
