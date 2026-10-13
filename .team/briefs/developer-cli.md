# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-13 (s84 done)

See `developer.md` for the base conventions.

## s84: Story threads—liaison replies via CLI command (ADR-0044)

Liaison now has `agile-team reply <story> <source>` command to answer a human's question on a story's thread on the dashboard. The text comes from a file or stdin (the same `-` pattern as `tell`). Unknown story, empty, or over-long text (>4000 chars) raises `CliError` with exact error text. On success, appends to `liaison/replies.jsonl` and prints `replied <id> on <story>`. Works while run is stopped. See ADR-0044, design `agile-team/docs/design/s84.md`.

## s51: Story priority with tiers and pulls (AC1–AC6 pass, design rules G1–G17)

Replaced s40 rule P2 with tier-based ranking: started (in progress) > held > not started. PO's order ranks within groups. New rules: `Tier` enum, `Priority.tier()`, `plan()`, `with_move()`, `pull()` functions. Pulls need reasons (G9). Changes build on plan, never queue (G15, G16). `state.pulled` saves pulled ids. `RunState` gains `pulled` field. Dashboard snapshot replaces `in_progress` with `tier: "in progress"|"held"|"not started"|null`. `po_tools` (prioritise, move_story, start_sprint) check and record pulls. All tests pass (2 rounds, 99.41% coverage, ruff clean). See design `agile-team/docs/design/s51.md` (G1–G17, D1'–D5', test checklist). ADR-0016 amended.

## s65: Git confinement—roles can't reach team repo (AC1–AC10 all pass)

**Deliverable:** cli (runner's guard and role steps). New module `git_check.py`, changes to `guard.py`, `presentation.py`, `dispatch.py`. Design rules G1–G10, no new ADR (extends s41/s43/s69 guard pattern).

**Implementation:** Two layers stop roles' git from reaching the team repo:
1. **Environment (G2):** Confined steps (`e2e`, `acceptance`) get `GIT_CEILING_DIRECTORIES=<run_dir>` and `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1`, so git can't climb past `.team/run`.
2. **Guard (G3–G7):** New `git_check.git_denial()` sees through prefixes (`X=1`, `env`, `command`, etc.), decides *where* each git segment works (G5), and looks up `GIT_RULES` (G6) to allow/deny.

**Key rules:** Unconfined steps get read-only git (status/diff/log, no commit). Confined steps (presentation/acceptance) can use git freely inside their workspace (`git init`, `git -C demo …`, `git clone`). Any git targeting the team repo is denied with `GIT_OUTSIDE`, naming the repo. Git can't find the repo from the workspace (G2 ceiling). AC1–AC10 pass: environment stops discovery, guard stops explicit access, prefixes are seen, workspace survives bounce.

See design `agile-team/docs/design/s65.md` (G1–G10, test checklist).

## s89: Unit suite passes on 3.13 (OS guard refined, test infrastructure only)

Bug fix: 36 tests failed on 3.13 with "unit test reached the real OS: open (filesystem)" when formatting tracebacks. Root cause: Python 3.13's `linecache`/`traceback` read source files via a different path that the guard charged to the wrong caller. Guard refined with rules T1–T6: source reads by stdlib modules (`traceback`, `linecache`) inside a guarded frame (agile_team/tests) are now allowed. Real `agile_team` code that reaches the OS still fails. **No runtime changes, no new ADR.** See design `agile-team/docs/design/s89.md`.

AC1–AC3 pass: 3.13 and 3.12 unit suites green, traceback formatting works, guard still catches real OS calls. AC4 (CI on PR #16) verified at s81 boundary.

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
