# ADR-0091: A story rebase step moves only its own branch

Story: s176. Design: `agile-team/docs/design/s176.md` (B1 to B10).

## Context

The story rebase step (s159 S2) runs local git in a story's worktree under
`Allows.LOCAL`. That rule checks the subcommand and a few flags. The
worktree shares the repo's refs, so `git checkout -B <other>`, `git rebase
<onto> <other>`, or `git reset` while HEAD is on another branch moves a
branch that belongs to another story, or the old story branch. The checks
after the step look only at the rebase branch. The sprint-51 review accepted
this as a known gap.

A guard that reads a command can't follow every way git moves a ref, so a
check of the result is needed too. Comparing every local branch isn't safe
on its own either. The runner moves branches while a step runs: other
stories' steps commit, other rebases start, and landings move the sprint
branch. A naive compare would bounce a good step and undo the runner's work.

## Decision

1. **Refuse before it runs.** The guard gets the step's one branch
   (`Scope.git_branch`) and the worktree's HEAD branch, read at each Bash
   call. A pure table (`git_check.BRANCH_MOVES`) says which branch each git
   call moves, and HEAD is tracked across one command's calls. A call that
   moves any other branch is refused under the new rule `git-own-branch`.
   The refusal names the step's branch.
2. **Check after it ends.** At the step's start the runner records the heads
   of the branches the step could move: every local branch except the
   rebase branch and those checked out in another worktree
   (`for-each-ref … %(worktreepath)`). The record is kept on
   `StoryRebase.heads` in `state.json`, so a cut-off step keeps it. When the
   step ends, whatever its handoff, each recorded branch that moved is put
   back with a checked `update-ref`, and the step bounces a round naming
   each branch and both shas.
3. **Why branches checked out elsewhere are left out.** Git itself refuses,
   from this worktree, to move a branch that is checked out in another one,
   and `--ignore-other-worktrees` is refused. Every branch the runner moves
   during a step is checked out somewhere: story branches in their
   worktrees, and the sprint branch in the main checkout. So the record
   holds only branches that nothing but this step could move.

## Consequences

- One agent's mistake can no longer move another story's branch, the old
  story branch or a free team branch, and a slip is undone and reported.
- The guard runs one `git symbolic-ref` per Bash call, and only in story
  rebase steps.
- A branch deleted during the step isn't restored. The guard refuses the
  deletion forms, and the runner drops branches itself (`revert_story`).
- Rule for later changes: the runner must not move a local branch that is
  checked out in no worktree while a story rebase step runs. A feature that
  needs to must leave that branch out of the record, or this check will undo
  its move.
- `git checkout <other>` (which moves HEAD, not a branch) stays allowed, and
  the existing S3 check still bounces a step that ends off its branch.

## Amended by s176 design review (2026-10-25)

The first build left holes in decision 1. It read `git rebase`'s operands
with an exact list of value-taking options. git accepts long abbreviations,
and `-S` takes its key only attached, so a command could hide the branch it
rebases. `--update-refs`, a `-c rebase.updateRefs=true`, or a repo config
that turns it on moves every free branch that points into the rebased
commits. A `checkout` that fails, followed by `;`, left the tracked HEAD
wrong. What changed:

- A rebase's candidates are every operand from the `<branch>` position on,
  plus HEAD's branch. More than one distinct candidate is refused. Only
  options that git always gives a separate value skip a word, so an
  unknown option can only add a candidate, never hide one.
- `--update-refs` and any `-c` option are refused by `git-own-branch` in a
  story rebase step. The step's env pins `rebase.updateRefs=false` through
  `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0`, and the step
  may not name a `GIT_CONFIG*` variable. A later git that adds a ref-moving
  option or setting is still caught by decision 2.
- The tracked HEAD follows a `checkout`/`switch` only while it is detached
  or on the rebase branch. From another branch it stays put, because a
  failed checkout leaves it there.
- The record of heads is cleared every time the step ends and the compare
  runs, not only when a branch moved, so a held step's next round starts
  from a fresh record.
