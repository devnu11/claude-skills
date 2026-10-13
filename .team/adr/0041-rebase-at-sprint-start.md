# ADR-0041: Rebase the team branch at sprint start

**Decision:** ~~The sprint-start sync~~ **The sprint-end boundary** rebases the team branch onto the target branch (origin/main) instead of merging, dropping commits whose patches are already upstream. Hash rewrites keep the runner's recorded hashes consistent; no commits are lost.

**Amendment (s108):** The rebase moved from sprint start to sprint end, after the sprint's own branch is pushed and before the review stack is brought up to date. The start sync now only reports whether the target moved and changes nothing. Reason: the human's rule (t58, m118 option b) pulls main into the team branch once per sprint at a point where the stack is updated in the same pass, so a mid-sprint or start merge never rewrites hashes the sprint is working on. R1–R11 below still apply to the END rebase; R12 is reversed.

**Date:** 2026-10-12  
**Status:** Accepted (amended s108)  
**Affected:** Runner git model; sprint boundaries; state tracking; review stack (moved to sprint end)

## Context

At sprint 18 (m54), rebasing the team branch's commits onto origin/main produced ~100 false conflicts. Main receives each sprint's work as rebased copies ("Rebase and merge" on GitHub). The team branch still held the original commits, and later commits editing the same lines. A merge would conflict on those lines even though there was no real overlap.

A rebase drops commits whose patches are already upstream. The false conflicts disappear. Hashes only matter within a sprint; at the boundary the branch is about to be rebased for the push anyway, so rewriting recorded hashes is safe.

## Decision

### Rules (R1–R12)

**R1: Rebase, never merge.** The start-edge sync calls `git -c rebase.updateRefs=false -c rebase.rebaseMerges=false rebase --no-verify --no-autostash --no-autosquash --empty=drop <target>`. No `merge`, `-s ours`, or `-X ours` anywhere. Merge commits and empty commits are dropped; the result is linear. (Consequence: AC1, AC5)

**R2: Stable sync point.** `Boundary.sync_from` stores the HEAD before the rebase. On the first run of the sync stage, it is pinned to `git.head()` and `runtime.save()` is called **before** `rebase_onto`. On resume or rerun, the same `sync_from` is passed to rebase. This guards against a crash between the rebase and R6's save losing the old hash map. (AC2, AC3)

**R3: Outcomes.** `rebase_onto` returns a `Rebase` with outcome `current` (HEAD unchanged), `rebased` (new HEAD, moved hashes), or `conflict` (git stopped, files listed). Non-zero exit with no conflicts raises `GitError`. (AC1, AC3)

**R4: Conflict safety.** On conflict, the branch is read (files, `git rev-parse REBASE_HEAD`, commit subject), then `git rebase --abort` is run. HEAD is byte-equal to before the command; no rebase is in progress. The boundary holds `sync_conflict` with files, commit and subject. (AC3)

**R5: Pairing.** Old-to-new commit mapping uses `git log --format=STAMP_FORMAT` on both ranges (before and after rebase). Each old commit's stamp (author, date, message) is matched against new commits oldest first. Matched commits advance the cursor; dropped commits map to the last matched copy or to the rebase base if none yet. (AC2)

**R6: Rewrite.** `rewrite.remap_state` replaces recorded team-branch hashes in `REMAPPED` fields (story commits, code commits, interrupted shas, stack entries). Other fields (`checked`, `head`, `pushed`, `base`) are left alone. After rewrite, `record_checkout()` and `runtime.save()` run at once. (AC2)

**R7: Lost content.** Before pairing, the sync checks whether any path changed content without touching. A path is lost if the team's version changed but upstream didn't, or vice versa. If lost, the branch is reset to the pre-rebase state and `UpstreamError` is raised. (AC2)

**R8: Empty stack entries.** After a rebased outcome, empty entries (start == end after rewrite) are dropped with `MERGED_NOTE`. (AC1, AC2)

**R9: Event tone.** `BoundaryOutcome.REBASED` is a new outcome. The `rebased` event carries `sha` (new HEAD) and `rewritten` (count of hash changes). The dashboard tone for `rebased` is `"good"`. (AC3)

**R10: Conflict grouping.** `sync_conflict` hand-over groups conflicting files by parent directory, counts them, and lists directories sorted with filenames sorted within. (AC3)

**R11: Push unchanged.** `push` keeps `--force-with-lease=<ref>:<expect>` and `_guard` refuses anything but review branches (never team branch, never target branch). (AC4)

**R12: End edge rebases (reversed by s108).** Only `Edge.END` maps to the rebase method at the REBASE stage, after PUSH and before RESTACK. The start sync no longer rebases; it only fetches and reports. (AC1, s108)

### Implementation

**New module `agile_team/rewrite.py`:** Pure functions for pairing old to new commits (by stamp: author, date, message) and rewriting hashes in `state.json`. Imports `RunState` under `TYPE_CHECKING` only to avoid circular imports.

**`agile_team/upstream.py`:** Replaced `merge_in` with `rebase_onto`. New `SyncOutcome` enum and `Rebase` dataclass. `listing(span)` runs git log with the stamp format. `_check_kept(spans)` validates that no content is lost. On conflict, `_failed_rebase` reads conflict data then aborts.

**`agile_team/boundary.py`:** Added `sync_from: str = ""` field. New outcome `BoundaryOutcome.REBASED`.

**`agile_team/boundary_runner.py`:** Replaced `_merge_in` with `_rebase(b)`. Guard clause `_pin_sync_from(b)` sets `sync_from` once and saves before the rebase. Dispatch table `AFTER_REBASE` handles conflict, current, rebased outcomes. `_settle_rebase` runs remap → record_checkout → save → drop merged → emit event.

**`agile_team/handover.py`:** Added `file_count` and `file_groups` to `sync_conflict`. New `group_files` utility groups paths by directory.

**Dashboard:** Tone map includes `rebased: "good"`. Fixture e93 (end-edge sync) is `outcome: pass` (not `rebased`).

**Docs:** Updated `agile-team/SKILL.md`, `agile-team/reference/protocol.md`, `agile-team/docs/customer/review-stack.md`. ADR-005 decision 1 ("merge in, never rewrite") is superseded.

## Consequences

**Sprint boundary is faster and silent.** Rebasing drops commits already on main, so the false conflicts of sprint 18 cannot happen. The sync is idempotent: rerunning it after a successful rebase is a no-op.

**Hashes are stable within a sprint.** The `sync_from` pinning means the runner can record the old hashes before the rebase, then remap them after. Any crash between steps leaves the mapping in place.

**Conflicts are rare and explicit.** A real conflict (same lines changed differently) aborts the rebase and leaves the branch clean. The human rebases by hand and continues; the runner remaps from `sync_from` as if the command had run.

**No hand-merge tooling needed.** The old `-s ours` and `-X ours` strategies are gone. The runner never merges and never hides conflicts under a blanket strategy.

**E2E tests are needed.** The real-git test cases (all commits upstream, copies plus new content, a real conflict, hash rewrite, hand rebase after conflict) are in the integration-tester's e2e step, not unit tests.

## Related decisions

- **ADR-0015 (s29):** Boundary steps (sync, push, review). This decision replaces the sync's merge with a rebase.
- **ADR-0005:** Consistent HTML escaping. This decision drops decision 1 ("merge in, never rewrite").
- **ADR-0029 (s62):** Liaison `continue_boundary` tool allows the human to resume after a conflict.
- **ADR-0028 (s61):** Checkout guard prevents external changes. The sync may change the branch, triggering the guard on resume.
