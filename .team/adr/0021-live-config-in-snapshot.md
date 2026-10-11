# ADR-0021: Live configuration in snapshot builds

**Date:** 2026-10-11  
**Story:** s21

## Context

The dashboard was showing budget and other configuration values from when it started. Users could not see changes to `.agile-team.toml` without restarting the dashboard. AC2 requires the budget and other config values to update when the config file changes.

The dashboard already uses Server-Sent Events (SSE) to push snapshots to the browser. Adding the config file to the watched files for SSE fingerprint calculation was straightforward, but re-reading the config file itself needed a safe strategy.

## Decision

- Each `snapshot.build()` calls `fresh_config(config)` to re-read `.agile-team.toml` from the repo
- If the file is missing or has TOML syntax errors (`ConfigError`), use the config from startup (fallback)
- The config file path is added to `watched_files()`, so changes trigger a new fingerprint and SSE push
- The role book (`.team/roles/` files and `[roles.*]` section) is still built once at startup; changes need a restart

## Consequences

**Positive:**
- Budget, pipeline steps, manager interval, round cap, and cadence are always current
- Changes to `.agile-team.toml` are visible in the browser within one SSE push cycle (typically under 1 second)
- No breaking change to the snapshot contract or role instantiation

**Constraints:**
- If a user writes an incomplete or invalid TOML file, the dashboard falls back to startup config for that push
  - A file that parses but is incomplete (e.g., empty or missing fields) loads with defaults until the next save
  - Only a missing or unparsable file falls back to startup config
- Wrongly-typed values (e.g., `team = 5` instead of a table) still cause the build to raise; this is a known gap (s4)
- `docs_dir` changes need a restart because `watched_files()` uses the startup config's directory path
- If config is being written (half-saved), the filesystem may see a temporary invalid file; the fallback handles this gracefully

## Related

- ADR-0002, ADR-0004: Dashboard architecture (vanilla JS, SSE, live updates)
- s21 design: rules F5–F6
