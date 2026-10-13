# Unit Tester: Current context and conventions

**Last updated:** 2026-10-12 (s65 done)

## s65: Git confinement (unit tests, coverage ≥95%, no new ADR)

Tests for `git_check.py` (new pure module), `guard.py` (G3, G4, G7 checks), `presentation.py` (workspace survival), `dispatch.py` (confined setup). Key test areas:

**`git_check.py`:** Strip prefixes (G3: `X=1`, `env`, `command`, `timeout`, etc.), parse git (first/sub words, options), bases (cd tracking, unknown on unanchored move), where (D location: UNCONFINED/STEP_DIR/WORKSPACE/ELSEWHERE/UNKNOWN), denial reasons (G4/G6/G7 applied). Path resolution through `-C`, `--git-dir`, `--work-tree`, `-c name=value`. Outside words (URLs, scp, flags). Cd tracking across separators (`&&` carries base, `;` makes it unknown).

**Guard integration:** G3 sees through `env -C`/`-S`, finds git after wrappers. Git segment check returns denial reason or None. Environment vars in `GIT_ENV_LOCKED` denied (G7) in confined steps. Regression: unconfined `git status`/`cherry-pick -n` allowed, `git commit`/`git -C x status` denied with today's text.

**Presentation:** Workspace persists across bounce (lay_out creates dir and runs `git init -q` only when missing). Integration-tester's workspace contains git repos.

**Dispatch:** `GIT_CONFINED` table maps `e2e`/`acceptance` to workspace getter; `_confine_git` sets `scope.git_workspace` and `launch.env` with ceiling/cwd-keep. Developer steps unconfined (neither set).

**E2E** (new `tests/e2e/test_git_confinement.py`, isolated_git + set_git_identity): in a scratch "team" repo, workspace below `.team/run/presentation/<id>/workspace`, git inside workspace passes (init, cd, commit, checkout, rebase, clone), git at team repo fails (guard denial or ceiling).

All existing tests pass; no test deleted. Coverage ≥95%, ruff clean. See design `agile-team/docs/design/s65.md`.

## s59: Rebase at sprint start (unit tests, coverage 99.43%, no new ADR scope)

Unit tests cover pairing (match, all dropped, middle dropped, first dropped, merge commit), remap (count, REMAPPED fields yes/no, staleness safe), rebase (argv exact, current, rebased with pairing, conflict with abort, lost-path reset), sync_from (set once, reused, save before rebase order), dispatch (conflict hold, rebased event, current emit), push guard (team branch refused), and group_files (directory grouping). Fixture e93 (end-edge) is now `outcome: pass`, not `rebased` (R12: only START edge rebases).

**No tests deleted; removed `merge_in` tests replaced by rebase tests.** E2E tests (5 cases: all upstream, copies+new, real conflict, hash rewrite, hand rebase after conflict) belong to integration-tester's e2e step, not unit.

See design `agile-team/docs/design/s59.md` (test checklist), review round 3 (all defects fixed).

## s89: OS guard refined to allow stdlib source reads on 3.13 (test infrastructure, no new ADR)

Guard rules T1–T6 (design): T1 allows source reads by `traceback`/`linecache` inside a guarded frame. T2–T4 unchanged (exempt callers, code under test still fails, no other relaxation). T5 names the caller in violations. T6 patched calls unchanged. **Changes:** `tests/os_guard.py` (add `_modules()` generator, `_reading_source()`, `SOURCE_READERS` tuple, `CALLER_NOTE`); `tests/test_os_guard.py` (new helper `call_audited_through` for multi-frame stacks, 7 parametrized T1/T3/T4 test cases, AC2 test `test_formatting_a_real_traceback_passes_the_guard`). All existing tests unchanged and pass. 36 earlier 3.13 failures now pass. Coverage 99.31%, ruff clean. See design `agile-team/docs/design/s89.md`.

## s81: Test CI module, boundary changes, fake Prs (no new ADR)

New test file `tests/test_s81_boundary.py` (and helpers). Test areas:

**`ci.py` module (pure):**
- `bucket_of`: unknown → FAIL (safe side, never green).
- `verdict_of`: [] → NONE; all skipping → NONE; mixed (pass+pending) → PENDING; any red → RED.
- `overall`: all checks are computed per-PR then ranked PR-wide. GREEN only when all PRs green.
- `failing_lines`: strips gh prefix/timestamp, keeps pytest/go patterns, max 20, fallback last 10.
- `green_report`: raises ValueError for any non-green or empty list.

**`CiWatch` (fake clock, fake Prs via s29_helpers):**
- Green on first look (one watch, one read, no sleep).
- No checks at first, then on 3rd look (sleep twice, CI_POLL_S).
- Timeout: watch Hang's, read shows pending, result is PENDING.
- Red: `failed_log` called with link, lines recorded.

**`boundary_runner` integration (green, red with lines, timeout, no PR, hold until bug story):**
- After push, stage is `ci`; watch only non-draft READY PRs.
- Green → `done` event with `ci: green`, `results`, `prs`. Report has READY_PHRASE.
- Red → `held` with `hold: ci_failed`, `ci: red`, checks with job name and lines.
- Timeout → held `ci_pending` with reason naming pending checks.
- No checks / no non-draft PR → done with `ci: none`, no READY_PHRASE.
- Push permission `no` → local event, never reaches ci.
- Hold until bug story recorded (via settle_bug).

**`po_tools.record_ci_bug`:**
- Refused: no CI hold, unknown story, done story.
- Accepted: boundary closes, upstream.closed == sprint, report says "checks failed, story sN opened", ci_bug == sN.

**`state.py` loaders:**
- Legacy files without `ci` or `ci_bug` load with None and "".
- CiResult round-trips through asdict/reload.

**`handover.py` rows (ci_green, ci_failed, ci_pending):**
- Apply only to their report shapes (ci field exact).
- ci_green triggers only on report with `ci == "green"`, not on hold field.

**`config.py`:**
- `ci_timeout_s` defaults 1800, must be positive.

All tests on fake. Exit code 124 (timeout) handled. No test deleted or weakened. Coverage ≥99%, ruff clean.

See design `agile-team/docs/design/s81.md` (test checklist, AC7 e2e pending).

## Recent completions (s77–s78)

- **s77:** P3 closes seam; all 31 LEGACY files migrated. Ruff TID251 enforces import discipline.
- **s76:** P2 seam—13 process/signal/network functions faked, moved 4 test files to e2e.
- **s78:** Health accuracy—beat thread resilience, monotonic sleep detection, excuse logic for active work.

See ADR-0038 (s78), ADR-0036 (s71 seam architecture).

## Your scope (unchanged)

Unit tests only. Run named tests with `run_tests` tool. Never full suite or `--cov`. Design file is contract; read source only for gaps.
