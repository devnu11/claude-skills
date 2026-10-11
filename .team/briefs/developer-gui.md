# Developer (GUI): Current context and conventions

**Last updated:** 2026-10-11 (s21 done)

See `developer.md` for base conventions.

## s21 complete: Dashboard fixes

Three features completed: $/tokens toggle on the "Tokens by" chart (persists across live updates), live budget updates from `.agile-team.toml`, and Done column visible at 1280px. All ACs pass.

- **AC1 toggle:** `ui.unit` defaults to `"tokens"`, click sets it, only `renderBars` reads it
- **AC2 live config:** Each `snapshot.build()` calls `fresh_config()` to re-read config; falls back to startup on error
- **AC3 board layout:** Flexbox with `flex: 1 1 0; min-width: 0` per column; empty columns 44px strips with vertical headings
- **AC4 tests & docs:** All tests pass, coverage ≥95%, ruff clean

Minor findings: `costRow` and `mixRow` repeat role label (nit D-a, deferred); docs note N1 on fallback behavior (minor, no change needed).

Known gap: board tested only with empty columns; integration test to cover full board at 1280px is pending.
