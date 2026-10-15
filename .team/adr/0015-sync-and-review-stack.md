# ADR-0015: Sync with upstream, verify review branches, and deliver stacked PRs

**Date:** 2026-10-11 (s29 done)  
**Status:** Accepted  
**Relates to:** ADR-0014 (escalate repeated setbacks), ADR-0013 (liveness), ADR-0009 (routing in code), s3 (sprints)

**Amended by s151 (2026-10-15):** Review branches are no longer derived.
The cherry-pick `review` stage and the `restack` stage are removed, and PRs
are no longer stacked. Each sprint end pushes the team branch as it is to
`<prefix><N>`, opens or reuses one PR based on main, waits for green CI,
then rebases the team branch and pushes it again to the same PR. Earlier
sprints' entries leave the stack. See ADR-0075. Sections 2, 3 and the
stack parts of 4 and 7 below are superseded.

## Context

**Manual workflow at the end of a sprint:** The human had to push review branches upstream, rebase them on main, verify they still work, then repush. At the start of the next sprint, rebase on the latest upstream main and validate. For stacked PRs, every PR had to be updated to the latest main and rebase-merged in order, one by one.

**Requirements:** The team's work must stay in sync with upstream (no stale divergences), each sprint's PR must be rebased on the latest main at review time and verified before push, and draft PRs should not trigger CI for every PR in the stack—only the ready one.

**Known constraints:**
1. The team branch's commit hashes are recorded in `state.json` and must never change (s3 sprints).
2. Review branches are rebuilt from scratch; fixes made only on a review branch are lost at the next rebuild, so all fixes go on the team branch.
3. Merges to main must be rebase merges (so entries are dropped cleanly by cherry-pick logic).
4. The runner owns the workflow; it runs at sprint boundaries as code, not as a prompt.

## Decision

### 1. Team branch stays put; sync at start merges in (U1, U5)

At sprint start, the runner runs a **boundary** step (a sprint-edge step no prompt can skip or override). It sets `state.boundary` and the router picks it before any sprint story moves. The boundary first runs the **sync** stage: if the team branch is not on a detached HEAD, it fetches the configured upstream and merges `<remote>/<branch>` into the team branch with `git merge --no-edit`. A new commit is made; the team branch stays valid. If HEAD did not change (nothing new), no commit is added. The team branch's hash stays known. Merges cannot be avoided—they are the point: every sprint must see the latest upstream.

**Consequence:** The team never rebases or resets the team branch. Hashes in state, reviews and designs stay valid forever.

### 2. Review branches are derived and rebuilt (U3, U15, U16)

At sprint end, after the full checks pass on the team branch, the boundary opens the **review** stage. This stage builds new review branches by cherry-picking the sprint's own commits onto the latest `<remote>/<branch>` in a **separate worktree** (`.team/run/review`), so the team branch and its hashes never change. Each entry is cherry-picked in order (bottom to top, starting from the target). If a cherry-pick conflicts, it stops and hands over to DevOps (a fix step in the worktree). After the fix, `git rerere` records the conflict resolution, and the rebuild runs again from scratch—rerere replays the resolution. After every entry is built, the bottom and top are checked.

**Consequence:** Review branches are not edited by hand; they are rebuilt every time. A fix made on the team branch reaches every review branch. Conflict resolutions are recorded and reused. The review worktree is ephemeral (git can clean it up).

### 3. Stack: one PR per sprint, bottom ready, others draft (U4, U8, U18)

At sprint end, after the review branches are built and pass checks, the **push** stage begins. For each sprint's entry, the runner creates or updates a PR: the **bottom** PR has base = `<remote>/<branch>` and mode `ready` (open for review), and every other PR has base = the previous entry's branch and mode `draft` (not open for review, skips CI). Each PR includes a `STACKED_LINE` in the body (except the bottom) saying which PR to merge first.

When the bottom PR merges (detected at the next sync), the runner drops that entry from the stack, retargets the next PR to main, and marks it ready. From that point, CI runs once (on the now-ready PR). Merges must be rebase merges: that way, the picks in that entry are in main and `git cherry-pick` drops the entry at the next rebuild (U8).

**Consequence:** Only one PR is ready at a time. CI runs once per merge, not once per PR in the stack. Unmerged stale PRs persist and can be updated later (e.g., if a human merges one out of order). Closed PRs are left alone.

### 4. Boundaries are code: sync, check, review, push are sprint-edge steps (U2, U3)

The four boundary stages—**sync** (merge in upstream), **check** (run full checks), **review** (rebuild and check review branches), **push** (open or update PRs)—are not prompts. They are runner steps that the router picks before any sprint story. The boundary cannot be skipped or manually reordered. A held boundary (due to a conflict or failed check) requires explicit `continue_boundary` from the PO before the sprint's stories can move.

