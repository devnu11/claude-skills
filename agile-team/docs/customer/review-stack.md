# Staying current with upstream, and reviewing each sprint as a pull request

The team works on its own branch (the **team branch**). At every sprint
boundary the runner does the git work itself and checks that everything
still works:

- **Sprint start**: it fetches `origin` and rebases the team branch onto
  `main` once more, because the team may have been stopped while you
  merged something. A branch already on `main` is left alone. Every commit
  hash the runner recorded is rewritten, as at the sprint end. If the
  rebase conflicts, the runner aborts it, leaves the team branch as it
  was, tells you, and the sprint goes on; rebase the team branch by hand
  when you can, since until then the sprint's pull request conflicts with
  `main` and gets no CI. There is no push and no pull request at the
  start. Then it runs the full checks on the team branch. A failure
  doesn't hold the sprint: the failing tests are recorded as the sprint's
  **known failures**, the Product Owner asks the liaison for a story for
  them, and the liaison writes it and puts it at the top of this sprint or
  later.
- **During the sprint**: nothing happens to your pull requests, and nothing
  is merged or rebased into the team branch. If you merge a pull request
  mid-sprint, the runner brings it in at the next sprint end, or at the
  next start if the team stopped in between. If the team
  needs a change sooner (a test fix, a rule, a commit from an open pull
  request), fetch it and run `agile-team pick <commit-or-A..B> --reason
  "<why>"`. The Product Owner accepts or denies it. To skip the Product
  Owner, add `--force` and type the first commit's sha when asked. Between
  steps the runner cherry-picks each commit onto the team branch as its own
  new commit, and it rewrites no hash. A conflict in any commit changes
  nothing. Picks and their reverts stay in the sprint's history and are
  pushed with it. If main already has a picked change, the sprint-end rebase
  drops the copy, as it does for any commit.
- **Sprint end**, in this order:
  1. It runs the full checks on the team branch.
  2. It pushes the team branch **as it is** (exactly what the team built
     and tested) to the sprint's branch `team/sprint-<N>`, and opens that
     sprint's pull request onto `main`, or reuses it.
  3. It waits for that push's CI. **Green is a gate**: nothing is rebased
     before it. If CI fails, the boundary holds, and you get the failing
     checks.
  4. Once CI is green, it rebases the team branch onto `origin/main`.
     Commits you already merged drop out, so they never conflict. The
     runner updates the commit hashes it keeps in `.team/run/state.json`
     itself. It never merges, so the history stays linear. This is the
     only time the team branch is rebased. If the rebase stops on a
     conflict, the runner aborts it and hands it to DevOps, which resolves
     it in a scratch worktree (`.team/run/rebase`, branch
     `agile-team/rebase-sprint-<N>`) without merging or squashing. The
     runner checks the result, runs the full checks there, and only then
     moves the team branch to it. If DevOps can't settle it, the boundary
     holds, and you get the conflict, DevOps's notes and the scratch
     branch to look at.
  5. It force-pushes the rebased branch to the same `team/sprint-<N>`. The
     pull request updates, and its history keeps the first push: GitHub's
     "force-pushed" line has a **Compare** link that shows exactly what the
     rebase changed. If main hadn't moved, the rebase changes nothing and
     there is no second push.
  6. It waits for CI again and records the result. A red result here is
     reported to you, but it doesn't hold the team.

The **full checks** are your `[toolchain]` `lint`, `static`, `test` and the
coverage gate, then each acceptance environment's `e2e` command.

## One pull request per sprint, based on main

Each sprint has one pull request, from `team/sprint-<N>` to `main`. It
holds the whole team branch, so when an earlier sprint's pull request is
still open, the new one holds its commits too:

| PR | Branch | Based on | Holds |
|---|---|---|---|
| #12 | `team/sprint-9` | `main` | sprint 9 |
| #13 | `team/sprint-10` | `main` | sprints 9 and 10 |

- The newest pull request names the earlier ones it holds. Merging it
  merges them too, so close them once it is merged. The runner never
  closes a pull request, and it stops watching the earlier ones.
- Merge with **Rebase and merge**.
- The team tells you a pull request is **ready to merge** only when every
  check passed on its current head, that is, after the rebase.
