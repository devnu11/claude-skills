# ADR-0017: Save interrupted steps in a reverted commit, not a stash

**Date:** 2026-10-11 (s9 done)  
**Status:** Accepted  
**Relates to:** ADR-0007 (clean halt on limits), s8 (SIGTERM and limit handling), s19 (routing in code)

## Context

**Problem from s8:** When a role step is cut off by an error, limit, SIGTERM, or kill signal, its uncommitted edits are left in the tree. On resume, `start --resume` refuses the dirty tree, and the next step on the story starts from scratch. The human had to stash edits by hand, and `status` still reported `running` with no process behind it.

**Human's decision (m3):** Keep the edits, either as a commit (easier for roles to reuse via `git cherry-pick -n`) or as a stash (requires `git stash` which roles are not allowed to run). Roles' Bash may only run `git cherry-pick -n`, not `git stash`, so a commit is the better choice.

**Constraint from s8:** Halts happen at multiple points (role step error, limit in role step, SIGTERM/crash at top level). Each halt must be handled the same way: capture the edits, save them, mark the status clearly.

## Decision

### 1. Save edits in a commit that is reverted at once (I3, AC2)

When a step is interrupted, the runner commits every changed path (in scope or not) with the message `chore(team): interrupted step by <label>`, then reverts that commit. The tree is clean, HEAD has moved by two commits, and the sha points to the edits. No `QUARANTINE` event is emitted. Roles can reuse the edits with `git cherry-pick -n <sha>` on resume.

**Consequence:** Edits are reachable by sha (not dropped by stash garbage collection), roles can reuse them via a tool they already know (cherry-pick), and the flow is the same whether the interruption was in the runner or caused by an external kill.

### 2. Track in-flight steps and clearance (I1, I2, AC1)

`state.in_flight` records the role, story id (or None for PO's own turn), and brief of the step being run. On step start, it is set; on settlement, it is cleared. If interrupted, the next resume can tell what was cut off.

**Consequence:** After a crash or kill, `state.json` says which step was in flight. The resume prompt can name it. On a clean settlement, the field is always `None`.

### 3. Distinguish interrupted status from running (I13, AC5)

`status` never reports `running` with a dead process. When `state.status = RUNNING` but the pid is stale or dead, `shown_status(run_dir, state)` returns `INTERRUPTED` (not stored to state.json). This tells the human that the run was halted.

**Consequence:** `agile-team status` and the dashboard correctly report an interrupted run without requiring `state.json` changes. Stale pids are harmless; `runner_alive(run_dir)` is the single source of truth.

### 4. Recover the edits on resume (I9, AC3)

`start --resume` detects a stale or dead pid with an interrupted step and saves the edits the same way (commit + revert, cause = `killed`). The resume prompt tells the human the sha was saved. From that point, the step is on the same footing as one that halted mid-run.

**Consequence:** A kill -9 or power loss leaves no trace in `state.json`, but `start --resume` recovers it the same way a cleanly-caught halt does. The resume prompt is explicit: `"the last run was killed; <label>'s edits are saved in <sha>"`.

### 5. Offer saved edits in the next brief (I10, AC8)

Until the step on that story settles, every role's brief on that story includes the saved sha in an exact template:

```
Interrupted work: an earlier {label} step was cut off ({cause}). Its edits are saved in commit {sha} and reverted. Reuse them with `git cherry-pick -n {sha}` and check them before you build on them; files outside your write scope are quarantined again.
```

When a step settles cleanly (whether it reused the edits or not), the offer is cleared.

**Consequence:** Partial work is not lost or redone. Each role on the story sees the offer until the story completes that step. The PO knows what is available on resume.

## Consistency rules

- **Salvage on every halt:** `halt_run`, `_step_failed` (error), and `recover_killed` all save interruptions the same way.
- **Both in-scope and out-of-scope edits go in:** The commit records what was being worked on, even if some of it belongs to another role. On cherry-pick, out-of-scope files are quarantined again.
- **State is the source of truth:** The sha comes from `state.json`, not the PO's memory or git log. All resume logic reads `state.interrupted` and `story.interrupted`.
- **Settlement clears the offer:** Once a step on the story settles (any verdict), the interruption is cleared from that story. Later steps on the same story do not see it.
- **No stash:** Every role works with commits and cherry-pick, not stash. Consistency with s7 sandbox rules (no stash allowed).

## Tradeoffs

- **Commit noise:** Every interrupted step makes two commits (save, revert). For frequent tests, this pollutes the git log. Acceptable: the commits are on the team branch, not on the product branch, and `git log --oneline` shows the pattern clearly.
- **Out-of-scope capture:** Files outside the role's write scope are committed and then quarantined again on cherry-pick. Acceptable: quarantine already handles this. It is simpler than trying to filter at interrupt time (file scope is context-dependent).
- **Sha reachability:** A reverted commit's edits stay reachable by sha forever (until repacked). Acceptable: this is standard git behavior and deliberate. A sha in `state.interrupted` is never stale.
- **No recovery from settle failure:** If `settle` crashes mid-way while committing, `in_flight` may stay set. The next step on the story will overwrite it. Acceptable: an edge case; the next step is independent of the crash.

## References

- Story: `.team/stories/s9.md`
- Design: `agile-team/docs/design/s9.md` (rules I1–I15, modules, test checklist, exact strings)
- Related: ADR-0007 (halt handling in s8), s8 (SIGTERM and limit classification)
