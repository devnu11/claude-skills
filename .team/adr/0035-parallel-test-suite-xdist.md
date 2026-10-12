# ADR-0035: The runner's test suite runs in parallel with pytest-xdist

**Date:** 2026-10-12  
**Status:** Accepted  
**Story:** s70

## Context

The runner's full test suite (implement gate) runs in ~233 seconds on one core. With pytest-xdist on 10 cores it runs in 51 seconds. One test blocked xdist: it was parametrized with `os.getpid()` and `os.getpgrp()`, so each worker collected different test IDs and xdist refused to run ("Different tests were collected between gw0 and gw1").

## Decision

1. **pytest-xdist is a dev dependency** of `agile-team/runner` (`[dependency-groups] dev`). Not a runtime dependency; the installed CLI is unchanged.

2. **Commands opt in with `-n auto`:** The gate's `test` and `coverage` commands, the `[[toolchain.targeted]]` row for `agile-team/runner`, and CI (`.github/workflows/agile-team.yml`) all add `-n auto`. `addopts` in config stays without `-n`, so a named test run from a role's Bash stays serial (faster for one test).

3. **Coverage across workers combines automatically:** pytest-cov detects xdist and writes one `TOTAL` line from the controller; the gate's parser reads it unchanged. No `[tool.coverage.*]` config changes needed. Combined coverage is 95%+.

4. **Test IDs never hold a live value:** The runner's own pid and process group are injected into `sandbox.stop_stale()` as `process_groups.RunnerIds(pid, pgrp)`. The test passes fixed fakes (`RunnerIds(4242, 4243)`) with static ids `["pid", "pgrp"]`, so the test ID is the same in every worker. A new test (`test_s70_ids.py`) collects the suite in two processes at once and asserts both lists are equal, catching any parametrize that evaluates a live value.

## Options considered

- **Make `-n auto` the default in `addopts`.** Every test run, including a single named test, pays for worker startup. Rejected: opt-in is explicit, written in the commands.
- **Resolve live IDs by label in the test.** Fixes IDs without touching code, but the story asks for injection so the test proves `stop_stale`'s own safety check.

## Consequences

- **Gate cycle time:** Implement → quality gate drops from ~4 minutes to ~1 minute on 10 cores. On one core, `-n auto` runs a single worker, no slower than serial.
- **Test independence:** Tests must not depend on order, shared fixed ports, fixed paths outside `tmp_path`, or process IDs. xdist's own check and the s70 ID test catch violations.
- **Presets unchanged:** `python` preset in `presets.toml` stays serial (users may not have pytest-xdist). Users can add `-n auto` to their own commands.
- **unattended/runner unchanged:** Stays serial; no xdist in that runner.

## Implementation notes

- **Modules changed:** `agile_team/process_groups.py` (add `RunnerIds`), `agile_team/sandbox.py` (pass `runner_ids` to `stop_stale`), tests (fix parametrized IDs with `FAKE`, add `test_s70_ids.py`).
- **Config changed:** `pyproject.toml` (add dev dependency), `uv.lock` (pytest-xdist), `.agile-team.toml` (add `-n auto` to agile-team half of test/coverage/targeted commands), `.github/workflows/agile-team.yml` (add `-n auto`).
- **Docs:** SKILL.md (liaison bullet), protocol.md (targeted note), guidelines.md (rule X4), ADR-0035 (this).

## References

- Design: `agile-team/docs/design/s70.md`
- Code review: `.team/reviews/s70.md`
- Initial issue: `.team/run/liaison/reports/2026-10-12-time-spent.md`
