# ADR-0040: CI waits at sprint boundary; only green checks mark PR ready

**Decision:** The sprint boundary gains a new CI stage that waits for the PR's GitHub Actions checks to pass. Only a green verdict marks the PR "ready to merge". Red checks hold the boundary until a bug story is opened and recorded. Timeout or no CI reports the PR as not ready.

**Date:** 2026-10-12

## Context

Sprint #21 (PR #14) passed the team's own boundary checks but failed CI on four e2e tests that pass only on the human's machine. The runner reported the PR as ready when it was not, and the human discovered the failures later. This forced a decision: who ensures CI is green before a PR leaves the team's hands?

The alternative approaches:
1. The human checks manually (informal, error-prone).
2. The runner waits for CI before marking the PR ready (inline with boundary, data-driven, testable).

## Decision

### Rules

The boundary gains one final stage (`Stage.CI`) after push. It waits for the PR's checks via `gh pr checks --watch` under a configurable timeout (`ci_timeout_s`, default 1800s). The verdict is based on check buckets (pass, fail, pending, skipping, cancel), computed per-PR and overall. The boundary completes only when every PR is green, or when a recorded bug story names the CI failure.

| Rule | Content |
|------|---------|
| **CI1** | **New stage.** `STAGES = (SYNC, CHECK, REVIEW, PUSH, CI)`; `CI` runs after `PUSH` on every boundary that pushed, and at a start only when restacking. Local, nothing, and push-rejected paths never reach it. |
| **CI2** | **What is watched.** Only `PrMode.READY` entries with a PR number, in stack order. Drafts are not watched (CI skips them). No entry to watch → verdict `NONE`. |
| **CI3** | **The wait.** For each watched PR, run `gh pr checks <n> --watch` under a deadline: `system.monotonic() + [gates] ci_timeout_s`. After the watch ends or times out, read `gh pr checks <n> --json name,state,bucket,link,workflow` and record the result. Watch exit code only means "ended" (0 or 1) or "timed out" (124). |
| **CI4** | **No checks at first.** Right after a push, GitHub reports no checks. On first check=[], sleep and look again up to 12 times (≈2 min grace) before giving up. |
| **CI5** | **Check buckets map to verdict.** `Bucket` enum: `pass`, `fail`, `pending`, `skipping`, `cancel`. Unknown bucket → `FAIL` (safe side: not green). |
| **CI6** | **One PR's verdict.** `verdict_of(checks)`: each bucket maps to `BUCKET_VERDICT` (pass→green, fail→red, cancel→red, pending→pending, skipping→none). Verdict is the first of `(red, pending, green)` found, else `none`. |
| **CI7** | **Overall verdict.** `overall(results)`: first of `(red, pending, none, green)` among all PR verdicts, else `none`. Green only when every PR is green. |
| **CI8** | **Failing lines.** For each failed check, extract the job id from `link` and read its log via `gh run view --job <id> --log-failed`. Keep lines matching pytest/go failure patterns, at most 20 lines, or the last 10 lines if no match. |
| **CI9** | **State and event.** Each watched entry gets `StackEntry.ci = CiResult(pr, url, head, verdict, checks)`. The boundary event includes `ci` (overall verdict), `prs` (text list), and `checks` (formatted failing lines). Results are asdict'd and logged. |
| **CI10** | **Outcomes.** (1) `GREEN`: boundary finishes, report says "ready to merge". (2) `RED`: boundary held `ci_failed`, report says "NOT ready"; PO must open a bug story and call `record_ci_bug(story)` to finish. (3) `PENDING`: boundary held `ci_pending`, report names the pending checks. (4) `NONE`: boundary finishes, report says "no CI result exists" (no open non-draft PR or no checks reported). |
| **CI11** | **Done only with green or recorded bug.** A `ci_failed` hold ends when: (a) `record_ci_bug(story)` names a story that exists and is not done, OR (b) `continue_boundary` reruns the CI stage (human re-ran checks and they passed). Only (a) closes the boundary; (b) only clears the hold. |
| **CI12** | **"Ready" only from green.** The phrase "ready to merge" appears only in the green report (built only by `ci.green_report`, which raises `ValueError` for any non-green result). Every other text says NOT ready. |
| **CI13** | **No PR, no CI.** Without `gh`, logged out, or with push permission `no`, the boundary ends at push. No CI verdict exists; PR is not called ready. |
| **CI14** | **Bug story first.** While `upstream.ci_bug` names an open story, `start_sprint` refuses unless that story is first in the list. A successful `start_sprint` clears `ci_bug`. |
| **CI15** | **Blocking is acceptable.** The CI stage blocks the router up to `ci_timeout_s`, like gate commands do. It runs inside `pulse.doing()`, so health stays green. Tell messages are delivered after. Resume reruns the CI stage; push stage was saved before it. |
| **CI16** | **Errors.** Unparsable `--json` output raises `UpstreamError`. `gh` timeout returns code 124 and message `"gh timed out after {limit}s"`; `_gh` turns it into `UpstreamError`. |

