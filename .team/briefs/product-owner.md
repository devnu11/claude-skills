# Product Owner: Current context and conventions

**Last updated:** 2026-10-12 (s51 done)

## s51: Started stories rank first; pulls need reasons (ADR-0016 amended)

Stories with commits always rank first, held started ones after in-progress, then stories not yet started. Your order ranks stories within each group. To pull a not-started story ahead of started ones, use `prioritise` or `move_story` with a reason; without one the tool is refused. `start_sprint` never pulls. **ADR-0016 amended:** ranking rule is `(done, RANK[tier], listed, natural(id))` where `RANK` = {in progress: 0, held: 1, not started: 2}. New `state.pulled` field holds pulled story ids. Priority events now include `"pulled"` in data for audit.

## s65: Git safety—presentations and acceptance run in isolated git (no new ADR)

S61 incident fixed: integration-tester's demo no longer has a path to the human's branches. Two safeguards now:
1. **Environment:** Confined steps get `GIT_CEILING_DIRECTORIES` so git can't climb out of `.team/run`.
2. **Guard:** New `git_check` module sees through `env`, `command`, prefixes; denies git targeting the team repo, allows git in the workspace.

**What changes for you:** Nothing. No new hand-overs, no new tools. Presentations and acceptance work as before, but safer. If a delivery's script accidentally targets the team repo, the guard denies it with a clear message (naming the repo). S67's e2e watch test passed, so the workspace demo rebuilt safely.

No new dependency, no ADR (extends guard pattern). See design `agile-team/docs/design/s65.md` (rules G1–G10).

## s59: Sprint-start sync rebases the team branch onto main (ADR-0041)

Sync no longer merges; it rebases, dropping commits already upstream. False conflicts from sprint 18 (~100 on m54) are gone. Hashes pinned before rebase and rewritten after; nothing is lost. Real conflicts abort cleanly; human rebases by hand and continues. End-edge unchanged. One new boundary outcome: `rebased` (tree kept, hashes rewritten; tone: `good`).

**What changed for you:**
- `sync_conflict` hand-over now lists conflicting files grouped by directory with counts, e.g. ". (1): README.md; src (2): a.py, b.py".
- No more `-s ours` or `-X ours` merges. The branch is always linear.
- New tool: none (the old `merge_in` is gone; `rebase_onto` is internal).

See ADR-0041, design `agile-team/docs/design/s59.md` (rules R1–R12), review round 3 (all defects fixed; e2e pending for integration-tester).

## s89: Unit suite passes on 3.13 (OS guard refined, test infrastructure, no new ADR)

Bug fix. 36 unit tests failed on 3.13 when formatting tracebacks because Python 3.13's `linecache` read source via a path the guard charged to the wrong caller. Guard refined with rules T1–T6: allow stdlib source reads inside guarded frames, still catch real code. Accepted on AC1–AC3 (unit pass, traceback works, guard still catches real OS). AC4 (CI green on PR #16) verified at s81 CI boundary. No runtime changes, no new ADR (extends s71).

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
