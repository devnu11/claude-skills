# ADR-0092: A story rebase step's settle adds no commit to its branch

Story: s182. Design: `agile-team/docs/design/s182.md` (R1 to R9).

## Context

After every step, the runner settles the tree. It commits in-scope leftovers
as a `fixup!` of the story's first commit, and it quarantines out-of-scope
edits as a commit plus its revert. A story rebase step (s159 S3) is then
checked by comparing its commits' subjects, in order, with the old branch's.
Because the settle runs first, every runner commit counts as a commit the
role added, so a rebase with any leftover can never pass. The bounce keeps
the rebase queued. A Manager `advance` moved the step on, and the same check
failed again under each new step name. s180 was reverted to the Product
Backlog for this (sprint 52).

## Decision

1. **Own settle.** A finished story rebase step is settled by its own
   function and never by the general `settle_tree`. There is no step commit,
   no requirement sorting and no hold-back.
2. **Set aside, off the branch.** Out-of-scope edits are committed alone,
   kept at `refs/agile-team/set-aside/<sha>`, and the branch goes back to the
   commit's parent with `git reset --keep HEAD^`. Refs outside `refs/heads`
   are shared by worktrees, are never pushed, and are not branches, so the
   s176 record of branch heads (ADR-0091) doesn't see them.
3. **Fold, don't bounce.** In-scope leftovers are amended into the rebased
   tip with its message unchanged, when the rebase is finished, on its
   branch, on `onto`, and has at least one commit. Otherwise they stay, and
   the dirty-tree refusal names them. The runner records each tip it made on
   `StoryRebase.made`.
4. **Name the commits.** The changed-commits refusal lists each extra,
   missing and changed commit by short sha and subject. Extra and changed
   commits say whether the runner (a sha in `made`) or the role made them.
5. **No advance past a queued rebase.** `advance` is refused while
   `story.rebase` is set. `upgrade_model` retries the rebase.
6. The boundary's scratch rebase check (`scratch_rebase`) is unchanged.
   `settle_tree` never commits into its scratch worktree.

## Consequences

- A correct rebase is adopted whatever the role left uncommitted. An edit
  folded into the tip lands in the last replayed commit, not necessarily in
  the commit whose conflict it resolves. The story's total diff is the same.
- Set-aside refs pile up under `refs/agile-team/set-aside/`. Nothing prunes
  them yet. They are small and local.
- Rule for later changes: nothing the runner does at the end of a story
  rebase step may add a commit to `onto..HEAD` before the commits check runs.
- A Manager who wants a stuck rebase gone must rescope, revise the design or
  escalate. `advance` no longer hides the rebase behind a step move.
