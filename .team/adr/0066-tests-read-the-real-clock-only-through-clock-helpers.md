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
