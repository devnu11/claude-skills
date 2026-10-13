# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-13 (s109 done; s107 done; s53 done; s99 done; s98 done; s105 done; s103 done; s104 done; s86 done)

See `developer.md` for the base conventions.

## s109 complete: Dashboard groups models by family (AC1–AC3 pass, no new ADR)

"Time by Model", "Tokens by Model", "Spend by Model" charts now show one row per model family (opus, sonnet, haiku) instead of splitting alias and exact version into separate rows. Aliases and exact ids of the same family sum into one row. Tooltips list exact versions with their shares; steps with no recorded model show "version not recorded". Implementation is view-time only: snapshot records `recorded_model` on each step (what was logged), dashboard applies `familyOf()` and `versionOf()` functions at build time. History is untouched. No new CLI or config. See design `agile-team/docs/design/s109.md` (MF1–MF8).

## s107 complete: Suite runs feature—story frontmatter declares repeated test runs (no new ADR, extends s69/s99 patterns)

New `suite_runs.py` module (pure + I/O) and gates integration (SR1–SR7). **What changes:** Story frontmatter gains optional `suite_runs: N` (1–10). Runner executes on `done` at the suite step (e2e, or implement if no e2e). Command runs N times in a row; stops on first non-zero exit; all N pass → reason extended with pass text + times; one fails → BOUNCE with failure details and tail. Runs inside `gate.suite-runs` stage. Dashboard's implement-gate node gains `"gate.suite-runs"` to its stages list. Results are kept in `Ran("suite-runs", ...)` and shown in briefs. **Modules:** New `suite_runs.py` (Wanted, SuiteRun classes, wanted/declared/suite_step/summary/report/passed_text functions). Changed: gates.py (Checks.after_suite_runs, _run_suite, _suite_outcome), dispatch.py (_keep_runs), cli.py (suite_runs wired), dashboard/index.html (node stages list), results.py (BRIEF_RESULTS pins). **No new ADR** (extends s69 runner results and s99 stages patterns). Coverage ≥95%, ruff clean.

See design `agile-team/docs/design/s107.md` (SR1–SR7, F1–F7 e2e, test checklist).

## s99 complete: Runner stages named, timed, and data-driven (ADR-0048, no new ADR per design extends s44/s98)

The runner's internal stages (quality checks, boundary syncs, service starts, presentation trials) are now named and timed. **What changes for you:** New CLI command `agile-team tools` lists the 21 built-in runner stages and any repo tools defined in `.agile-team.toml`. Each stage run is logged to `events.jsonl` as a `runner-stage` event with timing, command detail (80 chars, secrets masked), exit code, and exception name if raised. **Modules changed:** New `stages.py` (pure data), new `stage_log.py` (timing/events). Changes to gates, dispatch, commands, git_ops, upstream, sandbox (all add stage opens/notes). **Test scope:** Stage table pins (21 members, unique names matching regex), unlisted stages fail, one event per run, choke-point notes (Git, shell, upstream, sandbox, Preparer). No new dependency, no ADR (extends s44 meter and s98 span patterns). See design `agile-team/docs/design/s99.md`.

## s105 complete: Dashboard presentation seeds config in empty workspace (no new ADR, extends s26)

Dashboard presentations now start in empty workspaces without manual config setup. **Implementation:** `Delivery` gains an optional `seed: str | None` field (before `probe`). Packaged seed directory `agile_team/dashboard/seed/.agile-team.toml` holds a minimal valid config with `[dashboard] token = "presentation"` (t31). The runner plants the seed into presentation workspaces where missing (two points: source workspace via `presentation.lay_out`, sandbox copy via `sandbox.Preparer.prepare`). Existing files are never overwritten. New module `seeds.py` handles seed resolution, planting, and problem checking; `DEFAULT_SEEDS` table maps `web` delivery kind to `PACKAGED_SEED`. When a presentation fails to start, the gate's reason names broken files and their fix (e.g., `workspace/.agile-team.toml is broken: … Fix it …`). Tests pass on units/code-review. AC1–AC3 pass: empty workspace + prepare answers `/api/snapshot` 200, own config kept, broken files named. No new dependency, no ADR (data extension, no branch).

## s103 complete: Guard accepts named test output redirection, refusals name rules (no new ADR)

Guard now allows redirected test output: `pytest -q tests/test_x.py > out.txt`, `>> out.txt`, `2> err.txt`, `| tee out.txt`, and `< /dev/null` forms keep a test run's output. Full-suite runs (`pytest > out.txt` with no test name) are still refused. When the guard refuses a command, the reason names the rule violated and the allowed form (e.g., `"refused by rule 'full-suite': … Allowed: named tests, e.g. 'pytest -q tests/test_x.py::test_y'; to keep output, add '> out.txt' or '| tee out.txt'"`). This makes refusal messages clear and actionable—no guesswork on which command is allowed. Role files no longer say "use `timeout` command" (macOS lacks it); they say "use the Bash tool's `timeout` parameter" instead. No new guard rules, no new dependencies.

## s86 complete: Story dependencies as data (ADR-0046)

