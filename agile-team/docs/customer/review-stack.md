# Staying current with upstream, and reviewing each sprint as a pull request

The team works on its own branch (the **team branch**). It never rewrites
that branch. At every sprint boundary the runner does the git work itself
and checks that everything still works:

- **Sprint start**: it fetches `origin` and merges `origin/main` into the
  team branch. If nothing is new, no commit is made. Then it runs the full
  checks. The sprint's stories move only once they pass.
- **Sprint end**: it builds a **review branch** for the sprint. This is a
  copy of the sprint's own commits on top of the latest `origin/main`.
  Commits already in main are left out. It runs the full checks on that
  copy, then pushes it and opens a pull request.

The **full checks** are your `[toolchain]` `lint`, `static`, `test` and the
coverage gate, then each delivery's `e2e` command.

## One pull request per sprint, stacked

If you haven't merged earlier sprints yet, their pull requests form a
**stack**:

| PR | Branch | Based on | State |
|---|---|---|---|
| #12 | `team/sprint-9` | `main` | ready for review |
| #13 | `team/sprint-10` | `team/sprint-9` | draft |
| #14 | `team/sprint-11` | `team/sprint-10` | draft |

- Review and merge the **ready** one (the bottom). Use **Rebase and
  merge**.
- The others are drafts. CI skips drafts, so CI runs once per merge however
  deep the stack is.
- At the next sprint boundary, the runner sees that #12's changes are in
  main and drops it. It rebuilds the rest of the stack on the new main,
  checks the new bottom, retargets #13 to `main` and marks it ready.
- At every sprint end, the whole unmerged stack is rebuilt on the latest
  main once, the bottom and newest branches are checked, and every branch
  is pushed again.

## Permission to push

The first time a push is needed, the team asks you once: *may the team push
review branches and open or update pull requests?* Your answer is kept for
every later sprint.

- **Yes**: the runner pushes only `team/sprint-<N>` branches. It never
  pushes the team branch or `main`. If someone else pushed to a review
  branch, the push is refused and you are told.
- **No**: the branches are built and checked on your machine only, and the
  team tells you their names. You can push them yourself.

## When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| The PO asks you to merge `origin/main` by hand | Merging upstream into the team branch conflicts. The runner aborted the merge, so nothing changed. | Merge `origin/main` into the team branch, resolve, commit, then answer. |
| The dashboard shows a `boundary` row "check: fail" and a devops step follows | A check failed after the sync or on a review branch. DevOps fixes it on the team branch. | Nothing. The runner checks again after the fix. |
| "failed the same way again … the manager reviewed it" | The same failure came back after a fix. | The PO asks you what to do. |
| The sprint-end note says "skipped: no remote 'origin'" | The repo has no upstream, or `gh` is missing. | Nothing. The team works as before. Add a remote (and log in to `gh`) to get pull requests. |

## Configuration

Defaults suit most repos. To change them, add to `.agile-team.toml`:

```toml
[upstream]
remote = "origin"        # "" turns sync and pull requests off
branch = "main"          # what the team merges in and what PRs target
prefix = "team/sprint-"  # review branch names: <prefix><sprint>

[[delivery]]
name = "cli"
kind = "package"
e2e = "uv run pytest -q tests/e2e"   # this delivery's e2e suite, run with the full checks
```

## Where to look

- The dashboard's **Board** tab has a **Review stack** card. It shows each
  sprint's branch, PR number, draft or ready, and the check result, and
  what the runner is doing at a boundary right now.
- `agile-team status` includes `boundary` and `upstream` (the stack).
- The review worktree is `.team/run/review/`. It is scratch, and the runner
  recreates it at every rebuild.