- If CI fails on the first push, the team tells you the PR is **not**
  ready. You get the failing jobs and test lines, the team opens a bug
  story that comes first in the next sprint, and the team branch is not
  rebased this time. If CI is still running when the wait ends, the team
  tells you it is not ready yet and waits again.
- If CI fails only after the rebase, the sprint still ends. The team tells
  you the PR is **not** ready, with the failing checks: the rebase onto
  your newer main is what broke it.

### More than 100 commits

GitHub's **Rebase and merge** refuses a pull request with more than 100
commits. When the PR has more, the team's report says so and gives the
command that merges it by fast-forward:

```
PR #12 (team/sprint-9) has 140 commits, more than the 100 GitHub allows for "Rebase and merge". Merge it by fast-forward: git fetch origin && git push origin origin/team/sprint-9:main
```

GitHub then marks the PR merged.

## Permission to push

The first time a push is needed, the team asks you once: *may the team push
the sprint's branch and open or update its pull request?* Your answer is
kept for every later sprint.

- **Yes**: the runner pushes only `team/sprint-<N>` branches. It never
  pushes the team branch or `main`. If someone else pushed to a sprint
  branch, the push is refused and you are told.
- **No**: nothing is pushed, and the team tells you the branch name. With
  no CI result there is no green, so the team branch is not rebased at the
  sprint end.

## When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| The PO asks you to rebase onto `origin/main` by hand ("sprint N end: rebasing …") | After green CI, a new commit on main changes the same lines differently from the team. The runner aborted the rebase, so nothing changed. The message names the commit it stopped at and the files, grouped by directory. | `git rebase origin/main` on the team branch, resolve, `git rebase --continue`. Run `agile-team accept-checkout` if the run halted on the moved checkout, then answer. The runner rewrites its recorded hashes itself. |
| A sprint start says "origin/main moved N commits since the last sprint-end rebase" | You (or someone) merged into main since the last sprint end. | Nothing. The team branch and the pull request stay as they are until the next sprint end. |
| "CI failed on the team branch as built … nothing is rebased" | The team's own branch failed CI. | Don't merge it. The team's bug story fixes it next sprint, and a later sprint end reports it ready. |
| "green on the team branch as built … and is red on it rebased onto origin/main" | The team's branch passed, but rebasing it onto your newer main broke something. | Don't merge it. The compare link in the PR shows what the rebase changed. The PO asks for a bug story. |
| "No CI result exists" and "not rebased" | Nothing was pushed (you said no, or `gh` is missing), or the PR reported no checks. GitHub runs no pull-request CI on a PR that conflicts with `main`. | Nothing is called ready. Check the branch yourself before you merge. If the PR conflicts with main, rebase the team branch by hand. |
| The dashboard shows a `boundary` row "refused" | Something asked for the rebase before green CI. The runner refused and changed nothing. | Nothing. The runner waits for CI again. |
| The dashboard shows a `boundary` row "check: fail" and a devops step follows | A full check failed on the team branch. DevOps fixes it there. | Nothing. The runner checks again after the fix. |
| "failed the same way again … the manager reviewed it" | The same failure came back after a fix. | The PO asks you what to do. |
| The sprint-end note says "skipped: no remote 'origin'" | The repo has no upstream, or `gh` is missing. | Nothing. The team works as before. Add a remote (and log in to `gh`) to get pull requests. |

## Configuration

Defaults suit most repos. To change them, add to `.agile-team.toml`:

```toml
[upstream]
remote = "origin"        # "" turns sync and pull requests off
branch = "main"          # what the team rebases onto at sprint end and what PRs target
prefix = "team/sprint-"  # sprint branch names: <prefix><sprint>

[gates]
ci_timeout_s = 1800      # how long each sprint-end CI wait lasts

[[environment]]
name = "cli"
kind = "package"
e2e = "uv run pytest -q tests/e2e"   # this environment's e2e suite, run with the full checks
```

## Where to look

- The dashboard's **Board** tab has a **Sprint PR** card. It shows the
  sprint's branch, PR number, draft or ready, and the CI result of its
  current head, and what the runner is doing at a boundary right now.
- `agile-team status` includes `boundary` and `upstream` (the sprint's
  entry, with `as_is`, the sha of the first push).
- Runs before s151 built review branches in `.team/run/review/`. That
  folder is no longer used, and you can delete it.
