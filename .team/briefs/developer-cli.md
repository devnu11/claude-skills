# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-12 (s81 done)

See `developer.md` for the base conventions.

## s81: New CI module and boundary stage (no new ADR, extends s29)

New module `agile_team/ci.py` handles PR check results: data (Check, CiResult), enums (Bucket, CiVerdict), verdict rules (CI1–CI7), texts, and CiWatch for waiting. No new dependencies, `gh` stays behind the Prs interface. Changes:

- **`boundary.py`:** `Stage.CI`, `BoundaryHold.CI_FAILED`, `BoundaryHold.CI_PENDING`, `StackEntry.ci: CiResult | None`, `UpstreamState.ci_bug`, `PUSHED_REPORT` updated, `LOCAL_REPORT` ends with "No CI result exists."
- **`boundary_runner.py`:** New `_ci(self, b)` stage method, outcome methods `_ci_green/red/pending/none`, `settle_bug(story)` for recording bug stories. Four outcome functions mapped in `CI_OUTCOMES`.
- **`upstream.py`:** `Prs` protocol gains three methods: `wait_checks(number, limit_s)`, `checks(number)`, `failed_log(link)`. `GhPrs` implements them; `command_runner` passes timeouts.
- **`po_tools.py`:** New `record_ci_bug(story)` tool; `start_sprint` refuses unless `ci_bug` story is first.
- **`config.py`:** `Gates.ci_timeout_s: float = 1800.0` (configurable, validated positive).
- **`state.py`:** Loaders handle legacy files without `ci` or `ci_bug` (defaults: None, "").

**Key design points:** CI verdict rules are data-driven (`BUCKET_VERDICT`, `CHECK_ORDER`, `PR_ORDER`). Failing lines extracted from logs, at most 20 lines. No "ready to merge" phrase outside green verdict. The stage runs inside `pulse.doing()` so health stays green. Blocks the router up to `ci_timeout_s`.

See ADR-0040, design `agile-team/docs/design/s81.md`.

## Recent changes (s75–s79)

- **s77:** Seam P3 complete—six P3 functions added to `system.py` (home, which, on_signal, open_browser, async_sleep, HttpServer type). All OS calls now flow through the seam. Ruff TID251 enforces import discipline.
- **s76:** P2 seam—13 process/signal/network/HTTP functions added to `system.py` and called throughout code. Module `kill_words.py` bans `pkill`/`killall`.
- **s71:** Seam architecture—all OS calls flow through `system.py`. Unit tests run on fake with audit hook. Three phases: P1 (s71), P2 (s76), P3 (s77).

See ADR-0036 (s71 architecture).

## Context reduction (s23, s71)

Design file is your contract. Read source only for what the design leaves open. Grep with `-n`, read with `offset`/`limit` to avoid re-reading. Never run full suite; use `run_tests` tool for specific tests.
