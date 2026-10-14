# ADR-0064: CI failures are classed from GitHub's job data; only a green read of the pushed head is done

**Date:** 2026-10-14 (s111)
**Amends:** ADR-0040 (CI10, CI11), ADR-0049 (the CI rule is now enforced in code)
**Design:** `agile-team/docs/design/s111.md`

## Context

Since s81 the CI stage has judged a PR from the check buckets that `gh pr checks` reports. A red
result held `ci_failed`, and `continue_boundary` there was never refused. So a PO could wave a
failure through with a re-run that happened to turn green. s110 wrote the rule down ("a re-run
counts only when the failed job never ran our code") in the prompt only. Two more gaps:

- Nothing tied a green run to the commit the runner pushed.
- A failure that main's head has too blocked the sprint as if the team had caused it.

The human decided (t59, m121) that a broken main must not stop the team. The sprint is then not
done, and its PR waits until CI is green.

## Decision

1. **The runner reads GitHub's job data itself.** For each check with an Actions job link, it
   reads the job through `gh api repos/{owner}/{repo}/actions/jobs/<id>`: its commit and its
   steps. Required checks come from `gh pr checks --required`; when a repo marks none, every
   check counts. All of this goes through the existing `Prs` interface (`job`, `main_checks`,
   `rerun`), so no new dependency is added.
2. **Each check gets a kind** (new pure module `ci_triage.py`): `green`, `skipped`, `pending`,
   `stale` (its job ran on another commit; it is ignored), `ours` (it failed after running a
   step), `infra` (it failed or was cancelled with no step run; GitHub's own `Set up job` and
   `Complete job` don't count as steps), `main` (an `ours` failure whose check name and failing
   step also fail on main's head), and `rerun`. The kinds are kept on `Check` in `state.json`.
   Verdicts come from kinds through tables (`KIND_VERDICT`, `CHECK_ORDER`, `PR_ORDER`).
3. **Outcomes.** `green` finishes the boundary as done (the only "ready to merge"). `ours` holds
   `ci_failed`, and `continue_boundary` there is **refused** (`CI_OURS_REFUSAL`). `infra` is
   re-run by the runner once per job and pushed head (`StackEntry.reran` keys); after that it
   holds `ci_infra`. `main` holds `main_broken`. `stale` and still-running checks hold
   `ci_pending`.
4. **`record_ci_bug`** works at `ci_failed`, `ci_infra` and `main_broken`, and never finishes
   green. At `main_broken` the sprint ends as "ended, CI blocked by main". The bug story is first
   in the next sprint (CI14), and the unmerged PR is watched again at the next sprint end.
5. **The runner does not write story files.** At `main_broken` it holds and the PO opens the bug
   story for main and records it in the same turn.
6. **The Board shows the CI state** per stack entry: a `Card` (`state`, `text`) in the snapshot's
   `upstream.stack[].ci`, rendered as a pill.

## Consequences

- No note, answer or tool call can turn a red or pending sprint green. Only the runner's own read
  of the pushed head can.
- A broken main costs the team one PO turn, not a sprint.
- Every CI read makes one `gh api` call per Actions check, and one more read of main when
  something is `ours`. Read twice at most per boundary tick, this is cheap next to the CI wait.
- Known limits: a check that is not an Actions job can't be tied to a commit, and is `ours` when
  it fails. Only checks that also run on main can be classed `main`.
- Old `state.json` files load: a check without a kind is mapped from its bucket (`fail`/`cancel`
  → `ours`), and `reran` defaults to `[]`.