### Implementation approach

- **`agile_team/ci.py` (new):** Dataclasses `Check`, `CiResult`. Enums `Bucket`, `CiVerdict`. Functions to parse gh output, compute verdicts per-PR and overall, extract failing lines, format text. Class `CiWatch` to wait for CI and collect results.
- **`boundary.py`, `boundary_runner.py`:** New stage and methods. New holds `CI_FAILED`, `CI_PENDING`. New outcome functions. Integration with `record_ci_bug` tool via `settle_bug()`.
- **`po_tools.py`:** New `record_ci_bug(story)` tool. Refusals: no boundary held on CI, unknown story, done story.
- **`handover.py`:** Three new triggers: `CI_GREEN`, `CI_FAILED`, `CI_PENDING`. Rules apply per-report shape.
- **`upstream.py`:** `Prs` protocol gains `wait_checks`, `checks`, `failed_log`. `GhPrs` implements them via `gh` commands.
- **`config.py`:** New `Gates.ci_timeout_s` with default 1800.0.
- **`state.py`:** `UpstreamState.ci_bug`, `StackEntry.ci`. Legacy files load with defaults.

### Why this design

**Inline with boundary:** CI is the last check before marking ready. No separate system, no out-of-band polling. Failure → hold. Human opens bug story → unblock.

**Data-driven verdicts:** Bucket-to-verdict mapping is explicit and auditable. Same rules apply to all PRs. New tests can verify edge cases (all pending, mixed, cancel) without guessing.

**Blocking is safe:** The boundary waits up to `ci_timeout_s` (default 30 min, human-changeable). Health stays green via `pulse.doing()`. Resume works: push is saved before CI, so resume reruns the wait.

**Bug story is the gate:** Red CI alone doesn't unblock. A recorded story ensures the human acknowledged the failure and opened a fix. First-in-sprint rule ensures the fix runs before unrelated work.

**No "ready" from failing:** The phrase "ready to merge" appears only in the one report text and one hand-over line that apply to green. A timeout or pending checks are explicitly NOT ready, so the human sees the distinction clearly.

## Consequences

**Positive:**
- PRs leaving the team are CI-green (or have a recorded bug story to fix them).
- The boundary is the single point of truth; no separate checks needed.
- Data-driven verdict rules are testable and auditable.
- The PO has a single tool (`record_ci_bug`) and knows the flow (hold → story → first in sprint → continue).
- Timeout is configurable and can be raised if 30 min is too short for the team's CI.

**Tradeoffs:**
- The boundary can block for up to `ci_timeout_s`, holding all sprint stories. The human must raise the limit if CI is genuinely slow or flaky.
- A draft PR is not watched (CI skips drafts). If a non-draft PR at the boundary becomes a draft, CI is skipped; the human must reset it to non-draft or change the boundary.
- Integration-tester still needs to write an e2e test with a stub `gh` script (AC7); the story is accepted with this gap (design provides the spec).

**Future:**
- If CI timeouts are frequent, add a retry tool so humans can re-run without re-pushing.
- If draft handling becomes complex, revisit when drafts are introduced as a team pattern.
- The snapshot currently shows `upstream.boundary.stage`, which will now show `ci`; no contract change.

## Amended by s111 (2026-10-14)

ADR-0064 replaces CI10 and CI11. Verdicts now come from each check's kind (`green`, `stale`,
`ours`, `infra`, `main`, …), which the runner reads from GitHub's job data, and no longer from
the bucket alone. `continue_boundary` at `ci_failed` is refused: that hold now means our code ran
and failed. A job that never ran a step is re-run by the runner once; if it still never runs,
the boundary holds `ci_infra`. A failure that main's head has too holds `main_broken`, and
`record_ci_bug` there ends the sprint as "ended, CI blocked by main". `record_ci_bug` works at
all three holds. A green run counts only on the commit the runner pushed.

## References

- Story: `.team/stories/s81.md`
- Design: `agile-team/docs/design/s81.md` (rules CI1–CI16, test checklist, exact signatures)
- Review: `.team/reviews/s81.md` (round 5: tests fixed, e2e pending)
- Acceptance: `.team/acceptance/s81.md` (AC1–AC8 pass; e2e test work carried to integration-tester step)
