# Staying current with upstream, and reviewing each sprint as a pull request

The team works on its own branch (the **team branch**). At every sprint
boundary the runner does the git work itself and checks that everything
still works:

- **Sprint start**: it fetches `origin` and tells you how far `main` moved
  since the last sprint end, for example *"origin/main moved 3 commits since
  the last sprint-end rebase; nothing changes until the next sprint end"*.
  It changes nothing: no rebase, no merge, no push, no pull request. Then it
  runs the full checks on the team branch. The sprint's stories move only
  once they pass.
- **During the sprint**: nothing happens to git or to your pull requests.
  If you merge a pull request mid-sprint, the runner picks it up at the
  next sprint end.
- **Sprint end**, in this order:
  1. It builds a **review branch** for the sprint: a copy of the sprint's
     own commits on top of the latest `origin/main`, leaving out commits
     already in main. It runs the full checks on that copy and pushes it.
  2. It rebases the team branch onto `origin/main`. Commits you already
     merged (as rebased copies) drop out, so they never conflict. The
     runner updates the commit hashes it keeps in `.team/run/state.json`
     itself. It never merges, so the history stays linear. This is the only
     time the team branch is rebased.
  3. Bottom up through the stack, it brings each unmerged pull request up to
     date with main (see below), then the sprint's own one.
  4. It waits for CI on every pull request in the stack.

The **full checks** are your `[toolchain]` `lint`, `static`, `test` and the
coverage gate, then each acceptance environment's `e2e` command.

## One pull request per sprint, stacked

If you haven't merged earlier sprints yet, their pull requests form a
**stack**:

| PR | Branch | Based on | State |
|---|---|---|---|
| #12 | `team/sprint-9` | `main` | ready for review |
| #13 | `team/sprint-10` | `team/sprint-9` | ready for review |
| #14 | `team/sprint-11` | `team/sprint-10` | ready for review |

- Every pull request is ready (none is a draft). Each is based on the one
  below it, so the bases fix the merge order: merge from the bottom up,
  with **Rebase and merge**.
- The runner waits for CI on every pull request in the stack, by default up
  to 30 minutes. The team tells you the stack is **ready to merge** only
  when every check on every pull request passed.
- If CI fails, the team tells you the PR is **not** ready. You get the
  failing jobs and test lines, and the team opens a bug story that comes
  first in the next sprint. If CI is still running when the wait ends, the
  team tells you it is not ready yet and waits again.

### What happens after you merge

Say you merge #12 with **Rebase and merge**. Nothing happens until the
sprint ends. Then, at step 3 above, the runner:

1. sees #12 is merged and drops it from the stack;
2. rebases each remaining branch (`team/sprint-10`, then `team/sprint-11`)
   onto the new main, and checks that each one's files are exactly the same
   as before. Your merge only added the stack's own commits to main, so
   they are;
3. pushes each branch with `--force-with-lease` (refused if someone else
   pushed to it);
4. retargets #13 to `main` and keeps #14 on `team/sprint-10`, all ready.

No pull request is ever left based on a branch you already merged. If you
merged with squash instead, the branch has nothing left once rebased, and
the runner drops it the same way.

If a branch's files would change (main gained other commits, or a rebase
stopped on a conflict), the runner does not push the rebased copies. It
rebuilds the whole stack from the team branch on the latest main instead,
runs the full checks on it, and pushes that.

The sprint's own branch is pushed at step 1 and again at step 3 when main
moved, so its CI may run twice.

### More than 100 commits

GitHub's **Rebase and merge** refuses a pull request with more than 100
commits. When a PR in the stack has more, the team's report says so and
gives the command that merges it by fast-forward, once it is the bottom of
the stack:

```
PR #12 (team/sprint-9) has 140 commits, more than the 100 GitHub allows for "Rebase and merge". When it is the bottom of the stack, merge it by fast-forward: git fetch origin && git push origin origin/team/sprint-9:main
```

GitHub then marks the PR merged, and the next sprint end drops it as above.

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
| The PO asks you to rebase onto `origin/main` by hand ("sprint N end: rebasing …") | At sprint end, a new commit on main changes the same lines differently from the team. The runner aborted the rebase, so nothing changed. The message names the commit it stopped at and the files, grouped by directory. | `git rebase origin/main` on the team branch, resolve, `git rebase --continue`. Run `agile-team accept-checkout` if the run halted on the moved checkout, then answer. The runner rewrites its recorded hashes itself. |
| A sprint start says "origin/main moved N commits since the last sprint-end rebase" | You (or someone) merged into main since the last sprint end. | Nothing. The team branch and the pull requests stay as they are until the next sprint end. If you want main pulled in sooner, pull it into the team branch yourself. |
| The dashboard shows a `boundary` row "rebuild" with a note such as "team/sprint-10 rebased onto origin/main has a different tree" | At sprint end, bringing a pull request up to date would have changed its files, or a rebase stopped. Nothing was pushed. | Nothing. The runner rebuilds the whole stack on main, checks it, and pushes it. |
| The dashboard shows a `boundary` row "check: fail" and a devops step follows | A check failed on the team branch at sprint start or on a review branch at sprint end. DevOps fixes it on the team branch. | Nothing. The runner checks again after the fix. |
| "failed the same way again … the manager reviewed it" | The same failure came back after a fix. | The PO asks you what to do. |
| "CI failed on #12 … NOT ready" with failing test lines | The PR's CI checks failed (for example, a test passes only on your machine). | Don't merge it. The team's bug story fixes it next sprint, and a later sprint end reports it ready. |
| "No CI result exists" | Nothing was pushed (you said no, or `gh` is missing), or the PR reported no checks. | Nothing is called ready. Check the branch yourself before you merge. |
| The sprint-end note says "skipped: no remote 'origin'" | The repo has no upstream, or `gh` is missing. | Nothing. The team works as before. Add a remote (and log in to `gh`) to get pull requests. |

## Configuration

Defaults suit most repos. To change them, add to `.agile-team.toml`:

```toml
[upstream]
remote = "origin"        # "" turns sync and pull requests off
branch = "main"          # what the team rebases onto at sprint end and what PRs target
prefix = "team/sprint-"  # review branch names: <prefix><sprint>

[gates]
ci_timeout_s = 1800      # how long a sprint end waits for the stack's CI checks

[[environment]]
name = "cli"
kind = "package"
e2e = "uv run pytest -q tests/e2e"   # this environment's e2e suite, run with the full checks
```

## Where to look

- The dashboard's **Board** tab has a **Review stack** card. It shows each
  sprint's branch, PR number, draft or ready, and the check result, and
  what the runner is doing at a boundary right now.
- `agile-team status` includes `boundary` and `upstream` (the stack).
- The review worktree is `.team/run/review/`. It is scratch, and the runner
  recreates it at every rebuild.
