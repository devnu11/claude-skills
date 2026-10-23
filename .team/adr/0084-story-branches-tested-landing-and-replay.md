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

## Amended by s163 (2026-10-19)

The sprint-49 review found that a held landing could resume and push a merge
made on an older sprint head, which halted the run as drift, and that the
switch-over refused a sprint that main had taken by rebase. Design:
`agile-team/docs/design/s163.md`.

- **The landing order** (decision 2) is now ADR-0088's: the PO's order, then
  smallest first, with reverts in the same queue.
- **A landing never pushes a stale merge.** A pushed landing resumes only
  while its merge's first parent is still the sprint head. Otherwise, and
  after any refused sprint push, it gives up the merge (its record is
  cleared and the landing branch deleted) and merges afresh when its turn
  comes. A refused push lands again when the remote descends from the
  runner's `pushed` record. It halts as drift only when the remote doesn't,
  or when the main checkout can't fast-forward to it.
- **Records match the remote.** `pushed` is set right after a successful
  sprint push, before the checkout moves. After a followed remote, `head`
  and `pushed` both equal the remote head.
- **The stack keeps only what main lacks.** Every `start_sprint` drops stack
  entries whose head main contains, or whose commits main has as
  patch-equivalent copies (`git cherry`). The one-time switch counts "ahead"
  with the same `git cherry` rule, so no hand edit of the state is needed.

Known limits, ruled on at s163's design review (2026-10-19). The runner
can't tell a lease refusal from other push failures, because `push()` turns
every `UpstreamError` into refusal text:

- A sprint push refused for another reason (branch protection, auth, the
  network) while the remote still equals `pushed` counts as "descends" and
  re-lands. Up to `MAX_RESTARTS` attempts each merge, check and wait for
  landing CI again, then the landing holds with "the sprint branch kept
  moving", which doesn't say what really failed. Before s163 such a refusal
  halted at once. The cost is bounded, and the run doesn't halt.
- A push that reports a refusal but reached the remote (`R == merge`) is
  followed, so the story then merges a branch the sprint head already has.
  It is the same bounded loop, ending in a hold with the story not marked
  landed.

A follow-up could hold at once, with the refusal text, when the remote
didn't move, and count `R == merge` as a landed push. That narrows AC3's
"re-lands when the remote descends", so it needs a new story.

## Amended by s166 (2026-10-20)

A story PR's base is the sprint branch, so the landing's sprint push makes
GitHub mark the story PR merged. The landing's `gh pr close` then failed with
"already merged", and the run halted after a green landing (sprint 50).
Design: `agile-team/docs/design/s166.md`.

- **A merged PR counts as closed.** `GhPrs.close` runs `gh pr close` as
  before. Only when that fails does it read the PR's state, and `MERGED` is
  success. Any other failure raises as before. The rule is in the one `Prs`
  implementation, so the landing, the superseded story PR and the
  superseded sprint PR all share it.
- **The state decides, not the text.** The live hotfix matched gh's message.
  Reading the state survives a change in gh's wording. Reading it after the
  failure, not before, costs no extra call on the normal path and doesn't
  race GitHub marking the PR merged.
- **Consequence.** A landed story's PR usually ends merged, with no landed
  note: gh refuses a merged PR before it comments. The landing's own record
  and the `story-landed` event still say where it landed.

## Amended by s179 (2026-10-23)

Each mid-sprint restart (sprint 51) removed the worktree of every story
without a step in flight, because s159's I3 called those "stale". With a
worktree per open story, they are not: each one held a synced venv in
ignored files, and five parallel stories cost five rebuilds per restart.
Design: `agile-team/docs/design/s179.md`.

- **A resume keeps every open sprint story's worktree** (decision 1). It
  removes a story worktree only when the story is done, cancelled, out of
  the sprint or unknown, and never while a step is in flight; and `land`
  and `replay` unless a boundary replay is pinned.
- **Each removal is a `worktree-pruned` event** with the worktree's name and
  the reason, and a removed story's `worktree_head` is cleared.
- **The resume judges no drift.** A kept worktree that moved is held at its
  story's next step by the existing drift check, so a restart never throws
  away work the human might want to keep.
- **Consequence.** Worktrees of open stories outlive restarts, so disk use
  between sprint boundaries grows with the open stories, bounded by
  `max_open_stories`.

