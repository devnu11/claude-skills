# ADR-0084: Each story on its own branch, landed by a tested merge, replayed onto main

Story: s159. Design: `agile-team/docs/design/s159.md`. Amends ADR-0075,
ADR-0076, ADR-0077 and ADR-0058.

## Context

The whole team worked on one branch. A story's red tests, a half-done
implement and a reverted story all sat on the branch everyone else built on.
So pending tests were needed (ADR-0058), the sprint end rebased a branch that
mixed every story's commits (ADR-0075), and a story could not run beside
another one. The human wants each story isolated, landed only when it is
green, and visible on main as one unit. Main's history must stay readable,
and no push may ever replace history.

## Decision

1. **A branch and a worktree per story.** The first step makes
   `<story_prefix><id>` from the sprint head (`base_sha`) and a worktree at
   `.team/run/worktrees/<id>/`. The worktree is inside the repo, so it is
   gitignored and the sandbox needs no new root. Every step on the story runs
   in it, through a `Runtime` view with the worktree's config, git and
   pipeline. The run files stay in the main checkout.
2. **Landing is a runner step, and a story is done only when it has landed.**
   `land` runs after `acceptance` and no config removes it. It makes one
   `--no-ff` merge in a scratch worktree, so the story's commits keep their
   hashes and the merge has the sprint head as its first parent. It runs the
   full checks on that merge, pushes it to a throwaway landing branch, and
   waits for CI on that sha. Only green moves the sprint branch, which is
   pushed first and fast-forwarded after. Red changes nothing, so nothing is
   ever forced back.
3. **No push replaces history, and code checks it.** Every push names the sha
   it expects, taken from the runner's own record, and is refused before it
   is sent unless the new sha descends from it. Rewritten history always goes
   to a new branch (`-r<k>`): the sprint-end replay, a sprint-start replay and
   a carried story's replay. The one deletion is the landing branch, under a
   lease.
4. **The sprint end replays.** The sprint branch's first-parent line is
   replayed onto main: each story's commits are rebased, then re-merged with
   the same `merge(<id>)` message, and a plain commit is cherry-picked. main
   moves only by fast-forward to the replay branch. The remap pairs commits
   story by story.
5. **One rebase fix step.** A landing conflict and a carried story's
   conflict both become a story rebase onto the sprint head, on a new branch,
   done by DevOps when only DevOps-owned files conflict and by the developer
   otherwise. The runner checks the result as it checks a scratch rebase.
6. **Pending tests go.** A story's red tests live on its branch, which nobody
   else builds on until it lands green.

## Consequences

- A story at `land` costs CI twice (the landing branch, then the sprint
  branch at the same sha). Each open story's push costs one CI run. That is
  the price of a sprint branch that is always green.
- The human's main ruleset must allow merge commits, and must let the
  liaison push the fast-forward.
- Parallel stories can collide in shared docs (requirement ids, ADR numbers,
  the design index). These surface as landing conflicts and go through the
  rebase step.
- With no remote, no PR service or permission `no`, landing falls back to
  green full checks alone (local mode). Nothing is pushed.
- Story branches are never deleted by the runner. They pile up until the
  human prunes them.
