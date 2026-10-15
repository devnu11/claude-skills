# ADR-0066: Tests read the real clock only through `tests/clock.py`, and the page's clock is frozen under node

**Date:** 2026-10-14 · **Story:** s129 · **Design:** `agile-team/docs/design/s129.md`

## Context

`test_s97_awake_page_e2e.py::test_running_line_takes_out_sleep_or_marks_wall`
passed on its PR and failed on main (`480.00099… == 480`). Its driver "pinned"
the page's clock by setting `data.skew = NOW - Date.now() / 1000`, but the
page's `nowS()` reads `Date.now()` again later, so the time that passed in
between leaked into the result. Other e2e tests read `time.time()` and
`time.monotonic()` directly, and many tests compare computed durations with
`==`. The `system` seam rules (s71) already keep the runner's own code off the
real clock. Nothing kept the tests off it.

## Decision

- `agile-team/runner/tests/clock.py` is the only test file that reads the real
  clock. It offers `real_now()`, `real_monotonic()`, `Deadline`, `about()` (a
  duration matcher with `DURATION_TOLERANCE_S = 0.01`) and `page_clock(now)`.
- `dashboard_node.run_page(driver, now=None)` always freezes the page's
  `Date.now`: at `now`, or by default at the fixture's `generated_at`. Drivers
  no longer set `data.skew`.
- An e2e scan test (`tests/e2e/test_s129_clock_scan_e2e.py`) fails on any
  real-clock read under `tests/` outside `clock.py` and its own samples. An AST
  scan fails on any `==`/`!=` compare of a duration-named value inside an
  `assert` that doesn't go through `about`/`approx`.

## Consequences

- Page tests no longer depend on how old the fixture is or on how fast the
  machine is. A test that relied on the real clock making fixture data look
  old now says the time it needs.
- A new real-clock need in tests means a new function in `tests/clock.py`,
  which keeps every such read in one reviewed place.
- `DURATION_NAMES` is a table in the scan test. A new duration name in tests
  has to be added there before the scan checks it.
- No runtime code, dependency or snapshot key changes.

## Amended by s129 (2026-10-14, test-step re-plan)

**What changed.** The scan is split by owner, and every file goes to the role
whose write globs cover it:
- `tests/clock_scan.py` (new) holds the scan's tables and functions. Its
  `Tree.UNIT` covers every file under `tests/` outside `e2e/`, and its
  `Tree.E2E` covers every file under `tests/e2e/`. The two make `tests/`
  exactly once.
- `tests/test_s129_clock_scan.py` (unit-tester, tests step) scans the unit
  tree and tests the scanner. It reads its files into a module constant at
  import, while the OS guard is off, as `fake_system.PACKAGE_FILES` already
  does. So it stays a unit test that touches no OS.
- `tests/e2e/test_s129_clock_scan_e2e.py` (integration-tester, e2e step) scans
  the e2e tree with the same functions.
- `EXEMPT` is `clock.py`, `clock_scan.py` (patterns) and
  `test_s129_clock_scan.py` (samples).
- `fake.slept` (`RECORDED_SLEEPS`) is not a duration. It records the
  arguments passed to the fake's `sleep`, so an exact compare is correct.
- developer-cli writes nothing. Its write scope excludes all test files, and
  the e2e conversions are the integration-tester's (`{e2e}`).

**Why.** The first plan put the scan and helper tests in `tests/e2e/`, and the
`tests/e2e/` conversions with the developer. Neither role could write them: the
unit-tester's scope excludes `tests/e2e/**`, and the developer's excludes every
test file. The story stalled at `tests` three times. A single scan of all of
`tests/` would also stay red until the e2e step, after the implement gate,
which needs every pending test green. The story changes no runtime code, so
its tests step can't produce a red test that a developer turns green. The PO
moves it on with `pass_tests` (design/s129.md).