A failed check or rebuild conflict triggers a **fix step**: the DevOps role (no sprint story) gets a brief quoting the failure and fixes it. A fix runs `after_fix()` to resume the stage. A repeat of the same failure escalates to the Manager (s27).

**Consequence:** The workflow is deterministic and logged. The PO and Manager can override (hold or escalate). Fixes are tracked. The round-cap rule (s27) applies to boundary failures too.

### 5. Stalled boundaries and permission hand-overs (U6, U17, U20, U21)

While a boundary is held (e.g., sync conflict, check failed, permission pending), the runner refuses `start_sprint` and holds the sprint's stories with `BOUNDARY_REFUSAL`. When the PO calls `continue_boundary`, the boundary resumes its stage. An escalated boundary is also held until the Manager rules on it and the PO clears it with `continue_boundary(note)`.

At the **push** stage, if permission has not been asked yet, the runner asks: "May the team push review branches and open or update PRs?" The PO tool `set_push_permission({"answer": "yes" | "no"})` records the answer, which applies to every later sprint without asking again. If the answer is "no", the boundary finishes with a note and the branches are kept local.

**Consequence:** Every decision point (merge conflict, failed check, permission) is explicit and reversible. Permission is asked once, not per-sprint. The PO controls the gate.

### 6. The narrow Git and PR interface (U7, U24)

All remote operations go through two narrow, testable interfaces: `Upstream` (git) and `Prs` (PR service). `Upstream` has a single `Git` and `UpstreamSettings`; it handles fetch, merge, cherry-pick, push, merge-base. `Prs` is a protocol with four methods (`missing`, `find`, `create`, `edit`); `GhPrs` implements it with `gh`, and `NoPrs` reports why the service is missing.

Tests use bare repos in a scratch directory as `origin` and a fake `Prs` that records calls. Tests never run `gh` or touch a real remote. A repo with no upstream or no `gh` skips the sync and PR steps with a note, not an error.

**Consequence:** Git operations are isolated and testable. The implementation is swappable (fake for tests, `GhPrs` for production). The runner works with or without a remote.

### 7. Dashboard shows the stack and boundary (U8, U25)

The snapshot adds an `upstream` section: `team_branch`, `remote`, `branch`, `push` (yes/no/unasked), `report` (end-of-sprint message), `boundary` (current or null), and `stack` (list of entries with sprint, branch, base, PR#, mode, check). The Board view shows a **Review stack** card (when there are entries or a boundary) with the entries (sprint, branch, PR link, mode and check pills). The timeline shows `boundary` events (sync, check, review, push, held, done, etc.).

**Consequence:** The stack is visible and persistent. The human can see what is pending and what permissions are outstanding.

## Consistency rules

- **Never rewrite team branch:** No rebase, reset or amend. Merges are the only commits that touch it.
- **Fix on team branch, not review branch:** A fix made in a review worktree is lost at the next rebuild. `git rerere` only records conflicts, not new commits.
- **Rebase merges only:** Squash or commit merges change the patch ids, so entries do not drop from the stack until they are empty.
- **Boundary first:** The router picks boundary work before any sprint story. Held boundaries block all story moves.
- **Permission is idempotent:** Setting it again clears any hold and reruns the stage.
- **Events are facts:** Every boundary event (sync outcome, check pass/fail, conflict, hold, continue, push) is logged. The event's id ties it to handover context.

## Tradeoffs

- **Derived review branches cost rebuilds:** At each boundary stage, branches are rebuilt from scratch. For large repos this is slow. A fresh rebuild is the only way to ensure they are current and conflicts are detected early.
- **A check that fails only below:** A fix lands on the team branch, so it reaches the top review branch but not lower ones. If bottom and new main have a semantic conflict (not a patch conflict), the same failure repeats. The human then decides (merge the stack in one go). Carrying per-branch fixes would break the "rebuild from scratch" rule.
- **rerere replays only identical conflicts:** A changed main can bring a new conflict, which is a new fix step. Partial conflict resolution (e.g., "resolve line X differently this time") is a different conflict.
- **Merges to main are rebase-merge only:** A squash merge changes the patch id; the entry is not dropped until it comes out empty (every pick skipped or conflicts). Document this in a CI workflow note.

## References

- Story: `.team/stories/s29.md`
- Design: `agile-team/docs/design/s29.md` (rules U1–U27, modules, test checklist, exact strings)
- Related: ADR-0014 (escalation in boundary failures), ADR-0013 (liveness data), ADR-0009 (routing in code)
