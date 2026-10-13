# ADR-005: Merge upstream in, review on rebuilt branches, stack the PRs as drafts

Status: accepted (s29). Date: 2026-10-10. Design: [`../design/s29.md`](../design/s29.md).
Decision 1 is superseded by [ADR-012](ADR-012-rebase-at-sprint-start.md) (s59):
the sprint-start sync rebases and rewrites the recorded hashes.

## Context

The team works on one branch for many sprints. The run records commit
hashes in `state.json` (each story's `commit`, dispute bases), in review
files and in designs. The human wants three things. Each sprint should
start from the latest upstream and be verified. What reaches main should be
rebased onto the latest main and verified. And a stack of unmerged sprints
should not make CI run once per PR on every update. PR #10 was landed by
hand this way: a rebased scratch copy, merged to main with "Rebase and
merge".

## Decision

1. **Merge in, never rewrite.** At sprint start the runner merges
   `<remote>/<branch>` into the team branch. A fast-forward or a local merge
   commit is fine. If nothing is new, no commit is made. The team branch is
   never rebased, reset or amended, so every recorded hash stays valid. A
   merge conflict is aborted and handed to the PO, and the human merges by
   hand.
2. **Review branches are rebuilt from the team branch.** At sprint end,
   each unmerged sprint's own commits are cherry-picked onto the latest main
   in a scratch worktree (`.team/run/review/`). Each sprint's commits go
   onto the review branch of the sprint below. Merge commits and anything
   already in main (by patch id) drop out. The branches are rebuilt from
   scratch every time and never edited by hand. For that reason a fix for a
   failed check goes on the team branch and reaches the review branches
   through the next rebuild. A conflict is resolved in the worktree and
   recorded with `git rerere`, so the next rebuild reuses the resolution.
3. **Stacked PRs, one per sprint, drafts below the top of the queue.** The
   bottom PR targets main and is ready for review. Every other PR is a
   draft that targets the review branch below it. The CI workflows skip
   draft PRs, so CI runs once per merge however deep the stack is. Once the
   bottom PR is merged (as a rebase merge), the next rebuild drops it
   (its patches are in main). The next PR is retargeted to main and marked
   ready.
4. **Boundaries are code, and failures escalate like setbacks.** Sync,
   full checks, rebuild and push are runner stages that no prompt can skip.
   A failed check becomes a DevOps fix step whose brief quotes the output.
   The same failure twice in a row (s27's normalised key) or `round_cap`
   fix steps escalate to the Manager, and then to the PO.
5. **Push permission is asked once.** The PO asks the human the first time
   a push is needed and records the answer in `state.json`. With "no", the
   runner builds and checks the branches locally and reports them. The only
   branches the runner pushes are review branches, with
   `--force-with-lease` against the sha it last pushed. It never pushes the
   team branch or main.

## Alternatives rejected

- **Rebase the team branch itself.** That would invalidate every recorded
  hash, and the human ruled it out.
- **One `git rebase` of the whole stack, split afterwards.** The sprint end
  heads are often merge commits that a rebase drops, so mapping the
  rewritten commits back to sprints needs hooks or guesswork.
  `--update-refs` has the same problem and needs git 2.38. Per-sprint
  cherry-picks of a computed list are explicit and testable.
- **Fixes on the review branch, carried forward.** That would keep a
  second source of commits per sprint, which has to be replayed and can
  conflict with the team branch. It was left out (see the design's Known
  limits).
- **CI on every PR.** It is too slow and costly for a deep stack.

## Consequences

- `state.json` gains `boundary`, `upstream` (team branch, push permission,
  stack, last checked sha, last closed sprint, report) and `goal`. Older
  files load empty. The first sprint end after the upgrade puts every
  unmerged team commit in the first PR.
- Each sprint's start and end take one runner step each, plus the time of
  the full checks. A repo with no remote skips both with one event.
- The human must merge with "Rebase and merge" for the stack to drop merged
  sprints cleanly.
- `gh` is used only through `upstream.Prs`. Without it, the branches are
  built and checked but not pushed.
