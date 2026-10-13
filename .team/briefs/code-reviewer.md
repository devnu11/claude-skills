# Code Reviewer: Current context and conventions

**Last updated:** 2026-10-12 (s65 done)

## s65: Git confinement (one round, design matched, no new ADR) — verdict ship

**Scope:** `git_check.py` (new pure module), `guard.py`, `presentation.py`, `dispatch.py`, role files, docs. **Verdict: ship.** Diff matches design G1–G10 line for line. Coverage ≥95%, ruff clean. No test deleted or weakened.

**Design rules enforced in code:**
- **G1–G2:** `GIT_CONFINED` table (e2e, acceptance), `git_env(run_dir)` returns ceiling+cwd vars, `_confine_git` merges into launch.env.
- **G3:** `strip_prefixes(words)` skips assignments, WRAPPERS, returns command words after them.
- **G4:** `_read_only(call)` on unconfined segments, today's text.
- **G5:** `bases(links, start)` tracks cd moves (cd/pushd on AND only, unknown after other separators), `where(site, call, base)` resolves places (env -C, -C, --git-dir, --work-tree, -c) and args (PATH_ARGS), classifies Where (UNCONFINED/STEP_DIR/WORKSPACE/ELSEWHERE/UNKNOWN).
- **G6:** `GIT_RULES[Where]` table maps to `GitRule(allows, reason)`, `ALLOWS` predicates enforce them.
- **G7:** `_locked_mention(name)` denies GIT_ENV_LOCKED vars in confined steps.
- **G10:** `_check_view` order: secret, git (G7 then G3–G6), allowlist, tokens, waits, kills, suite.

**Module structure:** `git_check.py` pure (I/O only `resolve_in`), exports classes (Wrapper, Where, Allows, GitRule, Link, Stripped, GitCall, Site) and functions (strip_prefixes, parse_git, bases, where, git_denial, git_env); guard.py imports from git_check, `_check_git` lambda calls `git_denial(_site(scope), links)`.

**Regression tests:** Unconfined `git status`, `git cherry-pick -n x` allowed; `git commit`, `git -C x status` denied. Command prefixes (env, command, timeout) seen through. Option-first placement denied.

**All AC1–AC10 pass:** Environment stops discovery (test with git_env on real repo). Guard denies explicit access and sees through prefixes (parametrized tests). Workspace persists (lay_out creates/keeps). Denial texts name targets exactly.

See design `agile-team/docs/design/s65.md` (G1–G10, test checklist).

## s59: Rebase at sprint start (3 rounds, all defects fixed) — verdict ship (e2e pending)

**Scope:** `rewrite.py` (new), `upstream.py`, `boundary.py`, `boundary_runner.py`, `handover.py`, dashboard, docs. **Verdict: ship (e2e pending).**

**Round 1:** Design rules R1–R12 matched closely. No merge, no `-s ours`, linear result. Boundary gains `sync_from` field, outcome `REBASED`. `rebase_onto` reads start and target, runs exact argv, handles conflict by abort+read, checks for lost content. `rewrite.py` pure, pairing by stamp, remap by field table. Dispatch via `AFTER_REBASE` dict (R1–R12 data-driven). Fixture e93 (end-edge) becomes `pass` not `rebased` (R12: only START). No test deleted, no dependency added. **Changes requested:** R2 save before rebase (D1, D2), style (D3, D4).

**Round 2 defects fixed in round 3:**
- **D1, D2:** `_pin_sync_from` guard saves only when empty; two tests pin order (save before rebase on first run, rebase first on rerun).
- **D3:** Push test renamed; moved moved-assertion to separate test.
- **D4:** `_swap` helper reduces repeated swap-and-count; type hints on `_story`, `_interruptions`.

**Checked:** No `merge`, `-s`, or `-X` in sync. Team-branch push refusal pins both target and team (R11). `REMAPPED` table exact; `checked` not rewritten. No repeated blocks new. Coverage 99.43%, ruff clean.

**Pending:** AC6 e2e tests (5 cases: all upstream, copies+new, real conflict, hash rewrite, hand rebase after conflict). Integration-tester scope, design specifies all cases exactly.

See design `agile-team/docs/design/s59.md` (R1–R12, test checklist), review round 3, ADR-0041.

## s89: OS guard refined for 3.13 (test infrastructure, no new ADR) — verdict ship

**Scope:** `tests/os_guard.py`, `tests/test_os_guard.py`, `docs/architecture.md` (one row), `docs/design/s89.md`. **Verdict: ship.** Diff matches design line for line. Coverage 99.31%, ruff clean. No test deleted or weakened, no runtime code changed. Guard refined with rules T1–T6. New helper `call_audited_through` builds relay chains for testing multi-frame stacks (reuses `as_module`). `_modules()` is new generator yielding stack module names; `_caller()` refactored to use it (DRY). `_reading_source()` implements T1 (reader on stack inside guarded frame). AC1 (3.13 pass, 36 failures fixed), AC2 (traceback formatting test), AC3 (guard still catches real agile_team code) verified. AC4 will be checked at s81 CI boundary. See design `agile-team/docs/design/s89.md`.

## s81: CI module, boundary stage, Prs protocol — verdict ship (e2e work pending)

**Verdict: ship (e2e pending).** Scope: `ci.py`, `boundary.py`, `boundary_runner.py`, `upstream.py`, `po_tools.py`, `config.py`, `state.py`, `handover.py`, `test_s81_boundary.py`. Coverage 99.31%; ruff clean.

**Design review (CI1–CI16):**
- CI1: Stage added, runs after PUSH on every boundary that pushed.
- CI2: Only READY non-draft entries watched.
- CI3–CI4: Wait, grace, settle checks with retry loop.
- CI5–CI7: Verdict rules data-driven, GREEN only when all PRs green.
- CI8: Failing lines extracted from logs, safe patterns, max 20 lines.
- CI9–CI10: State and events recorded, four outcomes per verdict.
- CI11: Hold cleared only by green verdict or recorded bug story.
- CI12: READY_PHRASE appears only in green report and green hand-over.
- CI13: No PR or gh → NONE, not ready.
- CI14: Bug story first in sprint.
- CI15: Blocking acceptable, health green via `pulse.doing()`.
- CI16: Errors raised as UpstreamError.

**Module review:**
- `ci.py`: Verdict rules sound, failing_lines patterns correct, CiWatch contract met.
- `GhPrs` methods: argv exact, exit codes handled, log reads safe.
- `record_ci_bug`: refusals checked, settle_bug closes boundary, ci_bug field cleared on start_sprint.
- State loaders: legacy files load with defaults, round-trip tested.
- Handover rows: apply only to matching report shapes, ci_green on ci field not hold.
- `ci_timeout_s` validated positive, default 1800.

No test deleted or weakened. No dependency added.

**Pending:** AC7 e2e test (stub gh on PATH, capture argv, assert logs read). Integration-tester scope, design specifies it exactly.

All nine rule classes (CI1–CI16, not CI13 which has no rule class) enforced in code. See design `agile-team/docs/design/s81.md`, ADR-0040.

## Recent reviews (s77–s78, no new ADR)

- **s77:** Seam P3—import discipline enforced by ruff TID251.
- **s78:** Health accuracy—beat resilience, monotonic sleep, excuse logic.

See ADR-0036 (s71 seam), ADR-0038 (s78 health).

## Your focus

Verify design rules are enforced in code (not prompt). Check that verdict logic is data-driven (no branching on bucket type). Ensure Prs interface is unchanged (gh calls stay behind it). Confirm no new user-facing changes except hand-overs and tool.
