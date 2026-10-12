# ADR-0036: Unit tests run no OS calls — single seam with fake and audit

**Date:** 2026-10-12  
**Status:** Accepted  
**Story:** s71 (P1: seam, files, clock)

## Context

Unit tests were reaching the real OS directly: calling `Path` methods, `subprocess`, `time.time()`, `os.kill()`, even inside `tmp_path` fixtures. Tests polluted the test runner's process state, wrote and deleted real files, and could not simulate OS failures that are rare (full disk, permission denied, process not found). Isolation required both infrastructure (a fake OS) and enforcement (an audit hook that fails fast when a unit test breaks the rule).

## Decision

**One seam, three enforcement layers:**

1. **`agile_team/system.py` is the only code that touches the OS.** Thin functions with no logic: `system.read_text(path)`, `system.run(command)`, `system.now()`, etc. Every function in `system.__all__` is swappable. Every other module does `from agile_team import system` and calls `system.func(...)` at the use site, never `from agile_team.system import func` (which would bind the real function at import time, before the test can swap it).

2. **`FakeSystem` swaps the seam in unit tests.** An autouse fixture installs a fresh in-memory fake for every unit test: `monkeypatch.setattr(system, name, getattr(self, name))` for each name in `system.__all__`. The fake:
   - Keeps files in memory (bytes with mtime and mode) with normalised posixpaths against `FAKE_REPO`.
   - Records every write operation in `ops`.
   - Can fail: `deny(path)` makes reads raise `PermissionError`; `fill_disk()` makes all writes raise `OSError(ENOSPC)`.
   - Scripts command results via a `reply(words, result)` rule table; unmatched commands return success by default.
   - Holds the runner's built-in package data (roles, presets, dashboard HTML) at their absolute paths, so reads through `system` work in both fake and real worlds.

3. **Audit hook + patches enforce the rule at runtime.** `sys.addaudithook(os_guard.hook)` fires on every OS audit event. While a unit test (not `tests/e2e/`) runs:
   - If the event is in `AUDITED` and the caller is in `agile_team.*` or `tests.*`, raise `RealOsCall` with exact guidance: "unit test reached the real OS: {call} ({category}); inject it, or move the test to tests/e2e/".
   - If the caller is exempt (import machinery, `coverage`, etc.), allow it.
   - For calls with no audit event (pid, process groups, sleep, `platform`, `which`), a `PATCHED` table wraps them to raise the same error when called from test code.
   - All violations are recorded; if a test swallows the `RealOsCall`, the guard fails the test at teardown.

## Consequences

- **Fast, clean unit tests:** 99%+ of tests run in the fake world in milliseconds on dev machines. No tmp files left behind. No test order dependencies.
- **Realistic failures:** Tests can script a full disk, a missing file, a permission error, or a hung process—scenarios hard to create on the real OS.
- **Safe refactors:** The seam enforces one import pattern. Moving a function or renaming an OS call is caught at the test level before code review.
- **Two worlds in one suite:** `tests/e2e/` runs tests on real files and real OS calls. Unit tests use the fake. The fake's package data lets the same file-reading code work in both.
- **Transparent to production code:** The system module is thin; production code calls it with no knowledge of whether it's real or fake.

## Trade-offs

- **Fidelity gaps:** The fake copies files instead of hard-linking them; a later write to one name doesn't show through the other. This is acceptable because the runner deletes the draft immediately after linking. Reading a denied file raises `PermissionError` when the real OS would not (hard links need no read perm). Same as `os.replace` fidelity gap already documented.
- **Import discipline required:** `from agile_team.system import x` is banned across the codebase (ruff `TID251` in P3). Developers must remember `from agile_team import system` and call `system.x(...)`.
- **Three phases:** P1 (seam, files, clock) ships P1 modules and their tests. P2 (processes, signals, network, s76) and P3 (runtime, close, CLI, s77) follow; until then, files in `LEGACY` run on the real seam.

## Implementation notes

**P1 (s71):** Converted modules: `state`, `ledger`, `events`, `relay`, `watch`, `halt`, `config`, `keys`, `roles`, `health`, and `live`'s heartbeat read. Migrated tests: `test_state`, `test_ledger`, `test_events`, `test_relay`, `test_keys`, plus new `test_system_fake`, `test_os_guard`, `test_s71_seam`, `test_s71_tell`. Deferred to s76: tests for `results`, `po_session`, `onboard`, `presentation`, `paths`, `gates`, `dashboard/snapshot`, `dispatch`, `router` (file call), `checkout`, `stack`, `runner_tools`, and their source conversions.

**Test infrastructure:** `tests/fake_system.py` (in-memory FS, command scripting, package data, methods for each `system.*` name), `tests/os_guard.py` (audit hook, patch table, `World` enum, `RealOsCall` exception), `tests/conftest.py` wiring (autouse fixture, three pytest hook wrappers for setup/call/teardown).

**Docs:** `roles/unit-tester.md` (AC6 text on the seam), `reference/protocol.md` ("Unit tests touch no OS"), architecture and guidelines updated in P3.

## References

- Design: `agile-team/docs/design/s71.md` (Rules O1–O17, Phases, modules per phase)
- Code review: `.team/reviews/s71.md` (round 1, all defects resolved)
- Plan: `.team/run/liaison/plans/unit-test-isolation.md`
