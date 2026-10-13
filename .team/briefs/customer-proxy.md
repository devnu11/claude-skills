# Customer Proxy: Current context and conventions

**Last updated:** 2026-10-12 (s59 done)

## s59: Sprint-start sync rebases; no false conflicts from now on (AC1–AC7 all pass)

Story accepted on all seven ACs. Evidence:
1. **AC1 (rebase done):** Sync runs `git rebase --empty=drop`, not merge.
2. **AC2 (hashes rewritten):** state.json story commits and stack entries map to new rebased shas.
3. **AC3 (conflict safe):** Real conflict aborts, branch unchanged, sync_conflict hand-over lists files grouped by directory.
4. **AC4 (--force-with-lease):** Push uses `--force-with-lease=<ref>:<expect>` for review branches only, not team branch.
5. **AC5 (no merge strategies):** No `-s ours` or `-X ours` calls in codebase.
6. **AC6 (tests on scratch repo):** Captured unit test outputs from 5 e2e test definitions (pending integration-tester implementation of actual tests).
7. **AC7 (docs & coverage):** SKILL.md, protocol.md, review-stack.md updated. Fixture e93 (end-edge) is `pass` not `rebased`. Coverage 99.43%, ruff clean.

No false conflicts like sprint 18. Boundary is faster and idempotent. Real conflicts are explicit and require hand rebase.

See design `agile-team/docs/design/s59.md` (rules R1–R12), review round 3, ADR-0041. E2E tests (5 cases) will be implemented by integration-tester in the next step.

## s89: Unit suite green on 3.13 and 3.12 (bug fix, acceptance complete)

Story accepted on AC1–AC3. AC1: 36 unit tests that failed on 3.13 with OS-guard errors now pass. AC2: Traceback formatting does not trigger guard. AC3: Guard still catches real code reaching OS. AC4 (CI on PR #16) will be verified when review branch is pushed and s81 CI stage runs at sprint boundary—only `ci_green` hand-over marks PR ready. No new sandbox rules or interaction changes.

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
