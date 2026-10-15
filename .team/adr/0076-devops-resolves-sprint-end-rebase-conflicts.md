# ADR-0076: DevOps resolves a sprint-end rebase conflict in a scratch worktree

**Date:** 2026-10-15 (s151 design, q3 amendment)
**Status:** Accepted
**Amends:** ADR-0041 (end rebase: a conflict held `sync_conflict` for the human), ADR-0075

## Context

Since s59 a conflict in the sprint-end rebase aborted it and held the
boundary (`sync_conflict`) until the human rebased the team branch by hand.
The human asked (s151 AC6) that DevOps resolve it instead, out of the team's
checkout, with the full checks, never merging or squashing, and that only a
failure reaches the PO and the liaison.

## Decision

1. **Conflict → DevOps step.** The aborted rebase leaves the team branch as
   it was. The runner makes a git worktree at `<run_dir>/rebase` on the
   scratch branch `agile-team/rebase-sprint-<N>`, starts the same rebase
   there (`--empty=keep`, no autosquash, no merges) and runs a new step
   kind, `rebase-fix`, for `devops`. The brief names the stopping commit,
   its files, the worktree and the branch.
2. **Confinement in code.** The step may write only the worktree, and git
   may change only the worktree (G6 `WORKSPACE`); the team repo stays
   read-only. `GIT_EDITOR=true` is set for it.
3. **The runner judges the result, not the role.** At the `rebase` stage
   the runner refuses DevOps's branch unless: the step ended `done`; the
   rebase is finished and the worktree clean and on its branch; the branch
   sits on the target with no merge commit; its commit stamps equal the
   team branch's minus the commits already upstream (so no commit was
   added, dropped, squashed, reordered or reworded); no path only one side
   touched changed; and the full checks pass, run by the runner in the
   worktree. Then it resets the team branch to the result (`reset --keep`,
   only if the team HEAD has not moved), remaps the hashes as for a clean
   rebase and goes on to `push-rebased`.
4. **Failure holds.** Any refusal holds `rebase_conflict`; the PO (handover)
   and the liaison get the conflict, the reason, DevOps's notes and the
   scratch branch, which is kept. `continue_boundary` starts a fresh
   attempt. `sync_conflict` is no longer emitted; it stays loadable.

## Consequences

- A conflict no longer needs the human unless DevOps fails.
- A commit that became empty while resolving is kept as an empty commit,
  unlike a clean rebase, which drops it. That keeps the "no commit lost"
  check exact.
- DevOps cannot fix a semantic conflict in a file only one side touched;
  that is refused and reaches the human. This keeps a resolution to the
  conflicting files.
- The `rebase` stage can now run the full checks once more (in the
  worktree), so a conflicting sprint end takes longer.
- The worktree lives under `.team/run/`, which git and the step audit
  ignore; it is a separate checkout, so the team's working tree, index and
  branch are never touched.

## Amended by s153 (2026-10-15)

The decision lands in two slices (Manager ruling on s151). s153 adds the
pieces with no change in behaviour: `Upstream.upstreamed`, `lost_paths` for
any head, `adopt`, `ScratchRebase`, the boundary's data (`rebase-fix`,
`rebase_conflict`, `RebaseFix`, `Failure.worktree`), the state loader and
the DevOps step's scope. Until s151's implement step wires them, a
sprint-end conflict still holds `sync_conflict` and no `rebase-fix` step is
ever due, so a build between the two slices is safe to ship. The real-git
tests of the pieces are e2e tests, because unit tests run in the fake world.

## Amended by s153, round-2 review (2026-10-15)

s151's slice-2 unit tests stay in the tree while s153 runs (Manager and PO
rulings), and they belong to s151, not s153. The registry is runner-only.
A red test joins a story's pending ids only at that story's own tests gate,
and only if the step touched the test's lines. So one s151 tests step runs
during s153 and registers them. That step changes no assertion. It moves the
`sync_conflict` handover case out of the shared `BOUNDARY_ROWS` constant
into a test of its own, and adds `Pins s151/AC6.N (slice 2).` to each
other red test's docstring. Because the pending tests were registered in
the wrong order once, a split story whose later slice's tests are
already in the tree must have that slice's tests step run before the
earlier slice's gates. See design/s153.md (P7, Step order 5 and 6).