New module `dependencies.py` (pure + file I/O, ~350 LOC). Story files gain `depends_on: [s1, s2]` list in frontmatter (DP1). Loaded at three points: `cmd_start` (DP3, via `_load_dependencies`), `start_sprint`, and `open_story`. Validated as a graph: shape, self-reference, unknown ids, cycles (DP4, DP7, texts exact). Router skips stories waiting on undone dependencies (DP9, `_movable`). Backlog tab shows depends/waiting and warns on misordered stories (DP13, DP14); `priority` events get `warnings` on reorder (DP12). Migration complete: prose "Depends on sN" → frontmatter list, drop-done rule applied, table-M stories done (DP15). Tests pass; design rules DP1–DP15 enforced. ADR-0046. See design `agile-team/docs/design/s86.md`.

## s85 complete: The liaison's opinion recording commands (two new, no ADR)

Two new CLI commands for the liaison: `agile-team opinion <story> <kind> <source>` and `agile-team reviewed <source>`. Opinion text comes from a file or stdin (`-`); kind is one of keep, move-up, move-down, fold, close, scope, ask. On success, appends to `liaison/opinions.jsonl` and prints the opinion id. `reviewed` similarly appends to `liaison/reviews.jsonl` with a backlog review summary. Both refuse unknown story, unknown kind, or empty text with exact error messages. Works while run is stopped. Design O2–O4; ADR-0045.

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

## s98 complete: Every agent's tool calls are recorded, the PO's included (no new ADR, extends s44/s96/s97)

Tool calls (spans) are now recorded to `.team/run/tools.jsonl` for every agent and the PO. **What changes:** Each span records who (role, story, step), what (tool name, label, detail), when (start wall/monotonic time and awake seconds), how it ended (ok/error/timeout/unfinished). Labels are named (`po.run_role`, `runner-tool.run_tests`) or `Dev: <reason>`. Detail (first 80 chars) masks secrets (`*TOKEN*`, `*KEY*`, `*SECRET*`). Step-end events gain `tool_s`, `model_s`, `waiting_s`, `opened_at` fields; new `po-turn` events record the PO's split with `waiting_s` (time inside po.run_role). Snapshot gains a `tools` section: spans grouped by step, shortest calls gathered under `collapse_under_s` (default 0.1s). New module `tool_calls.py` (pure), changes to `live.py` (Reading gains calls, platform, start, end fields), `dispatch.py` (step-end gains time split), `po_tools.py` (emits po-turn), `config.py` (collapse_under_s setting), `dashboard/tool_groups.py` (gathering logic), `dashboard/snapshot.py` (tools section). No new dependency, no ADR. See design `agile-team/docs/design/s98.md`.

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

## s104 complete: Flow chart labels pile up fixed (ADR-0047)

**Bug fixed:** Flow chart labels were piled at the top-left corner in Story scope, boxes empty. **Cause confirmed:** WebKit compositing bug—opacity on dimmed nodes renders the label layer at SVG origin (0,0), not inside the box. Sprint/Run rendered correctly (different dimming logic).

**Decision:** Dim nodes by colour only (fill/stroke/color), never opacity/filter/transform/mix-blend-mode (FL1–FL2). Add `used: bool` field to roles (FL7); draw only used roles (FL8). Natural-size Mermaid config (useMaxWidth: false), 16px font, scroll sideways (FL5–FL6). Roles with no stats show "idle" (FL4). All rules FL1–FL9 enforced in code; no new dependency, no new ADR (extends s27/s4 pattern).

**Changes:** `snapshot.py` adds four functions (_assigned_developers, _routed_roles, _stepped_roles, _used_roles) and `used` field to roles; `index.html` fixes CSS, adds idleClassDef(), statsText(), natural-size Mermaid options. Fixture adds developer-db with used: false.

No new CLI, no new hand-over. All tests pass (unit/code-review done; e2e P1 pending for integration-tester). See ADR-0047, design `agile-team/docs/design/s104.md` (FL1–FL9).

## s53 complete: PO story admin tools—hold, release, request_cancel (no new ADR, follows s83/s51 patterns)

New module `story_admin.py` (pure rules + `Clerk` I/O class) and `holds.py` (dataclass). Three MCP tools: `hold_story(story, reason)`, `release_story(story, reason)`, `request_cancel(story, reason)`. **Implementation:** PO holds are their own field (`StoryState.po_hold: PoHold | None`, not the hand-over hold). Hold posts nothing to outbox; holds and release use data-driven `TOOLS` table with shared refusal helper (`priority.first_refusal`). Cancel request posts one question and waits for human's answer. Rules H1–H13 in `story_admin.py` design spec. `po_tools.py` routes all three through `Clerk(runtime).run(act, args)` and `wait_for_answers` settles answered cancels. New `StoryStatus.CANCELLED = "cancelled"` (finished). Dashboard snapshot adds `po_hold` field and `wait.title`. No new dependency, follows s83 desk pattern (pure module + I/O class) and s51 refusal helper pattern. See design `agile-team/docs/design/s53.md` (H1–H13, test checklist).

## Context reduction (s23, s71)

Design file is your contract. Read source only for what the design leaves open. Grep with `-n`, read with `offset`/`limit` to avoid re-reading. Never run full suite; use `run_tests` tool for specific tests.
