# Integration Tester: Current context and conventions

**Last updated:** 2026-10-13 (s109 done; s107 done; s53 done; s102 tests done; s101 P1 pending; s100 P1 pending; s99 done; s98 done; s105 done; s103 done; s92 node-harness P1 pending; s97 P1 pending; s104 P1 pending; s96 P1 pending; s86 P1 pending; s85 P1 pending; s84 P1 pending; s83 P1 pending)

## s109 complete: Dashboard model family grouping—AC1–AC3 acceptance tests pass (all pass)

**AC1–AC3 verified on real dashboard:** Every chart with Model grouping shows one row per family (opus, sonnet, haiku); aliases and exact versions are summed under the family name. Tooltips list exact versions with their shares, and steps with no recorded model show "version not recorded". Family mapping is in index.html as data tables, no history rewritten. Design rules MF1–MF8 enforced; AC3 test (alias + exact-id → one row) pinned. No new ADR (extends s96 snapshot patterns).

See design `agile-team/docs/design/s109.md` (MF1–MF8).

## s107 complete: E2E test fixes—readiness waits replace fixed sleeps (AC1, AC2 pass; AC3 to runner gate)

**File:** Tests refactored in `tests/e2e/` directory (readiness.py new, per-test-file updates). **Design checklist (F1–F7, all AC1–AC2 verified; AC3 is the runner's 5-run gate):**

**Readiness module (F1, F5):** New `tests/e2e/readiness.py` with `STARTUP_S = 120.0` monotonic deadline, `POLL_S = 0.05` polling interval. `wait_until(check, what)` polls a condition; `Output` class reads child's merged stdout on daemon thread; `Output.wait_for(pattern)` waits for a regex match or fails at deadline with output and exit code; `dashboard(Launch)` context starts the CLI with local args, waits for DASHBOARD_URL pattern, yields proc/output/url, kills on exit; `serving(handler)` starts in-thread HTTP server, waits for TCP connect, returns server. All timeouts include child output on failure (F2–F5).

**Test changes (F2–F4, F6):**
- **F2 (no fixed sleeps before assertions):** `time.sleep` calls removed before assertions that load can break. Sleeps ≥0.05s that wait for something become `wait_until`. Minimum-duration sleeps kept (load only helps). Minimum-age checks in lists.
- **F3 (no tight wall-clock bounds):** Socket/stream/subprocess timeouts in e2e tests set to `STARTUP_S` (120s). Short limits on purpose are listed (test asserts they fire).
- **F4 (health driven, not waited for):** HEALTH_TOML gains large `amber_quiet_s = 300, red_quiet_s = 600`. Fake step meter advances its own quiet clock on command (`_go_quiet` writes and waits for ack). Green→amber→red test passes with slow host (stale 120s, test is unaffected by load).
- **F6 (stream reads stop on condition):** `_stream_health` reads distinct (level, reason) pairs until `done(seen)` is true; fails after `STARTUP_S` with `seen` list, never a fixed window.

**Test files updated:** `test_dashboard_e2e.py` (dash uses readiness.dashboard, _read_url deleted, _conn uses STARTUP_S, _read_until for stream, health tests use fake step), `test_s83_backlog_e2e.py` (served → readiness.dashboard), `test_s84_thread_e2e.py` / `test_s104_flow_e2e.py` (readiness.dashboard, --timeout 120, watch communicate timeout), `test_s85_opinions_e2e.py` (same as s84), `test_health_false_red_e2e.py` (Output.wait_for, wait_until for chore beat), `test_proxy_sandbox_e2e.py` (readiness.serving, CURL_MAX_S, CLI_S timeouts, TimeoutExpired handling), `test_command_timeout_e2e.py` (wait_until for child death), `test_unattended_wake_e2e.py` (wait_until for status JSON).

**Reviewed, unchanged (F2/F3 minimums):** `test_signal_own_groups_e2e.py` sleeps (0.2 nothing-check, 1.1 minimum), `test_s98_tool_spans_e2e.py` sleep (0.05 minimum duration), `test_command_timeout_e2e.py`/`test_signal_own_groups_e2e.py` (timeouts firing as assertions), `test_unit_limit_e2e.py`/`test_service_stop_e2e.py` (sleeps in child), `test_service_stop_e2e.py`/`test_service_presentation_e2e.py` (production readiness), proc.wait(timeout=10) after kill.

**AC3 (runner gate):** Story frontmatter has `suite_runs: 5`. E2e gate runs test command 5 times, all pass → "the test command passed 5 runs in a row (412 s, 398 s, …)"; acceptance brief shows suite-runs block.

Coverage ≥95%, ruff clean. See design `agile-team/docs/design/s107.md` (F1–F7, test checklist).

## s102 complete: Page tests for runner stages on Flow/Time charts (AC4, AC-R all pass)

18 node-harness tests written, all pass against fixture with rs4/rs5 (runner-stage events): SN1–SN4 stage nodes hexagons/edges/positions, SN2 drawn checks, SN5 stats per scope, SN7/SN8 running/active, SB1–SB3 share bars (model/tools split), TM2–TM8 time pieces/sources/runner row, RD1–RD3 measured text ≥12px with 4.5:1 contrast in both themes. Fixture complete, pages harness passes all items.

See design `agile-team/docs/design/s102.md` (test checklist, rules).

## s101: Node-harness tests for nested step expansion (P1, your work)

**File:** `tests/test_s101_nested_page.py` (new, under `tests/dashboard_node.run_page` setup).

**Design checklist (all via node harness, behaviour + readability):**

**Behaviour (N1–N6, AC1–AC5):**
1. **N1/N2 bar keys:** `barKey` of s3's live implement bar is `step:developer-cli:s3:<at>`, and the `e103` PO bar's is `po:e103`. `toolGroupOf` finds the live group for the live step, the interrupted group for the interrupted step, and the PO group for `e103`. A step with no group gives `null`.
2. **AC1 nesting:** With nothing open, s3's `data-row-label`s and every bar's `y` equal the s100 output. Opening the live step adds `<key>/model`, the lanes and misc right after the `developer-cli` row and before `PO`, and moves the `PO` row down by the nest's height. Opening two bars on one row orders their nests by `from`.
3. **AC1/AC4 stacking:** The parallel `Dev: Read` / `Dev: Grep` pair have different `data-lane`s. `slow` and `timed_out`, which don't overlap, share lane 0. Unit table for `callLanes`: touching calls share a lane, three mutually overlapping calls take three lanes.
4. **AC2/AC4 two-line label:** With a window wide enough, `slow`'s `<g data-call>` holds `tlText("call", "Dev: run the unit tests")` and `tlText("detail", …)`. With a narrow window it holds neither, and its `<title>` has the name, the detail, `started` and the duration. Calllines table: name fits but detail too short (<MIN_DETAIL_CHARS); detail cut with `…`; empty detail.
5. **AC3/AC4 states:** `timed_out` and the `Dev: Grep` error have `data-outcome` `timeout`/`error` and `--critical` fill. The interrupted step's call is `unfinished` with `fill="url(#tl-…-unfinished)"`. The heartbeat's open call is `open`, and its `data-to` equals `now`. At `now + 60` its `data-to` grows by 60.
6. **AC4 PO wait:** Opening `e103` shows a `po.run_role` call with `data-outcome="waiting"` and detail `developer`. The PO's model row label reads `model · 9.5 s`, taken from `data.model_s`. The model pieces don't cover the call's `[from, to]`.

**AC5 and state:**
7. **N6 model pieces:** The live step's model pieces are the bar's span minus the union of its calls, including the open one. With no `step-end`, the label is the pieces' measure.
8. **N3 none:** Opening an s1 step (no tools data) draws one `no tool calls` line and no call or model bars.
9. **AC5 misc:** The live step's nest has one `data-misc` box, whose text is `misc · 3 calls · 0.04 s`. Its `<title>` starts with `MISC_TITLE` and lists `Read 2 · Grep 1`. It has no `data-from`/`data-to`. Its rect `x` is the same in two different windows (zoomed and panned). The interrupted step has no misc box.
10. **AC5 on demand:** Stub `globalThis.fetch` to return `ok` with a two-row array. A click on `[data-tl-misc]` fetches `api/misc?role=developer-cli&story=s3&step=implement&opened_at=<…>` once, and `miscListHtml` then has two `li[data-misc-call]`. A second open uses the cache and fetches nothing. A rejecting fetch shows `could not load the calls`, and `[]` shows the "moved on" note. Nothing is fetched before the click.

**Replay and controls (N14, N13):**
11. **N14 replay:** `toolsAsOf` at a cursor inside `slow` turns it `open` with `ended_at: null`, and drops calls and groups after the cursor.
12. **N13 toggle:** `toggledKeys` table (add all, remove all when all are open, mixed → add). A click on the `developer-cli` row label opens every developer-cli bar of s3.
13. **N15 SVG ids:** Two timelines open (s2 and s3, Sprint scope) have no repeated `id` attribute (prefixed by story).

**Readability (AC-R, measured):**
14. **AC-R:** Extend the s100 TR helper. Parse `timelineHtml` for s3 with the live step and `e103` open, a wide window and an open misc list (stubbed loaded). Every text node outside `<title>` has ancestor `data-text` in `TL_TEXT`, rendered size ≥12 CSS px, contrast ≥4.5:1 against `--surface` in both themes. `call`, `detail`, `misc` are in `TL_TEXT`.

**Coverage:** All 14 checklist items (design lines 267–308) verified via node harness. No process/e2e tests written (behavioural tests spawn node). Ship story when these land.

See design `agile-team/docs/design/s101.md` (N1–N15, test checklist), review round 1 (ship with P1 pending).

## s100: Node-harness and measured tests for timeline behaviour and readability (P1, your work)

**File:** `tests/test_s100_timeline_page.py` (new, under `tests/dashboard_node.run_page` setup).

**Design checklist (all via node harness or measured page tests):**

**Behaviour (TL1–TL16):**
- **TL2:** s1 (done) range from story-opened to done gate's at, running=false. s3's range ends at now (running=true). No events → note text, no SVG.
- **TL4/AC1:** s3's rows are its roles in RING_ORDER, then PO, then runner. Injected ruling for s3 adds manager row.
- **TL5/AC2:** Bounced steps have data-outcome="bounced"; passed steps "passed"; test-dispute adds "disputed"; running step "running"; data-to equals now for running.
- **TL6:** rs1 stage bar "failed" on runner; checkout.guard (s2) "ok"; boundary.sync (story=null) not in any story group.
- **TL7:** po-turn touching s3 gate is PO bar for s3 (not s1); po-turn with outbox message naming s3 also touches s3.
- **TL8/AC5 bounce arrow:** s2's review bounce draws data-arrow="bounce" from code-reviewer to developer row. s3 bounce to itself has same row. Bounce with no next step draws no arrow (tooltip says "back to"). Window after next step clips arrow (none drawn). Arrow inside window sits in clip-path group.
- **TL9:** s7's fault (e90) is data-mark="fault" on manager.
- **TL10/TL11/AC5 waits:** asleep (s3 sleep row), question (m3 on s3, open → now), hold (s4 e79 → next step or now), other (s3 gap while s1/s2 step, label lists ids, depends_on id has "(dependency)"), idle (no wait). Precedence: sleep inside question is asleep.
- **TL12:** s1 architect step's sleep band draws data-sleep over bar span.
- **TL13/AC5 totals:** s3 work = Σ steps + running, runner excludes during, po = Σ tool_s + model_s of touches, waiting = gap pieces, asleep = clipped union. Numbers exact, data-total keys in TOTALS order.
- **TL14/AC5 Sprint scope:** Groups are sprint-1, then s1/s2/s3/s4 in view.stories order. boundary.sync (story=null) in sprint-1's runner. Turn touching s2 and s3 counts once in po. Sprint disabled for s5 (no sprint).
- **TL15:** zoomed in/out/fit and pannedBy (pure state). Wheel with ctrl zooms, shift pans, plain vertical does nothing.
- **TL16/AC5 live now line:** Fixed window (end set), now T→T+600 moves data-now x right. Following (end=null), running bar right edge and now line share x. Done s1 no data-now.

**Readability (AC-R, TR1–TR5, measured):**
- **TR1–TR4:** Parse timelineHtml (s3 story and sprint scope) as HTML. Every text node outside <title> has ancestor with data-text in TL_TEXT. Inline font-size × (svg width ÷ viewBox width) ≥12 CSS px (measure computed style, not inline). Colour var resolved from `:root` and `:root[data-theme="dark"]` blocks, WCAG contrast ≥4.5 against --surface.
- **TR5:** FLOW_FONT_PX ≥12, useMaxWidth false, CSS scroll, idleClassDef colour-only. Default node (--ink) on --surface ≥4.5. Stub getComputedStyle with theme values.

**Coverage:** All checklist items (design lines 260–276) verified. No node/process tests written yet; all via node harness and measured page checks.

See design `agile-team/docs/design/s100.md` (test checklist, TL1–TL5, TL7–TL16, TR1–TR5), review round 2.

## s99 complete: Runner stages—naming, timing, events (all ACs verified; P1 e2e with real repo)

**Verdict:** Unit/code-review done (all pass). Design rules RS1–RS14, AC1–AC4 verified on captured test runs. **Your P1 work:** Write `tests/e2e/test_s99_stages_e2e.py` to verify: (1) Runner-stage events written to events.jsonl during a step; (2) Each stage run produces one event with exact keys/order; (3) Timing (started_at, started_mono, started_slept, seconds) is positive and reasonable; (4) Command detail masked secrets, clipped to 80 chars; (5) Real choke points (Git.\_exec, CommandShell.run, upstream.run, sandbox.run\_shell, Preparer.\_serve) write notes. Fixture schema available. No new sandbox changes.

## s98 complete: Snapshot tools section, served correctly (all ACs verified; P1 e2e pending)

**Verdict:** Unit/code-review done (all pass). Customer proxy reported AC1–AC3 done (sample tools.jsonl matches spans, labels, masked token). AC4–AC6 verified by team test results. **Your P1 work:** Write `tests/e2e/test_s98_tools_e2e.py` to verify: (1) tools.jsonl written during a step; (2) tools section present in served snapshot; (3) gathering works (short calls grouped under collapse_under_s threshold); (4) role/story/step/opened_at grouping; (5) misc entry with count/seconds/tools dict. Check that snapshot `tools` array matches tools.jsonl data (contracts match). Fixture schema available. No new AD or sandbox changes.

## s105 complete: E2E tests for presentation seeding (file `tests/e2e/test_presentation_seed.py`, AC1–AC3 pass)

**File:** `tests/e2e/test_presentation_seed.py` (new).

**Design checklist (all AC1–AC3 via real repo, real Preparer, test dashboard via fetch):**

1. **AC1 (packaged seed, today's config):** Load repo's `dashboard` delivery (seed is None, seed_dir → PACKAGED_SEED). Empty presentation workspace + `Preparer().prepare` → `GET /api/snapshot` replies 200 (unpacked config works). Workspace holds `presentation/workspace/.agile-team.toml` with S5 text. `prepared.stop()` returns None.

2. **AC1 (own config preserved):** Workspace with own `.agile-team.toml` (`token = "mine"`) + prepare → file unchanged, snapshot still 200 (existing never overwritten).

3. **AC3 (broken file diagnosis):** Workspace config `"[dashboard\n"` (unparsable) + prepare/liveness → `NotUp` reason contains `workspace/.agile-team.toml is broken` and `Fix it … delete it …` text (S7 rule enforced).

Setup: tmp_path repo, `isolated_git` fixture, real `config.load` (do not load real `.agile-team.toml` as Config.repo; use scratch). No test harness; fetch/stop real. AC1–AC3 pass (customer-proxy verified all pass). Coverage ≥95%, ruff clean. No test deleted.

## s103 complete: E2E test output redirection allowed; refusals name rules (no new ADR)

Your e2e test runs can now save output with redirects: `pytest tests/e2e/test_x.py > out.txt`, `| tee out.txt`, and similar forms. Full-suite runs are still refused. When the guard denies a command, it now names the rule violated (e.g., `"refused by rule 'full-suite': the full suite is the runner's to run: it runs it at the gates and puts the output in your brief (## Runner results). Allowed: named tests, e.g. 'pytest -q tests/e2e/test_x.py::test_y'; to keep the output, add '> out.txt' or '| tee out.txt'"`). This clarity helps you avoid retries on guesswork. Role files no longer mention `timeout` command (macOS has none); they use the Bash tool's `timeout` parameter. No new guard rules or dependencies.

## s92 P1: Node-harness tests for gate routing to e2e test owner (your work)

When implement gate fails with an e2e test failure (pytest FAILED in tests/e2e/), the runner routes it to you as a gate fix step. Your brief lists only the e2e items, exact pytest output, and the design rule if the developer cited one. Fix only those items (update the e2e test), then hand off `done`. The queue pops, story returns to developer, no round counted. **Your P1 work:** Node-harness tests for `STATUS_TONE.route = "warning"`, the `gate` row with route verdict showing which roles fix next, and the `gate-fix` row showing your role, status, and files. See checklist items in design `agile-team/docs/design/s92.md` § Test checklist, Page section.

## s97: Node-harness tests for awake-time page display (unit/code-review done, P1: your work)

**File:** `tests/test_s97_awake_page.py` (new, under `tests/dashboard_node.py` setup).

**Design checklist (all via node harness, 4 items):**

1. **Running line awake/wall (AW10):** With `clockNow - step.at = 600s`, `step.slept = 120`, `clock = "awake"`, `runningLine()` reads `⏱ running 8 min`. Same step with `clock = "wall"`, `slept = 0` reads `⏱ running 10 min (may include sleep)` (AW10).

2. **Time chart wall count (AW11):** `timeBy` builds groups with `wall` sum. Tooltip for a group with wall steps says `· N may include sleep`. Group with no wall steps has no mark. `timeRow` renders exact text.

3. **Legend text (AC4, AW12):** `timeLegend()` contains exactly "Awake time (agent steps only; runner stages: see A6)".

4. **Replay reopens (AW13):** `stepsAsOf(view, step)` nulls `clock` and `slept` when reopening a step, so replayed steps show wall time unmarked (clock=null, slept=null).

See design `agile-team/docs/design/s97.md` (test checklist, AW10–AW13).

## s104: E2E tests for Flow chart fixes (unit/code-review done, P1: your work)

**File:** `tests/e2e/test_s104_flow_e2e.py` (new). Cause and rendering checks run on fixture via node harness (dashboard_node.run_page). Served-snapshot AC5 test real dashboard.

**Design checklist (all via node harness + served dashboard):**

1. **AC4 (cause):** On fixture, Story scope with focus that dims ≥1 node, and Sprint scope on same data:
   - No `classDef` line contains `opacity`, `filter`, `transform`, `mix-blend-mode` (FL1, FL2).
   - `classDef idle` sets only `fill`, `stroke`, `color` (exact text).
   - This check **fails on today's code** (test confirms fix works).

2. **AC4 (hidden then shown):** Stub `mermaidModule` to record `initialize` options and `render` sources.
   - With `ui.tab = "board"`, call `render()`; stub records nothing.
   - Call `showTab("flow")`; let microtasks run.
   - Expect one `initialize` with `flowchart.useMaxWidth === false`, `themeVariables.fontSize === "16px"`.
   - Rendered source passes FL1 check (no opacity).

3. **AC3 (size):** `parseFloat(mermaidConfig(themeVars()).themeVariables.fontSize) >= 16` and `useMaxWidth === false`. Box stats ≥ 12 CSS px.

4. **AC2 (idle text):** Story scope, role with no totals and no open step has label `· idle`, not `$0.00`. Role with totals still shows `tokens · $ · time`.

5. **AC5 (unused roles):** With `developer-db` `used: false`, `flowSource` has no `developer-db` node. With `used: true`, has one. Role with no `used` key still drawn.

6. **S96 labels:** Running box shows `⏱ running <time>`. Existing s96 expectations still hold.

7. **Served snapshot AC5:** Serve on scratch repo. Snapshot has no `developer-db`. Append `step-start` event for `developer-db` to `events.jsonl`. Next `/api/snapshot` has it `used: true` and `flowSource` draws it (AC5, FL9).

See design `agile-team/docs/design/s104.md` (test checklist items in E2E section), ADR-0047.

## s96: Node harness and e2e for Flow time display (unit/code-review done, P1: your work)

Code shipped. Unit tests pass (23 tests, coverage ≥95%, ruff clean). Code review done (all ACs pass). **Your work (P1): node-harness tests and e2e for active running line.**

### Node harness tests (`tests/dashboard_node.py`, four test functions from design checklist items 7–9, 14–15)

**Setup:** Load fixture with time steps (agent steps with different durations).

1. **Scope toggle (ST10):** With `ui.scope` set to `story`, `sprint`, `run`, `scopeTotals(view)[role].seconds` matches hand-computed sums for the fixture (AC5, ST10).
2. **Box time (ST10, ST11):** `nodeLabel` for a role contains `fmt.span` total. Running role with open step started 600s before `clockNow` gives `runningLine` with `"⏱ running 10 min"`.
3. **Time chart (ST12–ST14):** `Object.keys(UNITS)` is `["tokens", "usd", "time"]`; `UNITS.time.label="Time"`, `title="Time by"`. With `ui.unit="time"`, `renderUnit` writes three buttons and title. `barRows` largest first; `timeRow` tooltip has step count and `% of time`; value is `fmt.span`. `timeLegend()` text exact `"agent steps only; runner stages: see A6"`.
4. **costRow unchanged:** Dollars display unaffected by the `whole` parameter rename.

### E2E test for active running line (real dashboard, 60s timeout)

**File:** `tests/e2e/test_s96_running_time_e2e.py` (new).

**Test:** Open dashboard on Flow tab. Let a step run (or mock one open in snapshot). Verify: active box shows `⏱ running 5 min` (or similar) **without a new snapshot arrival**, and the time increments roughly once per minute. Stop the runner or set a long clock offset to lock the display, verify time stops changing.

See design `agile-team/docs/design/s96.md` (test checklist items 7–9, 14–15).

## s86: E2E and node-harness tests for story dependencies (AC1–AC5 unit/code-review done, P1: migration pin and page harness)

Code shipped. Unit tests pass (coverage 99.46%, ruff clean). Code review done (all ACs pass except P1). **Your work (P1):** DP16 migration pin (AC4) and page harness tests (AC5).

### E2E: DP16 migration pin (AC4)

File: `tests/e2e/test_s86_dependencies_e2e.py` (new).

Read the real `.team/stories/*.md` bodies. Verify:
1. **Prose check:** Every file whose body matches `(?i)\bdepends\s+on\s+s\d+` must have id in `HISTORY` (done stories: s4, s5, s9, s29, s70, s76, s77, s79, s83, s84, s85 only). Assert matching ⊆ HISTORY.
2. **Migration table (DP15):** Each story in table M (s2, s6, s10, s16, s32, s33, s34, s35, s36, s39, s54, s55, s94, s95, s102) has `story_files[id].frontmatter['depends_on']` equal to table M's list (drop-done rule applied, so s39→[], s10→[], etc.). Assert exact match per story.

See design DP15–DP16 and table M for expected lists.

### Node harness: Dependencies on Backlog tab (AC3)

File: `tests/dashboard_node.py` (add to existing file, four test functions).

**Setup:** Load fixture with dependencies. Fixture story s2 depends on s1 (done), s5 depends on s2 (undone), s6 depends on s1 (done).

1. **Dependencies shown (DP14):** Backlog row for s2 shows `depends on s1 (done)`. Row for s5 shows `depends on s2`. Row for s6 shows `depends on s1 (done)`. Story with no depends_on shows no line.

2. **Waiting and done markers (DP14):** s2 and s6 (wait on nothing) have no `waiting_on` banner. s5 (waiting on s2) shows inline with depends line or as banner; no (done) marker on s2.

3. **Warning pills (DP14):** Fixture has s2 above s5 (inversion). Row for s2 shows pill `⚠ s2 is above s5, which it depends on` (exact text). s5 has no warning (depends on s2 which is below it).

4. **Timeline warnings (DP12, DP14):** `TIMELINE.priority` event where s2 moved above s5 has meta ` · ⚠ s2 is above s5, which it depends on` and tone `warning`. Event with no inversions has `warnings: []` and tone `default` (not `warning`).

See design DP11–DP14 for exact texts and warning logic.

## s85: E2E tests for liaison opinions (AC1–AC5 unit/code-review done, P1: node-harness and e2e tests pending)

Story shipped in code. Unit tests pass (coverage 99.46%, ruff clean). Code review done (all ACs pass). **Your work (P1): node-harness and e2e tests.**

### Node harness tests (dashboard_node.py, four test functions)

1. **Badge and filter (AC2):** With fixture (s6 move-down opinion, s5 scope settled), Backlog shows badges `liaison: move-down`, `liaison: scope`. Expanding shows kind, date, text. Ticking "only suggestions (1)" filters to s6 only; unfiltered positions and handles unchanged.
2. **Details (AC2, AC4):** s6 shows opinion details with kind, text, time; dismiss and apply buttons labeled "move to the bottom" (move-down) and "send to the PO"; buttons disabled without TOKEN.
3. **Review bar (AC3):** Shows "Last review: <time>" and summary, or "The liaison has not reviewed yet". With `asked_at` later, adds "Asked <time>; waiting"; button absent without TOKEN.
4. **Posting (AC3, AC4):** `postReview()` POSTs `/api/review` with `{}` and token header. `postOpinionAct(id, act)` POSTs `/api/opinion` with `{opinion, act, version}`. 409 response sets reason; OK clears note.

### E2E test (30s timeout, real dashboard --port 0 --token t)

POST `/api/opinion` with apply (dismiss similar). Expect 202 with id/status. For move-up on Backlog story, expect ref is a reorder id. For other kind, expect ref is a thread post id (route in answer).

See design `agile-team/docs/design/s85.md` (test checklist items 13–17), ADR-0045.

## s84: E2E tests for story threads (AC1–AC5 unit/code-review done, P1: node-harness and e2e tests pending)

Story shipped. Unit tests pass (coverage ≥99.44%, ruff clean). Code review done (all ACs pass except P1). Design rules H1–H19 all enforced.

**Your work (P1): node-harness tests and e2e for thread posting and liaison reply.**

### Node harness tests (`tests/dashboard_node.py`, three test functions)

**Setup:** Load fixture as `data.snap` with thread entries on story s5 from all four sources (human→PO, PO→human, human→liaison, liaison→human).

1. **Thread render (AC1, AC4):** `storyDetails("s5")` shows 4 entries in order (by time). Each has labels `"you → PO"` style and Markdown text (no nested `.md` div—fix m1). `NO_THREAD` text on story with no entries. With `TOKEN`, textarea/select/button present; without, read-only note. Select defaults to `"product-owner"`.

2. **`postThread` (AC1):** Blank draft sets `SEND_EMPTY` note, doesn't call fetch. Valid draft POSTs `api/thread` with `{story, to, text}` and `X-Agile-Team-Token` header. 403 response sets `READ_ONLY` note. 500 sets error text. OK clears draft and note. (Stubbed fetch, no real POST.)

3. **Timeline (AC4):** Timeline event for a thread entry shows `from: "you"`, `to: "PO"`, `what: "thread"`, body is Markdown text. Story filter in timeline includes thread entries for that story.

### E2E test for thread posting and liaison reply (REAL world, 30s timeout)

**File:** `tests/e2e/test_s84_threads_e2e.py` (new).

**Setup:**
- Real runner in a scratch team repo.
- State with at least one story (s5).
- Start dashboard with `--port 0 --token test_token`.

**Test:**
1. **POST to PO (AC1, AC2):** Make a real POST to `/api/thread` from `127.0.0.1` with:
   - Headers: `X-Agile-Team-Token: test_token`, `Content-Type: application/json`.
   - Body: `{"story": "s5", "to": "product-owner", "text": "Can you review this?"}`.
   - Expect 202 with `{"id": "t1", "status": "posted"}`.
   - Verify: `liaison/messages/t1.md` exists, begins with head `<!-- thread story=s5 at=<time> -->`, contains "Can you review this?".

2. **Watch wakes on liaison post (AC3):** POST to liaison: body `{"story": "s5", "to": "liaison", "text": "Any questions?"}`. Expect 202 with `{"id": "lp1", "status": "posted"}`. Call `agile-team watch --timeout 30` in another process/thread. Expect within 5s: `{"triggers": ["liaison_message"], "posts": [{"story": "s5", "text": "Any questions?", "at": <time>, "id": "lp1"}]}`.

3. **Liaison replies (AC3):** Call `agile-team reply s5 -` with text "Sure, all good." on stdin. Expect stdout `"replied lr1 on s5"`, exit 0. Verify: `liaison/replies.jsonl` has one line `{"story": "s5", "text": "Sure, all good.", "at": <time>}`.

4. **Thread in snapshot (AC4):** Call `GET /api/snapshot`. Expect `"thread"` array with 3 entries: t1, lp1, lr1, in time order. Expect `"events"` includes 3 `thread` events (ids `thread-t1`, `thread-lp1`, `thread-lr1`), no `message` event for the `reply` outbox line (if any).

**Coverage:** Verifies localhost + token gate (202), file writing, watch trigger, CLI reply, and snapshot merge.

See design `agile-team/docs/design/s84.md` (test checklist items 14–16, e2e), review round 2, ADR-0044.

## s83: E2E tests for Backlog tab (AC8, P1: node-harness and e2e tests pending)

Story shipped. Unit tests pass (coverage ≥95%, ruff clean). Code review done (all ACs pass except P1, which is your work). 

**Your work (P1): node-harness tests and e2e for dashboard reorder.**

### Node harness tests (`tests/dashboard_node.py`, four test functions)

**Setup:** Load fixture as `data.snap` with backlog stories (s5, s6 in sprint 1; s50, s51 in backlog).

1. **Expand/collapse (AC2):** `toggleRow("s5")` → expanded with story file content and state fields. `aria-expanded="true"`. `toggleRow("s5")` again → collapsed, details gone. Prelude's `fetch` rejects (offline), so story file shows `no story file`.

2. **Handles (AC4):** Backlog rows (s50, s51) have `<button data-move="up|down|top">`. Current-sprint rows (s5, s6) have no `data-move` buttons. Without TOKEN, no row has handles and note reads "read-only" text.

3. **`moveTarget` edges (B9):** From place P (1-indexed):
   - `moveTarget("up", 1, 2)` → null (already first).
   - `moveTarget("up", 2, 2)` → 1.
   - `moveTarget("down", 2, 2)` → null (already last).
   - `moveTarget("down", 1, 2)` → 2.
   - `moveTarget("top", 2, 2)` → 1.
   - Invalid place or action → null.

4. **`reorderNote` cases (B16):**
   - Pending: "waiting for the runner: moves apply between steps".
   - Applied: clears note (empty string).
   - Refused (generic): shows reason text.
   - Refused (STALE): shows reason + reload button with `data-reload` (calls `location.reload()`).
   - No token (403): "read-only: open the link the dashboard printed (it carries the token), on this machine".
   - Other HTTP error: status number (e.g., "404").
   - Network error: error message or generic "network error".

Bonus (from review D2): **No drag posts while pending.** Fixture has request with status="pending". `ui.reorder` set. Drop on another Backlog row posts nothing.

Bonus (from review D4): **Commits shown.** Give a fixture story a `commits: ["abc123"]`. Expanded details show it under state fields.

### E2E test for reorder request (REAL world, 30s timeout)

**File:** `tests/e2e/test_s83_reorder_e2e.py` (new).

**Setup:**
- Real runner in a scratch team repo (via `isolated_git` + `scratch_team`).
- State with sprint and backlog stories.
- Start dashboard with `--port 0 --token test_token`.
- Verify server is listening and token in URL.

**Test:**
1. Make a reorder POST from `127.0.0.1` to `http://localhost:<port>/api/reorder` with:
   - Headers: `X-Agile-Team-Token: test_token`, `Content-Type: application/json`.
   - Body: `{"story": "s50", "position": 1, "version": "<current_version>"}`.
2. Expect 202 response with `{"id": "r1", "status": "queued"}`.
3. Let router run one tick (call `router._tick()` or wait one heartbeat).
4. Check: `state.reorders["r1"] == "applied"`, order changed (s50 moved), event emitted with `source: "human (dashboard)"`.
5. Snapshot now shows `reorders[0].status == "applied"`, `reorders[0].story == "s50"`.

**Coverage:** Verifies request queueing (202), routing's apply (event, order, state), and snapshot reflects the change.

See design `agile-team/docs/design/s83.md` (test checklist items 18–23), review round 4, ADR-0043.

## s15: E2E tests for Markdown rendering (10 cases, all pass)

Story complete. Dashboard Markdown rendering via markdown-it now tested offline with vendored library copy. File: `tests/e2e/test_dashboard_markdown_e2e.py`.

**What to verify:**
- **Pin and copy agree (AC4):** Parse `MARKDOWN_URL` from page script, version matches `markdown-it-<v>.min.js` file.
- **Syntax (AC1):** All elements render (headings, paragraphs, lists, emphasis, code, tables, links) and output starts with `<div class="md">`.
- **Links (AC2):** https/http links get `target="_blank"` and `rel` with `noopener`, autolinks work.
- **Payloads inert (AC2):** 14 inputs (script, onerror, javascript:, data:, vbscript:, mailto:, relative, image, iframe, escaped quote) render with no `on*` attrs, no unsafe schemes in href, all tags in safe set, script input shows `&lt;script&gt;`.
- **Plain fallback (AC4):** Unloaded `md()` returns `<div class="md plain">` + escaped text; null/undefined give empty div.
- **Load failure (AC4, M8):** Node import fails (offline), promise resolves, markdown stays null, `md()` stays plain.
- **Questions use md (AC3):** Open/raised/answered questions render with Markdown (bold, code, lists in q-answer).
- **Timeline picks by kind (AC3, M10):** step-end/message/answer use md; gate/hold use esc.
- **One function, no copies (AC1, M1):** `markdownit(` once, `function md(` once, `.render(` on markdown once (regex `\bmarkdown\.render\(`).
- **Old rule updated:** E2E URL scan verifies exactly two pinned URLs (Mermaid + markdown-it).

Use `dashboard_node.run_page()`, vendor copy in tests/ with `useMarkdown(require(...))` (CommonJS under node). Parse HTML output with `html.parser`. No node? Hand off blocked; ask for file.

See design `agile-team/docs/design/s15.md` (rules M1–M12, test checklist), ADR-0042.

## s51: E2E test for router priority ranking (AC7 pending, unit and review complete)

Story complete on units (coverage 99.41%, ruff clean) and code review. E2E tests belong here. Design calls for one case: with started and not-started stories, router picks the started one first. File: (tbd) router e2e test. **Setup:** state with 4 stories (order=["s45", "s38", "s21", "s50"], s45/s50 not started, s38/s21 started with commits). **Test:** Router calls `dispatch.router()`, first routable story is s38 (not s45). When s38 held, s21 is next. When s38 released, s38 is next again. Covers AC1 (in-progress first) and AC4 (held story skipped).

## s65: Git confinement—build demos in the presentation workspace (AC9 e2e test, all pass)

Story accepted. Runner now isolates roles' git to prevent reaching the team repo. **For your presentations:**
- **Workspace location:** `.team/run/presentation/<story>/workspace`. Runner creates it with `git init` on first use, keeps it on bounce.
- **Where git works:** Build demos *inside* `workspace/`. Commands that work: `cd <ws> && git init demo`, `git -C <ws>/demo commit …`, `git -C <ws>/demo rebase main`, `git clone demo copy`, `git -C <ws>/demo checkout -b topic`. Commits and pushes all allowed inside workspace.
- **What's blocked:** Git targeting the team repo or outside the workspace is denied: `git -C <team> status`, `cd <ws> && git clone /etc /tmp/x`. Git outside the workspace is read-only in your cwd only: `git status`, `git log` in the cwd pass; `git commit` in the cwd is denied.
- **Environment:** Git can't climb above `.team/run` (ceiling set by runner). If your demo has no `.git`, `git status` fails with "not a git repository", not reaching the team repo.

See AC9 e2e test design, `agile-team/docs/design/s65.md`. Workspace is your story's sandbox; keep it clean between steps (ACM: you may wipe it by overwriting files, but only you do).

## s59: E2E tests for rebase at sprint start (AC6, five cases, carried to this step)

Story complete on units and integration. Unit tests cover pairing, remap, rebase, conflict, push guard, sync_from order, group_files. E2E tests (5 cases on real git) belong here. File: `tests/e2e/test_s59_rebase_e2e.py` (30s timeout).

**Five cases (design test checklist, lines 217–222):**
1. **All already upstream:** Team commits A, B. Origin/main has A', B' (rebased copies). Sync gives `rebased`, HEAD equals origin/main, tree equals origin/main's, state.json story commits map to origin/main's sha.
2. **Copies plus new content (m54 case):** Team has A, then B editing A's lines. Main has A' (copy) and unrelated U. Merge would conflict; sync gives `rebased`, history is linear (no merge commits), B's content is kept, U is present, B's recorded hash is rewritten.
3. **Real conflict:** Main changes a line differently from team. Sync holds `sync_conflict`, HEAD unchanged, no `.git/rebase-merge`, hand-over lists files grouped by directory with count.
4. **Hash rewrite in state.json:** After rebased, every `REMAPPED` field holds a commit reachable from HEAD; `upstream.checked` unchanged; `state.checkout.head` equals HEAD.
5. **Hand rebase after conflict:** After conflict, test rebases by hand in clone and calls continue. Second sync is `current` by HEAD but remaps from `sync_from`, so story hashes point to hand-rebased commits.

**Setup:** Bare origin + clone, `set_git_identity`, `isolated_git` fixture. Never touch real home directory.

See design `agile-team/docs/design/s59.md` § Test checklist, AC6 (e2e cases), ADR-0041.

## s81: E2E test for CI with stub gh on PATH (AC7, carried to this step)

Story accepted. All ACs pass except AC7 (e2e test), which is your work. New file `tests/e2e/test_s81_ci_e2e.py` (REAL world, 30s limit).

**What to build:**
1. Stub `gh` script in `tmp_path/bin`, first on PATH via `monkeypatch.setenv("PATH", ...)`.
2. Stub records its argv to a file.
3. Answers: `pr checks N --watch` (exit 1), `pr checks N --json …` (one fail check with Actions job link), `run view --job J --log-failed` (log with `FAILED tests/x.py::test_y` line).
4. Test: `CiWatch(GhPrs(command_runner(tmp_path)), 30).results([entry])` → RED with that failing line.
5. Assert stub argv: `pr checks N --watch`, `--json name,state,bucket,link,workflow`, `run view --job J --log-failed`.
6. Never touch real HOME.

**Setup:** `entry = StackEntry(pr=5, mode=PrMode.READY, branch="review", url="https://…#5")`. Command runner uses `tmp_path` repo.

The test is integration (real CLI-like gh stub), not unit. Covers the full wait/read/log path. Existing `test_ci_git_e2e.py` test name available if needed.

See design `agile-team/docs/design/s81.md` § Test checklist, AC7.

## Scope (unchanged)

E2E tests only. Run by file name (`pytest tests/e2e/test_s81_ci_e2e.py`). Never full suite or `--cov`. Real OS and clock; 30s timeout. No monkeypatch for `system.<name>` (use real calls). Moved tests from unit use `parents[4]` (one more parent level). Coverage ≥95%, ruff clean.
