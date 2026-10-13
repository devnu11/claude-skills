# Architect: Current context and conventions

**Last updated:** 2026-10-12 (s65 done)

## s65: Git confinement—S61 incident solved, no ADR (extends s41/s43/s69 guard pattern)

During s61, integration-tester's git demo had no `.git`, so git climbed to the team repo and moved the human's `main`. Two-layer solution in code:

**Layer 1: Environment (G2).** Confined steps (e2e, acceptance) get `GIT_CEILING_DIRECTORIES=<run_dir>` and `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1` in launch env. Git can't climb above `.team/run`, so a demo with no `.git` fails "not a git repository", not reaching the team repo.

**Layer 2: Guard (G3–G7).** New pure module `git_check.py` classifies git segments. The PreToolUse hook now sees through command prefixes (env, command, timeout, etc.) via `WRAPPERS` table (G3). For each git segment, tracks where it works via cd tracking and places (G5), looks up `GIT_RULES` by `Where` (G6), and denies writes/reads to elsewhere. In confined steps, additionally denies mentions of locked env vars (GIT_CEILING_DIRECTORIES, GIT_DIR, GIT_WORK_TREE, GIT_DISCOVERY_ACROSS_FILESYSTEM, CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR) (G7).

**Data tables (no branching):** `GIT_CONFINED` (e2e, acceptance → workspace getters), `WRAPPERS` (env, command, timeout, etc.), `PATH_ARGS` (init, clone, push, etc. → ALL/FIRST), `GIT_RULES` (Where → allows/reason), `ALLOWS` (READ_ONLY/ANY/NONE predicates).

**Modules:** New `git_check.py` (pure, ~380 LOC, I/O only via `paths.resolve_in`). Changed: `guard.py` (moves SAFE_GIT/NO_COMMIT_FLAGS, calls git_check), `presentation.py` (workspace survives bounce via `_ensure_workspace`), `dispatch.py` (GIT_CONFINED table, _confine_git call at setup end).

**Coverage:** ≥95%, all AC1–AC10 pass. E2E test `test_git_confinement.py` runs in real git (isolated_git fixture). No new dependency. See design `agile-team/docs/design/s65.md` (G1–G10, test checklist).

## s59: Rebase at sprint start (ADR-0041, rule R1–R12, docs updated)

Sprint-boundary sync rebases the team branch onto main instead of merging, dropping commits already upstream. False conflicts from sprint 18 (~100) are gone. The decision replaces ADR-005 decision 1 ("merge in, never rewrite").

**Key rules (R1–R12):**
- **R1:** `git rebase --empty=drop`, no merge, no `-s ours` or `-X ours`. Result is linear.
- **R2:** Boundary.sync_from pinned before rebase; save before rebase on first run guards against crash losing old hash map.
- **R5:** Commits paired by stamp (author, date, message); dropped commits map to last matched copy or rebase base.
- **R6:** Hashes rewritten in `REMAPPED` fields only (story commits, code commits, interrupted shas, stack entries); `checked`, `head`, `pushed`, `base` left alone.
- **R7:** Lost-content check validates no path changed without one side touching it; reset on violation.
- **R9:** New outcome `REBASED` (sha, rewritten count); tone is `"good"`.
- **R12:** Only START edge rebases; END edge unchanged.

**Docs updated:** `agile-team/SKILL.md` (sprint boundaries section), `agile-team/reference/protocol.md` (hold table, start step), `agile-team/docs/customer/review-stack.md`, fixture e93 (end-edge sync: `outcome: pass`, not `rebased`).

**Process in code:** `rewrite.py` pure, `Rebase` dataclass, `SyncOutcome` enum, dispatch via `AFTER_REBASE` dict (table-driven, no branching). E2E tests (5 cases) pending for integration-tester.

See design `agile-team/docs/design/s59.md` (R1–R12, test checklist, known limits), review round 3, ADR-0041.

## s89: Guard refined to let stdlib read source on 3.13 (no new ADR, extends s71)

Python 3.13 changed `linecache.updatecache` to use `__spec__.loader.get_source`, causing `open` calls charged to a non-exempt module (e.g. `_pytest.assertion.rewrite`). Rules T1–T6 fix the guard:

