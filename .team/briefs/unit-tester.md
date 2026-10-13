# Unit Tester: Current context and conventions

**Last updated:** 2026-10-12 (s81 done)

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
