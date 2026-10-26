# ADR-0075: The sprint end pushes the team branch as built, gates the rebase on its green CI, then pushes again

**Date:** 2026-10-15 (s151 design)
**Status:** Accepted
**Amends:** ADR-0015 (review stack), ADR-0041 (end rebase), ADR-0040 (CI wait)

## Context

Until s151 a sprint end built a **review branch** by cherry-picking the
sprint's own commits onto the latest main in a scratch worktree (`review`),
checked it, pushed it, rebased the team branch (`rebase`), and then
restacked every open sprint PR bottom up (`restack`), each PR based on the
one below. So the first thing CI saw was a rebuilt branch, not the branch
the team built and tested, and the PR never showed what the rebase changed.

The human asked (2026-10-14, restated at the sprint 44 end) for: push the
team branch as it is, wait for green CI as a gate, rebase it onto main
locally, push it again to the same PR, and wait for CI again, which may be
red. The PR then holds both pushes, and the force-push's compare link shows
what the rebase changed.

## Decision

1. **End stages** are `sync`, `check`, `push`, `ci`, `rebase`,
   `push-rebased`, `ci-rebased`, in that order. The start stays `sync`,
   `check`. `review` and `restack` are removed, with `stack.py`,
   `restack.py`, the review worktree, the `review-fix` step kind and the
   `review_check` and `review_conflict` fix cases.
2. **One PR per sprint, based on main.** `push` sends the team branch's HEAD
   (a sha refspec; no local review branch is made) to `<prefix><N>` with
   `--force-with-lease` against the sha the runner last pushed there, then
   creates or reuses the PR `<prefix><N>` → `[upstream] branch`, ready.
   Earlier sprints' entries are dropped from `upstream.stack` at the end
   `sync` (`superseded` events), because the new branch holds their
   commits. Their PR numbers go into the new PR's body. Their PRs are left
   open; the runner closes nothing.
3. **Green is the gate, in code.** `boundary.rebase_refusal(entry)` refuses
   the rebase unless the sprint's entry has a CI read that is green on the
   sha it pushed. The `rebase` stage checks it first. A refusal changes
   nothing, holds the boundary (`error`, outcome `refused`) and sets the
   stage back to `ci`, so `continue_boundary` waits for CI again.
4. **No CI, no rebase.** With no `gh`, no permission, a closed PR or no
   checks, the boundary finishes after `push` or `ci` with the report and
   the sentence "The team branch is not rebased …". A `record_ci_bug` after
   a red, infra or main hold finishes it the same way.
5. **The second CI never holds.** `ci-rebased` records its result on the
   entry (`ci`) and the `done` event. Green finishes with the "ready to
   merge" text; anything else finishes with a "NOT ready" report to the PO
   and the liaison. An `infra` check still gets its one re-run per head. A
   rebase that changed nothing (`current`) skips the second push and CI: the
   as-built green is the green of that head.

## Consequences

- The PR's first push is exactly what the team tested; the human sees the
  rebase as a force-push in the PR's history.
- A team without `gh`, without push permission or without CI no longer
  rebases at the sprint end. Until the sprint start rebases (a follow-up
  story the liaison proposed), it drifts from main, and the start sync's
  "main moved N commits" note grows.
- When the as-built branch conflicts with main, GitHub runs no
  `pull_request` workflow on it, so no green comes and the end does not
  rebase (verdict `none`). The human rebases by hand, or the follow-up start
  rebase does it.
- Earlier unmerged sprint PRs are no longer updated; the newest PR holds all
  their commits, and merging it merges them.
- `upstream.stack` holds at most the current sprint's entry after an end
  sync. `StackEntry.check` and `checked` and `Boundary.restack` are retired;
  `state.json` drops them on load, and a saved boundary at `review` or
  `restack`, or with a `review_*` failure, loads at `push` with no failure.
- The `rebase` stage's rules R1 to R11 (ADR-0041) are unchanged.

## Amended by s152 (2026-10-15)

The follow-up start rebase is ADR-0077: the start `sync` rebases the team
branch onto the target. A start conflict is aborted and holds nothing, so a
team branch that conflicts with main still waits for the human's hand
rebase: its as-built PR gets no CI (`none`), and the end does not rebase.

## Amended by s159 (2026-10-18)

The sprint branch is now built from story merges (ADR-0084). The sprint
start creates `<prefix><N>` and its stack entry, and each landing pushes it.
Its PR is a draft from the first landing on. The as-built push and its green
CI still gate the end. The rebase is replaced by a **replay**: the
first-parent line is replayed onto main, each story re-merged, and the
result goes to a new branch `<prefix><N>-r<k>` with a ready PR. It is no
longer force-pushed to the same PR, because no push may replace history.
The entry keeps the as-built record (`as_is_branch`, `as_is`, `as_is_pr`),
and the old draft PR is closed with a link. main moves only by
fast-forward, which the reports give as a command instead of "Rebase and
merge". End stages are `sync, check, push, ci, replay, push-replayed,
ci-replayed`.

## Amended by s183 (2026-10-25)

A sprint can reach main before its END boundary runs, for example when the
human fast-forwards main to the sprint head. Until now, `push-replayed`
compared HEAD only with the entry's `pushed` sha. It pushed `-r<k>` and asked
for a PR that GitHub refused, and a rerun then marked a merged PR ready.
Now `push-replayed` on the END edge first fetches and checks whether the
target contains HEAD (their merge base is HEAD). If it does, the sprint
closes as **shipped**: no push, no PR created or made ready, the recorded PR
closed when it is still open (a merged one is left as is) and the entry's
mode set to `closed`. The `done` event and the PO's `Review:` text say the
sprint is already on the target at that sha. The event carries no `ci` key,
so `ci_green` ("ready to merge") does not fire. Green CI on the as-built
push still gates the end, because `replay` runs only after it. A target
that holds only part of the sprint, or holds it only by patch, gets the
replay push as before.
