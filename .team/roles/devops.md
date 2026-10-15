<!--
devops: your instructions for this role (repo layer).

Write plain Markdown below this comment; it is appended to the role's
built-in prompt. Layers apply in order: built-in, then global
(~/.config/agile-team/roles/, or $AGILE_TEAM_HOME/roles/), then this repo
(.team/roles/). To replace the role entirely, start the file with YAML
frontmatter (---) instead. _shared.md applies to every role.
This comment is ignored.

Role: Owns CI, build files, toolchain commands and the delivery prepare steps.
-->

## Boundary fixes (this repo)

- **The sprint-end rebase stopped on a conflict**: you own it. The
  sprint end runs in this order: push the team branch as it is to the
  sprint's PR, wait for its CI to be green, rebase the team branch onto
  main, push it again to the same PR. When that rebase conflicts, the
  runner aborts it (the team branch is unchanged) and stops the same
  rebase in a scratch worktree on a scratch branch, both named in your
  brief. Resolve it there with `git -C <worktree> …`: edit only the
  conflicting files, keep both sides' intent, `git add`, `git rebase
  --continue`, until it is done. Never merge, squash, reorder, reword,
  skip or drop a commit; keep a commit that became empty with `git
  commit --allow-empty -C REBASE_HEAD`. Run named tests there. The
  runner then checks the result, runs the full checks in the worktree
  and moves the team branch to it. If you cannot resolve it, hand off
  `failed` with notes the human can act on; the PO and the liaison get
  them with the scratch branch's name.
