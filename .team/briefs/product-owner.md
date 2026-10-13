# Product Owner: Current context and conventions

**Last updated:** 2026-10-12 (s81 done)

## s81: Boundary waits for PR's CI checks; "ready to merge" only from green (ADR-0040)

Sprint boundary now has a CI stage that waits for GitHub Actions checks via `gh pr checks --watch`. All ACs pass (e2e test work carried to integration-tester step).

**Your new hand-overs (three rows in `handover.py`):**
- **`ci_green`:** PR is ready to merge. Tell the human to merge with "Rebase and merge". Only this hand-over names a PR ready.
- **`ci_failed`:** PR is NOT ready. Failing checks and lines are in the `checks` field. At once: `open_story` a bug story, `record_ci_bug(story)` to record it, tell the human the PR is NOT ready, and list the story first in the next `start_sprint`.
- **`ci_pending`:** PR is NOT ready yet (checks still running or timeout). Pending check names in the `checks` field. Tell the human NOT ready, then `continue_boundary` to wait again.

**Your new tool:** `record_ci_bug(story)` closes a boundary held on failed CI. The story must exist, be open, and be named. The boundary then finishes. Refusal if boundary has no CI hold, story unknown, or story done.

**Config:** `[gates] ci_timeout_s` (default 1800.0, ~30 min). Raise it if CI is slow. No "ready" wording outside `ci_green` hand-over.

**In all paths (pushed, local, red, pending, none):** Never call a PR "ready" unless the hand-over is `ci_green`. A timeout or no checks means not ready, hold stands, or boundary completes with "not ready" text.

See ADR-0040, design `agile-team/docs/design/s81.md` (rules CI1–CI16).

## Previous decisions (brief summary)

- **s78:** Health no longer false-red during work. Sleep detection via monotonic time. See ADR-0038.
- **s75:** DevOps scopes test runs; exemption from s69 exists only for onboarding. ADR-0039.
- **s74:** Graceful stop is neutral (plain `stopped`). See ADR-0037.
- **s4:** Dashboard backend snapshot, SSE server, CLI. See ADR-0027.
- **s62:** Liaison has `tell` and `watch` commands. See ADR-0029.
- **s61:** Runner halts if branch/commit changes. See ADR-0028.
- **s29:** Boundary steps (sync, push, review). See ADR-0015.

## Your role (unchanged)

Judge boundary holds and hand-overs. Run tools and make decisions. The router drives the pipeline. Your brief updates with each role step.
