# ADR-0092: The runner's own commits are carried over a green landing

Story: s180. Design: `agile-team/docs/design/s180.md`. Amends ADR-0084's s163
rule "a landing never pushes a stale merge".

## Context

s163 (ADR-0084, amended) made a pushed landing resume, and a green one move
the sprint branch, only while its merge's first parent is still the sprint
head. Otherwise the landing gives up its merge and merges, checks and runs
CI again. The rule didn't foresee the runner's own commits. The runner keeps
committing on the main checkout while a landing waits: story files (`story
new`/`amend`), shares, revert and pass records, storyless steps and PO
settles. Each one moves the sprint head (`record_checkout` →
`_follow_sprint_head`), so every waiting landing is dropped. In sprint 51
this cost s165 a full round, twice in one day.

Two fixes were open:

1. **Defer the runner's commits** while a landing is in flight. The commits
   come from at least six places, some inside a PO tool call or a step that
   owns the checkout. Each would need its own wait, a CI wait can last
   `ci_timeout_s`, and a held landing would stall story intake for hours.
2. **Carry the commits over the merge.** At green, cherry-pick the commits
   that moved the head onto the merge, so the merge lands at its own sha and
   they follow it. One place changes (the lander), and every source of
   commits is covered at once. The carried commits get new shas.

## Decision

Carry (option 2), with three guards.

1. **What is carried.** At green, under the main lock, the lander reads the
   move: the merge's first parent `B`, the sprint head `H`, the remote record
   `pushed` and every story's branch base. The move is carried only when
   `H` descends from `B`, `B..H` isn't empty and holds no merge commit (no
   other landing or revert landing), `pushed` is an ancestor of the merge
   (nothing moved is on the remote yet), and no story's `base_sha` or queued
   rebase `onto` is in `B..H`. Anything else is dropped as before.
2. **How.** In `.team/run/land`, detached at the merge, the lander runs
   `git cherry-pick --allow-empty --keep-redundant-commits B..H`. A conflict
   aborts it and the landing is dropped. The commits keep their authors,
   dates, messages and trailers, one copy per commit.
3. **What moves.** The sprint branch on the remote moves to the merge only,
   the CI-green commit, as before. The main checkout moves from `H` to the
   last copy with `reset --keep` (`Upstream.reset_team_branch`), which
   refuses if HEAD isn't `H`. The copies stay unpushed until the next
   landing or the sprint end pushes them, which is where they were before.
   `rewrite.remap_state` rewrites the run's recorded shas. `story-landed`
   gains `carried` (old sha → new sha).
4. **No fork on a moved commit.** While a landing holds a merge whose first
   parent isn't the sprint head (`RunFlags.landing_base`; see the round-2
   amendment below for the saved `Landed.base`), a story with no worktree
   isn't offered. A branch forked on a moved commit would keep the
   old copies, so the carry would have to refuse.
5. **A drop says why.** `landing-dropped` gains `moved` (every commit of
   `B..H` as `<short sha> <subject>`) and `not_carried` (the guard that
   refused). The land report carries the drops, and a new story-scoped
   hand-over `landing_dropped` shows them to the PO.

## Consequences

- A waiting landing survives the runner's bookkeeping. CI runs once per
  landing, not once per bookkeeping commit.
- A carried commit's sha changes once. The sha printed in its event (`story
  opened`, `story amended`, a step's `commit`) and in a liaison note names
  the old copy. `story-landed`'s `carried` maps it to the new one, and
  `state.json` is remapped. The old commit stays in the object store
  (reflog), so a quarantine sha in an old note still works with
  `git cherry-pick -n`.
- A carried commit isn't CI-checked on its own when it is carried. It never
  was: before s180 it rode, unchecked, under the next landing's merge. That
  merge's CI and the sprint end's as-built CI still check it.
- A story that would start during such a window starts after the landing
  ends. The wait happens only when the head moved during the landing.
- The guard on `reset --keep` is the s163 halt: if something moves HEAD
  between the carry and the move, the run halts as checkout drift, as a
  failed fast-forward does today.
- Lands, revert landings included, still run one at a time, so one
  `landing_base` is enough.

## Amended by s180, design round 2 (2026-10-23)

Guard 4 used only `RunFlags.landing_base`, which lives in memory and is
cleared when `land` returns. A land that returns on a CI hold, or a restart,
left a pushed merge waiting with no hold. A story could then fork on the
moved head, and the landing dropped with `FORKED`, which is the incident s180
is about (review F1).

What changed:

- `Landed` gains `base`, the merge's first parent, saved at the landing
  push. The router holds while any story at `land` keeps a pushed merge
  whose `base` isn't the sprint head, or while the in-memory flag (the
  merge being made and checked) is below it. A pre-s180 record has no
  `base` and holds nothing until its resume fills it in.
- The hold applies to a story with no `branch` (it would fork), not to one
  with no worktree. A story with a branch never forks again.
- The stall hand-over names the landing that holds a story.

New consequence: a landing held on CI below a moved head keeps new stories
from starting until it lands, drops or bounces. That can take hours. The
stuck-Sprint-Backlog hand-over names the landing, so the PO and the liaison
see what to release. Forking such a story on the merge's base instead was
rejected: the branch would miss the story-file commit that opened it and
any storyless config commit.