- **T1:** Source read is stdlib's. An audited event allowed when a frame of `SOURCE_READERS` (`traceback`, `linecache`) is on the stack **inside** the nearest guarded frame (`agile_team`, `tests`). With no guarded frame, whole stack counts.
- **T2:** Opener rule unchanged. `"traceback"` joins `EXEMPT_CALLERS`.
- **T3:** Code under test still fails. An open from `agile_team.*` or `tests.*` is refused even while traceback formats.
- **T4:** No new relaxation elsewhere. No event allowed by outer exempt modules (xdist, coverage).
- **T5:** Violation names its caller with `(caller: {caller})` suffix.
- **T6:** Patched calls (line 209) unchanged.

New helper `call_audited_through(names, event)` builds relay chains from synthetic modules for testing multi-frame stacks. See design `agile-team/docs/design/s89.md`.

## s81: CI stage at boundary; verdict rules data-driven (ADR-0040, extends s29)

New CI stage runs after the boundary pushes. Waits for `gh pr checks --watch` under `ci_timeout_s` deadline (default 1800s). Verdict is green only when every watched PR is green. Red or timeout holds the boundary until a bug story is recorded.

**Architectural decisions:**
1. **One new stage in pipeline:** `STAGES = (SYNC, CHECK, REVIEW, PUSH, CI)`. Runs after PUSH on every boundary that pushed, and at start only when restacking.
2. **Data-driven verdicts:** `Bucket` enum, `BUCKET_VERDICT` table (fail/cancel→red, pass→green, pending→pending), `CHECK_ORDER` = (red, pending, green), `PR_ORDER` = (red, pending, none, green). No branching on verdict type.
3. **Failing lines extracted:** Job id from link, log via `gh run view --job <id> --log-failed`. Match pytest/go patterns, max 20 lines, fallback last 10 non-blank.
4. **Only green marks ready:** Phrase "ready to merge" appears only in `ci_green` hand-over line and green report. Never from red, pending, none, local, or pushed reports.
5. **Hold until bug story recorded:** `record_ci_bug(tool)` writes `upstream.ci_bug`, closes the boundary with "checks failed, story sN opened". Bug story must be first in next sprint.
6. **No new dependency:** `gh` stays behind `Prs` interface. Unit tests fake it via `system.run` seam.

**Modules:** New `ci.py` (CiWatch class, verdict rules, text builders). Changed: `boundary.py` (stage, holds, state fields), `boundary_runner.py` (outcome methods), `upstream.py` (Prs protocol), `po_tools.py` (record_ci_bug tool), `config.py` (ci_timeout_s), `state.py` (loaders), `handover.py` (ci_green/ci_failed/ci_pending rules).

See ADR-0040, design `agile-team/docs/design/s81.md` (rules CI1–CI16).

## Seam completion (s77, no new ADR)

P3 closes s71 architecture. Six new `system.py` names: `home`, `which`, `on_signal`, `open_browser`, `async_sleep`, `HttpServer`. All 31 pre-P1 LEGACY tests migrated to fake or e2e. Ruff TID251 enforces `from agile_team import system` import discipline across all code.

**Consequence:** Seam is complete. Every OS interaction auditable and testable. All code follows one pattern. No branching on test type (world enum decides timeout). See ADR-0036 (s71 architecture).

## Key design principles (your domain)

- **Process in code, not prompt:** Gate rules, hold clearing, verdict logic, bounds are data tables or code functions, never prose agreements.
- **Data-driven over branching:** Tables (BUCKET_VERDICT, PR_ORDER, HALTS, WAITS, NORMALISE) let new cases be added without conditionals.
- **Single source of truth:** Snapshot carries raw data; browser derives views. Heartbeat carries both clocks; reader detects sleep. State.checkout is only branch record; check runs everywhere.
- **Blocking is safe:** CI stage blocks router up to 30 min; health stays green via `pulse.doing()`. Resume works (push saved before CI, resume reruns wait).

See ADRs 0007, 0009, 0013, 0015, 0027, 0040 for decisions on design patterns.

## Your focus (unchanged)

Review step sequences, gate checks, role boundaries. Ensure snapshot contract, state transitions, and error paths. Verify integration at role boundaries (tester → proxy, git ops seam, HTTP seam).
