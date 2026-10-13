# Code Reviewer: Current context and conventions

**Last updated:** 2026-10-13 (s53 done; s102 done; s101 done, P1 tests pending; s100 done; s99 done; s98 done; s103 done; s92 done; s97 done; s104 done; s96 done; s86 done; s85 done; s84 done; s83 done)

## s102 complete: Runner stages on Flow and Time charts (1 round, all ACs pass) — verdict ship

**Scope:** `stage_log.py` (StageBoard protocol, Hidden class, open_row function), `live.py` (Pulse.showing, heartbeat.stages), `dispatch.py` (board=pulse assignment), `dashboard/index.html` (50+ functions SN1–SN8, TM1–TM8, SB1–SB3, RD1–RD4, ~1000 LOC), fixture. **Verdict: ship.** Coverage 99.53%, ruff clean. Gate fix: legend test assertion corrected (TM8 rule cited). **No new ADR** (extends s96/s101 patterns).

**Design rules enforced:** Stage nodes (hexagons, STAGE_NODES table, SN1–SN8) drawn from events/open rows, edges to anchors, stats per scope, running line with awake time, active node picks first running stage or PO. Heartbeat stages key (HB1–HB4). Time pieces from three sources (TM1–TM4), runner row, PO split (model/tools/waiting), share bars on nodes (SB1–SB3). Flow and bars at natural size with scroll (RD1–RD4).

See design `agile-team/docs/design/s102.md` (all rules SN1–RD4, test checklist).

## s53 complete: Story admin tools—pure rules + Clerk I/O (1 round, all ACs pass) — verdict ship

**Scope:** `holds.py` (new, HoldKind enum, PoHold dataclass), `story_admin.py` (new pure module, ~500 LOC, + Clerk class for I/O), changes to `gates.py`, `state.py`, `priority.py`, `dependencies.py`, `waits.py`, `backlog.py`, `router.py`, `po_tools.py`, `dashboard/snapshot.py`, `roles/product-owner.md`, tests. **Verdict: ship.** Coverage 99.54%, ruff clean. No new ADR (follows s83 desk pattern and s51 refusal helper).

**Design rules enforced (H1–H13, no branching):**
- **H1–H2:** `po_hold` is separate field from hand-over `hold`. Hold posts nothing, replaces reason if held. One event per success.
- **H3:** Holds don't move stories (priority.held unchanged). Router skips held stories in _movable/_escalated/_scribable.
- **H4–H5:** Board pill reads `⏸ PO hold: <reason>`. Release clears both holds, sets ACTIVE, saves reason in note for next step's brief.
- **H6–H7:** Cancel request posts one question, waits for answer. Only human's "cancel" answer calls `cancel(state, story)` (sole place status becomes CANCELLED).
- **H8:** Refusals data-driven (unknown, blank reason, finished, cancel pending, open question, manager wait, nothing to release, code unsaid). First match wins via `priority.first_refusal`.
- **H9:** Settle before acting (story_admin.Clerk.settle in router._tick after desk.apply).
- **H10:** One event per success (story-admin kind, role product-owner, data has tool/reason/before/after/question).
- **H11:** CANCELLED is finished (FINISHED = {DONE, CANCELLED}). Removed from order/pulled/human_order/scribe_due. Keeps file/commits/events.
- **H12:** Router never routes cancelled. _movable needs ACTIVE, _escalated needs NEEDS_MANAGER, _scribable checks po_hold and cancel clears scribe_due.
- **H13:** Labels: cancelled status, cancel-requested hold, PO hold—all via `backlog.label()` table.

**Module structure:** `story_admin.py` pure (Act/Decision enums, TOOLS table, refusal/effect/settle functions). `Clerk` does I/O: settle first, check refusal, apply tool, post question, save, emit event. `po_tools.py` routes hold_story, release_story, request_cancel through Clerk. No branching per tool (all via TOOLS dict). All texts exact per design.

**Test areas:** Hold/release/cancel/settle actions, refusals (15 cases), no question on hold, s4 case (blocked, no hold, no question → released), continue_story leaves po_hold, settle answers, only answer cancels, router skip, waits.wait title, backlog labels, snapshot po_hold, state loaders. All 15 checklist items pass.

See design `agile-team/docs/design/s53.md` (H1–H13, test checklist).

## s101 complete: Nested tool-call expansion (1 round, all ACs pass) — verdict ship (P1 tests pending)

**Scope:** `tool_calls.py` (start_row, open_row functions; ToolSpan.as_dict refactor), `live.py` (Pulse._open_calls, heartbeat adds calls), `tool_groups.py` (new, MiscAsk, ask_key, gathered_calls), `snapshot.py` (misc_calls), `server.py` (_misc route), `dashboard/index.html` (nested-row functions N1–N15, ~1000 LOC), fixture. **Verdict: ship (P1 node-harness tests pending).**

**Design rules enforced (N1–N15, AC1–AC5, AC-R):**
- **N1–N2:** Every step/PO bar has a key; opened keys in shared `ui.tlOpen` Set. Bars matched by role/story/time window; PO matched by event.data.opened_at.
- **N3:** Nested lines: model, lanes (one per stacking level), optional misc, or single "no tool calls" line if no group.
- **N4:** Stacking by first-fit: sort by (from, id), put each call in first lane whose last `to` ≤ call.from, or new lane.
- **N5:** Call bar state: ok/error/timeout (TOOL_LOOKS table), unfinished (hatched), open (grows to now), waiting (po.run_role with ok/open status).
- **N6:** Model row pieces: bar span minus call union (tlComplement), drawn as bars, total label from step-end event's `model_s` or measured.
- **N7:** Label: strip at y=top+4, h=8; lines below (name at +26, detail at +40, both x=x1+3). Drawn only if fit; narrow bars hide both in tooltip.
- **N8:** secondsText: <60s → "N.NN s"; ≥60s → fmt.span.
- **N9:** Misc box: text, rect (dashed), title with tool counts. Not on time axis (`x=LABEL_W+4`, no `data-from`/`data-to`).
- **N10:** Misc on demand: click toggles ui.miscOpen key, fetches /api/misc once, caches result, renders list.
- **N11:** Heartbeat gains `calls` after `step`: every open meter's calls, outer (PO) first.
- **N12:** GET /api/misc: query (role, story, step, opened_at), returns 200 JSON array or 404.
- **N13:** Keyed bars have `data-tl-keys`, `cursor:pointer`, `data-open="true"` when open. Row labels with keyed bars get `data-tl-keys`. Click toggles.
- **N14:** Replay: `toolsAsOf` keeps groups with opened_at ≤ cursor, calls with at ≤ cursor, reopens unfinished calls.
- **N15:** SVG ids prefixed by story id (tl-<story>-<group>-clip, etc.) so two timelines don't repeat ids.

**Module structure:**
- `tool_calls.py` pure + frozen dataclasses: `start_row(where, call)` returns TC11 keys up to `slept`; `open_row(where, call)` adds `status: "open"`; Calls.opened() lists open calls.
- `live.py` Pulse: `_open_calls()` returns [row for m in open for row in m.reading.calls.opened()]; `heartbeat` adds `"calls": self._open_calls() if live else []`.
- `tool_groups.py` pure (new): MiscAsk namedtuple (role, story, step, opened_at); ask_key() parses strings, validates finite float, returns Key|None; gathered_calls() finds group's misc rows, returns sorted by at.
- `snapshot.py`: `misc_calls(config, ask)` reads tail, gathers via tool_groups, returns list|None.
- `server.py`: Dashboard.misc_calls callable (default None). _misc handler parses query, calls app.misc_calls, returns 200 JSON or 404.
- `index.html`: 40+ functions ≤8 LOC each, data tables exact (NEST.LANE_H/STRIP_H/INDENT/MIN_DETAIL_CHARS/MISC_PAD, TOOL_WAITING, TOOL_LOOKS, MODEL_LOOK, MISC_TITLE, NO_CALLS, MISC_LOADING/FAILED), SVG contract (data- attributes exact), UI state (tlOpen, miscOpen, miscCalls).

**Tests:** No new test file (node harness tests pending as P1). Gate fixes: TL_TEXT count 9→12, heartbeat key lists. Fixture adds tools groups and heartbeat calls. Coverage 99.53%, ruff clean. All AC1–AC5 pass (customer-proxy verified on dashboard).

**Minor findings (don't block):** m2, m7 helper opportunities (keyedBars, span). m3, m4 transient/live-refresh limits. m5 unfinished/waiting swatch collision. m6 CSS rule for pointer (equivalent). Docs not in diff (architect ship step).

See design `agile-team/docs/design/s101.md` (N1–N15, test checklist, known limits), review round 1, acceptance (all six ACs pass on dashboard).

## s100 complete: Story timeline SVG (2 rounds, all defects fixed) — verdict ship (P1 pending)

**Scope:** `live.py` (Sleep class, _count_sleep, _log_sleep), `dashboard/snapshot.py` (_sleeps, SLEEPS_TAIL_BYTES), `dashboard/index.html` (timeline SVG builder and controls, ~1000 LOC). **Verdict: ship (P1 node-harness/e2e pending).**

**Design rules enforced (TL1–TL20, TR1–TR5):**
- **TL1–TL4:** Timeline section under spend/links with rows per role in RING_ORDER order, PO row, runner row. Spans from story-opened to done/now. No events → note text only.
- **TL5–TL6:** Step bars coloured by verdict (passed/bounced/disputed/held/escalated) with outcome markers. Runner-stage bars on runner row. During-stages noted.
- **TL7–TL9:** PO bars from po-turn events with touches check (PO_TOUCH_KINDS). Rulings as diamonds. Bounce arrows from verdict to next step.
- **TL10–TL11:** Gaps shaded by wait kind (asleep/question/hold/other/idle) with labels. Wait intervals clipped to gaps. Sleep band hatching over rows.
- **TL12–TL13:** Totals: work (step seconds), runner (stage seconds, excluding during), po (tool_s + model_s from touching turns), waiting (gap sum), asleep (sleep union). Breakdown in tooltip.
- **TL14–TL16:** Sprint scope toggle. Story groups in sprint order. Window with zoom/pan/follow/fit. Axis ticks auto-spaced.
- **TR1–TR5:** All text from TL_TEXT table (≥12px, --ink or --ink-2), no class sizing. SVG width equals viewBox (no scale), container scroll. Flow chart: FLOW_FONT_PX ≥12, useMaxWidth false, scroll, idleClassDef colour-only.
- **TL19–TL20:** Sleep record on beat gap >2 beats; snapshot sleeps section with tail read, valid rows, sorted by from.

**Module structure:** `live.py` Sleep dataclass (start, end, slept), _count_sleep/clocks/step events unchanged, _log_sleep appends JSON line (OSError suppressed). `snapshot.py` _sleep_row validator, _sleeps tail reader, SLEEPS in RUN_FILES, SLEEPS_TAIL_BYTES=262144. Browser: 40+ pure model functions ≤8 LOC each (roleRank, tlNow, storyRange, verdictOf, stepBars, stageBars, poBars, rulingMarks, bounceArrows, gapSegments, sleepWaits, questionWaits, holdWaits, otherWaits, storyGroup, sprintGroup, groupTotals, modelTotals, timelineModel, tlState, tlWindow, zoomed, pannedBy, tlTicks, tlText/tlSpan/tlButton, timelineSvg, totalsHtml, legendHtml, timelineHtml, setTlScope, onTlWheel, doneStories, openTimeline, keepTimelineScroll). Data tables exact: TL, TL_WIDTH, TL_TEXT, TL_SCOPES, VERDICT_KINDS, OUTCOMES, STEP_STATES, STAGE_STATES, ARROW_VERDICTS, HOLD_LABELS, RULING_KINDS, PO_TOUCH_KINDS, WAIT_KINDS, IDLE, TOTALS, TICK_STEPS. SVG attributes contract: data-group, data-row-label, data-bar, data-outcome, data-from, data-to, data-wait, data-sleep, data-now, data-arrow, data-mark (exact names).

**Coverage ≥95%, ruff clean. No tests deleted.**

**Round 1 findings (all fixed in round 2):**
- **D1:** Arrows outside window are clipped via clip-path (tlSeen check, groupDefs adds clip per group, groupSvg wraps content).
- **D2:** All 19 functions now have one-line `/** … */` docs.
- **D3:** X-mapping extracted to `tlX` (used by plot.x, axisSvg, nowSvg); sleepIntervals extracted (used by storyGroup, modelTotals).
- **m1:** Header title cut properly via tlCut.
- **m3:** nowSvg signature takes range, win, now, h (four params, page JS acceptable per review).

**Minor findings (don't block):**
- **m4:** storyGroup doc displaced by sleepIntervals helper; move back at next index.html touch.
- **m5:** SVG ids (tl-<group>-clip, -sleep, -arrow) repeat across open timelines (same content, HTML invalid); prefix with story id at next touch.

See design `agile-team/docs/design/s100.md` (TL1–TL20, TR1–TR5, per-module, test checklist), review round 2, fixtures contract snapshot.json.

## s99 complete: Runner stages as data (1 round, all ACs pass) — verdict ship (P1 e2e pending)

**Scope:** `stages.py` (new pure module, ~180 LOC), `stage_log.py` (new, ~150 LOC), `config.py` (Tool dataclass, TOOL_RULES, _tools), `cli.py` (tools_report, cmd_tools), changes to gates, dispatch, commands, git_ops, upstream, sandbox, boundary_runner, runner_tools, po_tools, roles/devops.md. **Verdict: ship (P1 e2e pending).**

**Design rules enforced (RS1–RS14):** RS1 STAGES dict matches Name enum, unique names. RS2 opened(name) KeyError for unlisted. RS3 note() does nothing with no stage open. RS5 keeps first non-zero code or latest command. RS6 raised is exception class name. RS7 awake_gap computes awake time per platform. RS8 Place (story, step) from StageLog.within. RS9 when/attach from table. RS10 OSError suppressed. RS11 Tool rules enforce name pattern, no clash, non-empty fields. RS12 DevOps owns [[tool]]. RS13 [[tool]] not executed (future). RS14 agile-team tools prints JSON. AC1–AC4 all pass: table pins (21 exact), unlisted fails, one event per run, choke points note, tools loads/clashes refused, agile-team tools outputs JSON.

**Module structure:** `stages.py` pure, exports Name enum (21 members), Stage/When/Attach/Place/Run dataclasses, STAGES dict, QUALITY/BOUNDARY/RUNNER_TOOL mappings, opened/unlogged/note functions. `stage_log.py` logs events via Marker interface. `config.py` Tool/TOOL_RULES/tool_problems pure. `cli.py` tools_report (JSON builder). Modules call stage_log.open/note at runtime; test with FakeSystem.

**Coverage ≥95%, ruff clean. No tests deleted.**

See design `agile-team/docs/design/s99.md` (RS1–RS14, per-module changes, test checklist), ADR-0048.

## s98 complete: Tool-call recording (TC1–TC18, all pass) — verdict ship (P1 e2e pending)

**Scope:** `tool_calls.py` (new pure module, ~280 LOC), additions to `live.py`, `dispatch.py`, `po_tools.py`, `config.py`, new `dashboard/tool_groups.py`, `dashboard/snapshot.py` changes, tests. **Verdict: ship (P1 e2e pending).**

**Design rules (TC1–TC18):** One span per call (TC1), opened on ToolUseBlock id, closed on matching ToolResultBlock. Status ok/error/timeout/unfinished (TC2). Unfinished spans closed at meter's end (TC3). Awake axis via platform-specific formula (TC4): POSIX mono delta, Windows wall minus sleep delta. Who from meter's Who plus STEP_OF_ROLE fallback (TC5). Named label for mcp__team__*/mcp__runner__* tools (TC6); Dev: for others (TC7). Detail: first 80 chars from DETAIL_KEYS with shown() applied (TC8–TC9). Masking replaces SECRET_ASSIGNMENT env vars with *** (TC10). Span line: JSON with keys in order (TC11). Time split: awake/busy/waiting via interval union (TC12). Split on step-end and po-turn events (TC13–TC14). Snapshot tools section: rows grouped by (role, story, step, opened_at) (TC15), valid rows only (TC16), shortest calls gathered under collapse_under_s (TC17–TC18).

**Module structure:** `tool_calls.py` pure + frozen dataclasses (Status, Where, Call, ToolSpan, Split, Calls). Functions under 8 LOC. POSITIONS/NAMED_SERVERS/WAITING/SECRET_ASSIGNMENT tables data-driven. `Calls` class tracks open calls by id, emits fresh spans. `Live.Reading` gains calls ledger, platform, start/end marks. `Pulse.take` writes spans on ToolResultBlock; `Pulse.close` closes unfinished. `dashboard/tool_groups.py` gathers via running sum.

**Coverage ≥95%, ruff clean. No tests deleted. All TC1–TC18 rules enforced; AC5–AC6 checklist items pass.**

See design `agile-team/docs/design/s98.md` (TC1–TC18, per-module changes, AC5–AC6).

## s103 complete: Guard refusals standardized via new `refusal.py` module (1 round, all ACs pass, ship)

**Scope:** New `agile_team/refusal.py` (pure, ~50 LOC), changes to `suite_check.py`, `kill_check.py`, `git_check.py`, `guard.py`, `roles/_shared.md`, design spec. **Verdict: ship.** Diff matches design R1–R8 line for line.

**Design rules enforced (R1–R8):** (R1) Bare redirect operator (whole word `>`, `>>`, `<`, `1>`, `2>`, `2>>`) followed by target word; target is not a positional. (R2) Run kind decided on test paths after R1 applied. (R3) Redirect target not path-checked by guard (audit is backstop). (R4) No built-in role file contains `"timeout "` (with space); backtick-quoted `timeout` keyword and `timeout` ini allowed. (R5) No Bash refusal reason contains `"timeout "`. (R6) Wait check unchanged (loop with timeout/gtimeout prefix still passes). (R7) Every Bash refusal: `"refused by rule `{rule}`: {why}. Allowed: {allowed}"` (rule = Rule enum member, allowed non-empty). (R8) One rule name per refusal row (two GIT_OUTSIDE rows share one rule). **Rule table:** 14 Rule members with exact `why` and `allowed` texts matching design table. **Module structure:** `refusal.py` pure (no imports from agile_team), exports FORMAT string, Rule enum, Refusal dataclass with `text()` method. Guard modules import and build Refusals at runtime; `text()` preserves `{placeholder}` for later `.format()` calls. **Coverage ≥95%, ruff clean. No test deleted.**

See design `agile-team/docs/design/s103.md` (R1–R8, rule table, per-module changes, test checklist AC1–AC3).

## s92 complete: Gate fixes with assertion changes require a named rule (no new ADR)

Your brief on gate fixes: "Gate fix by `<role>` (commit `<sha>`) on `<files>`: `<note>`." When a fix changed what a test asserts without naming an AC or design rule, the note flags it: "assertion lines changed, but no rule was named; check them." Request changes if the rule doesn't support the change or is missing. All gate fix records show in exact order (R18). See `agile-team/docs/design/s92.md` (R19, test items 25, AC5).

Your brief now lists gate fixes: "Gate fix by `<role>` (commit `<sha>`) on `<files>`: `<note>`." When a fix changed what a test asserts without naming an AC or design rule, the note flags it: "assertion lines changed, but no rule was named; check them." Request changes if the rule doesn't support the change or is missing. All gate fix records show in exact order (R18). See `agile-team/docs/design/s92.md` (R19, test items 25, AC5).

## s97: Awake-time calculation—two clocks on step events, platform-aware rules (1 round, all ACs pass) — verdict ship (P1 tests pending)

**Scope:** `system.py` (+platform), `live.py` (Pulse.slept_s, _count_sleep, clocks(), Meter.interrupted), `dispatch.py` (pulse.clocks on step events), `dashboard/step_times.py` (new, ~280 LOC pure), `snapshot.py` (_watch), `index.html` (running line, timeBy, legend), tests. **Verdict: ship (P1 node-harness pending).**

**Design rules enforced (AW1–AW13):**
- **AW1–AW2:** Pulse beats every 20s, counts gaps > 2 beats, accumulates in slept_s. Step events carry `data.mono` and `data.slept` via `clocks()` (released lock).
- **AW3–AW4:** `Mark` readings validate numbers (not bool), `PLATFORMS` table maps `win32`→Windows, others→POSIX.
- **AW5–AW6:** `AWAKE` dict routes to platform rule. POSIX: `end.mono - start.mono`. Windows: `(end.at - start.at) - (end.slept - start.slept)`.
- **AW7:** `Stopwatch.between` → `wall_timing` (fallback with mark) or `awake_timing` (clock name + slept delta).
- **AW8–AW13:** Killed steps untimed; running steps via `so_far(now)` with snapshot's current clocks; page running line formula; wall steps marked; legend text.

**Module structure:** `step_times.py` pure + frozen dataclasses, `Clock`/`Platform` enums, `AWAKE` table (no branching), `Pairing` stores `Mark` in `starts[index]`, `_timing` returns `UNTIMED`/`Timing`, no `closed`/`wall_seconds` functions (replaced by `_closed`/_running). Snapshot `_watch` builds `now` from files and heartbeat.

**Test coverage (all items from design checklist pass):** POSIX sleep span, Windows counter, Windows fallback, no clocks, platform_of names, AWAKE keys, killed, running (POSIX/Windows/no-clocks), mono/slept going back, bool/string/None handling, as_dict keys. S96 exact-dict test gains two keys. No test deleted or weakened.

**Minor findings (m1–m4, don't block):** m2 seam test (one line) missing; m3 dispatch clocks test weak (doze only before both); m4 duplicate event helper.

See design `agile-team/docs/design/s97.md` (AW1–AW13, per-module, test checklist, known limits).

## s104: Flow chart fixes—dimming by colour, unused roles marked (1 round, all ACs pass) — verdict ship (P1 e2e pending)

**Scope:** `snapshot.py` (_used_roles, _assigned_developers, _routed_roles, _stepped_roles functions, `used` field on roles), `index.html` (CSS, idleClassDef, statsText, ringRoles filter, mermaidConfig, natural-size Mermaid), fixture. **Verdict: ship (P1 e2e pending).**

**Design rules (FL1–FL9):** No compositing styles (opacity/filter/transform/mix-blend-mode) in classDef. Dim by colour only (fill/stroke/color). Every role has `used: bool` (routed or stepped). Chart draws only used roles (except PO always). Natural-size SVG (useMaxWidth: false, 16px font), scroll sideways. Show "idle" when role has no totals and no open step. No `used` key = still drawn (backward compat).

**Module structure:** `_used_roles` union of `_routed_roles` (from STEP_ROLES via pipeline) and `_stepped_roles` (from events). `_routed_roles` uses new `_step_role` helper with `.get()` fallback on STEP_ROLES. Generic developer expands to assigned developers or itself. `_roles` adds `used: r.name in used` to each role. Functions ≤8 LOC. `index.html`: `idleClassDef()` returns colour-only class def; `statsText(view, ctx, name)` returns `"idle"` or totals; `ringRoles(view)` filters by `r.used !== false`.

**Coverage ≥95%, ruff clean. No tests deleted. Fixture adds developer-db with used: false.**

See design `agile-team/docs/design/s104.md` (FL1–FL9, per-module changes), ADR-0047.

## s96: Time per role on dashboard (1 round, all ACs pass) — verdict ship (P1 pending)

**Scope:** `step_times.py` (new pure module, ~150 LOC), `snapshot.py` (_steps function), `index.html` (five helpers, Flow scope predicates, box time, Time unit), tests. **Verdict: ship (P1 node-harness/e2e pending).**

**Design rules enforced (ST1–ST15):**
- **ST1–ST8:** Event pairing by (role, story); killing first on duplicate; wall time from end - start rounded to 0.1; null for killed steps; open steps running; sprint from last sprint-start event; model from end, fallback to configured, else "unknown"; only agent steps count.
- **ST9:** Span format: 0 min, <1 min, N min, H h M min.
- **ST10–ST11:** Box time sums finished steps in scope (Story/Sprint/Run); running line shows elapsed time, updates once/sec via `tick`.
- **ST12–ST14:** Time unit with label/title/totals/total/legend/row; bars per group, largest first, tooltip with step count and share; legend text exact.

**Module structure:** `step_times.py` pure, `Pairing` class, `spans()` function, `FEEDS` dispatch table. Snapshot adds `_steps()` via new `_step()` helper with model fallback (ST7). Dashboard: `fmt.span()`, `finished()`, `stepsAsOf()` (ST15), `inScope()`/`inSprint()` predicates, `scopeSteps()`, `addStepTimes()`, `openStep()`, `runningLine()`, `ledgerTotals()`, `stepTotals()`, `timeBy()`, `timeRow()`, `timeLegend()`.

**Coverage ≥95%, ruff clean.** All ST1–ST8 rules enforced. See design `agile-team/docs/design/s96.md`.

## s86: Story dependencies as data (1 round, all ACs pass) — verdict ship (P1 pending)

**Scope:** `dependencies.py` (new, ~350 LOC), `gates.py` (one field), `dispatch.py` (load_dependencies, reorder warnings), `cli.py` (START_REFUSED text), `router.py` (_movable guard, _why signature), `po_tools.py` (_depends_refusal, open_story, start_sprint), `dashboard/snapshot.py` (three keys), `dashboard/index.html` (helpers, backlogRow, timeline), `roles/product-owner.md`, docs, tests. **Verdict: ship (P1 DP16 e2e pin and page harness pending).**

**Design rules enforced (DP1–DP15, design spec):**
- **DP1–DP2:** `depends_on` list in frontmatter, loaded from open story files, file wins. `StoryState` field, dataclass, default `[]`. Dedup by `dict.fromkeys`. Known: done stories are valid targets.
- **DP3:** Load at `cmd_start` (via `_load_dependencies`), `start_sprint`, `open_story`. No other reads.
- **DP4:** Validation order: shape (NOT_A_LIST), self (SELF), unknown (UNKNOWN), cycle (CYCLE). First refusal wins.
- **DP7:** `find_cycle` DFS depth-first from each id in `priority.natural` order. Path from cycle point to itself joined by `" -> "`.
- **DP5:** `load_refusal` returns text; refusal changes nothing, saves nothing. `cmd_start` raises `CliError(START_REFUSED…)`. `start_sprint` returns `refused()`.
- **DP6:** `open_story` checks argument/file/graph; MISMATCH order-sensitive, dedup'd; self/unknown on new graph incl. new story.
- **DP8–DP10:** `waiting_on` lists undone/missing ids in list order. `_movable` checks waiting_on is empty. `_why` order: hold > WAITING > status; text exact.
- **DP11–DP13:** `above` finds inversions in queue. `warnings` calcs new inversions. Snapshot keys: depends_on (list), waiting_on (undone, [] if done), dependency_warnings (texts, [] if done).
- **DP12, DP14:** `reorder` adds `warnings` key ([] if none, else `WARNING` per new inversion). `priority` event tone `warning` when warnings non-empty. Backlog tab shows depends, waiting, ⚠ pills.
- **DP15:** Migration complete; prose "Depends on sN" removed, table-M stories have frontmatter lists, done deps dropped (s39 s29 done, no entry).

**Module structure:** `dependencies.py` pure functions + file I/O, no dependencies added (PyYAML already present). `Declared` class with lists and bad ids. DRY: `graph_refusal` uses `first_refusal`. Helpers under 8 lines (DP12 `warnings` via list comp, DP13 `warning_texts` via map).

**Coverage 99.46%, ruff clean. No tests deleted. Fixture adds s2 above s5 (waiting, with warning), s6 on done s1 (waiting_on: []).**

See design `agile-team/docs/design/s86.md` (DP1–DP15, D1–D3, m1–m4), ADR-0046.

## s85: Liaison opinions (1 round, all ACs pass) — verdict ship (P1 pending)

**Scope:** `opinions.py` (new, ~250 LOC), `cli.py` (two new commands), `server.py` (two POST routes), `snapshot.py` (opinions section, events), `index.html` (~200 LOC, badges, filter, review bar, buttons), `threads.py` (public `read_lines`, `append_line`, `has_time`), tests, docs, fixture. **Verdict: ship (P1 node-harness/e2e pending).**

**Design rules enforced (O1–O20):** Kind/Act/Route enums; Recording with refusals (story, kind, text); Latest-by-line wins; Review closure; Ask posts to inbox; Act parsing and refusals (unknown, superseded, keep, settled); Routes (NONE/REORDER/PO); Snapshot items, route, acts; Events merged; Write gate (403/400/409/202); Token never leaks.

**Module structure:** `opinions.py` pure + file I/O; Board, Opinions classes; lenient readers; table-driven dispatch (DOERS, APPLIERS). `threads.py` gains three public functions (read_lines, append_line, has_time). CLI appends to JSONL files with validated input. Server routes via `Opinions` instance. Snapshot builds items list, merges acts, event-ifies opinions/acts. HTML: badges (O15), filter (O17), details (O16), review bar (O18), buttons (O16), posting (O19).

**Coverage 99.46%, ruff clean. No tests deleted. Fixture adds s6 move-down (open), s5 scope (settled).**

See design `agile-team/docs/design/s85.md` (O1–O20), ADR-0045.

## s84: Story threads—human discusses with PO and liaison (1 round, all ACs pass) — verdict ship (P1 pending)

**Scope:** `threads.py` (new pure module, ~250 LOC), `relay.py`, `router.py`, `po_tools.py`, `watch.py`, `cli.py`, `dashboard/server.py`, `dashboard/snapshot.py`, `dashboard/index.html`, `roles/product-owner.md`, tests, design fixture. **Verdict: ship (P1 node-harness/e2e pending).**

**Design rules enforced (H1–H21, design spec):**
- **H1–H5:** Party enum (HUMAN, PO, LIAISON), RECIPIENTS frozenset. Text refusal: blank/whitespace, >4000 chars exactly. Story refusal: unknown (exact text), done allowed. Post shape: JSON {story (regex), to (string), text (string)}, extra keys OK.
- **H6–H8:** To PO via `Relay.tell(tagged(story, text))`. Head format `<!-- thread story={story} at={at} -->\n\n`. `tag_of` reads file, matches head, returns Tag or None. `told_line` gives thread-tagged line format.
- **H9–H10:** `reply_story` tool with story/text checks (H3, H2 in order), posts Note(REPLY, text, [story]), returns {status, id}. `notify_user(kind=="reply")` refused with exact USE_REPLY text before posting.
- **H11:** Inbox line `{story, text, at}` appended to `liaison/inbox.jsonl`. Lenient read (blank/torn/non-object lines skipped).
- **H12:** Watch `Seen.posts`, `Look.posts`, `new_posts(seen)` method. Trigger `liaison_message` fires on new_posts. `posts` in line(). `_next` keeps seen.posts. Old memory loads posts=0. First watch records current as seen.
- **H13:** Liaison CLI `reply <story> <source>` (file or -). Text/story checks (H2, H3). Appends to `liaison/replies.jsonl`. Works stopped.
- **H14–H15:** `Threads.all()` = four sources merged by (at, id). Entry fields: id, story, author, to, text, at. JSONL lenient (blank/non-object/torn skipped). Tag on relay files, reply in outbox, inbox/replies JSONL, no other markers.
- **H16–H17:** Events: `thread-<id>`, kind="thread", role from EVENT_ROLES (PO only), data has entry/author/to. No message event for reply outbox lines.
- **H18:** Snapshot: `thread` array, watched_files includes inbox/replies/told files.
- **H19–H21:** Page: `threadHtml(story, view)` on expanded row. Form with textarea (maxlength 4000), select (PO/liaison), button (with TOKEN). `postThread` POSTs with token header. `keepFocus` saves/restores selection. Timeline: `TIMELINE.thread`, `ctx.thread` map, "thread" in MARKDOWN_KINDS.

**Module structure:**
- `threads.py` pure: Party enum, Entry/Post/Tag dataclass, text/story validation, parse_post, tagging/reading, Threads class with post/reply/all readers, SENDERS dispatch table, RECIPIENTS/EVENT_ROLES dicts, watched function.
- `relay.py`: REPLY added to KINDS (last). Draft renamed `.draft-{token()}`.
- `router.py`: _told_lines uses threads.told_line, _deliver = answers + tagged stories (deduplicated).
- `po_tools.py`: reply_story tool (H9), notify_user refuses REPLY kind.
- `watch.py`: Seen.posts, Look.posts, new_posts, liaison_message trigger.
- `cli.py`: cmd_reply command (H12).
- `server.py`: BODY_LIMITS table per-route. _thread handler (H4 order: may_write→403, length→400, parse→400, post→400, 202).
- `snapshot.py`: _thread section, _thread_event, _events merges thread + drops reply from message.
- `index.html`: `ui.drafts`, `ui.to`, `ui.sending`, `ui.threadNote` state. Functions: `threadHtml`, `postThread`, `keepFocus`. Input/change/click listeners.
- `product-owner.md`: Section explaining thread posts and reply_story tool.

**Test coverage (all items from design checklist pass):**
- Text/story checks (blank, 4000/4001, unknown story).
- Parse post (valid, non-object, missing key, bad to, bad id, non-str, blank, over-long).
- To PO: file written with head, Entry returned, Relay.told lists it, no draft left, two posts → t1/t2.
- Router: THREAD_TOLD_LINE delivered, stories included, plain tell still gives TOLD_LINE no story.
- `reply_story`: unknown/empty refused (exact texts), good posts to outbox, `notify_user(reply)` refused.
- To liaison: line appended, id=lp1/lp2.
- Watch: fires on new post, next watch skips, shorter inbox reports all, old memory loads posts=0, first watch takes existing, heartbeat posts=[], reply still fires message.
- Liaison reply: file appends, prints replied<id>, returns 0. Unknown/empty/over-long refused (exact), works stopped.
- All merges: four sources by (at, id), torn line skipped (ids unchanged), reply without stories not an entry, head-less told not an entry.
- Snapshot: thread dict array, four thread events (role PO only for reply), no message event for reply.
- Write gate: 202 from 127.0.0.1+token; 403 from other host/bad token (body unread); 400 for bad body/story/length/app.post=None.
- Token: absent from snapshot/told/inbox/replies.
- Watch memory: posts field loads and keeps correctly.
- Relay draft: `.draft-{token()}`, two tells get distinct numbers.

**No test deleted or weakened. Coverage ≥99.44%, ruff clean.** All 13 design checklist items pass (14–16 e2e pending for integration-tester).

See design `agile-team/docs/design/s84.md` (H1–H21), ADR-0044, review round 2 (m1/m2 minor, don't block).

## s83: Backlog reorder with human-order rule (1 round, all ACs pass) — verdict ship (P1 pending)

**Scope:** `backlog.py` (new pure module, ~150 LOC), `reorders.py` (new I/O module, ~200 LOC), `story_files.py` (new, ~100 LOC), `priority.py` (Source enum, source field), `po_tools.py` (human-order check, reorders hand-over), `state.py` (three new fields), `router.py` (Desk instance), `dispatch.py` (Runtime.reorder method), `config.py` (DashboardSettings), `dashboard/server.py` (POST /api/reorder, GET /api/file), `dashboard/snapshot.py` (order_version, backlog, reorders, label, disputes, developer, commits, files), `dashboard/index.html` (Backlog tab with expand/collapse, handles, drag-drop, file loading), tests. **Verdict: ship (P1 node-harness/e2e pending).**

**Design rules enforced (B1–B20, design spec lines):**
- **B1–B3:** `View.of(state)` lists queued stories (not done), split current/backlog by sprint. Label from `priority.held()` or hold text parsing. Snapshot carries view result.
- **B6–B7:** `story_files.FOLDERS` whitelist (story, design, review, acceptance). `path_of()` checks kind, id (via `STORY_ID` regex), story existence, file existence and regularity. Path built only from table and checked id.
- **B9–B10:** `Ask` {story, position (int, 1-based backlog place), version}. `order_version()` = `sha256(json([queue, backlog]))[:12]`.
- **B12–B13:** `place_refusal()`, `sprint_refusal()`, `stale_refusal()` checks. `placement()` → Placement. `Desk.apply()` calls refusals in order, records first as reason.
- **B14:** `Reorder.event_data()` includes `source` (Source enum).
- **B17:** `human_refusal()` checks: guarded projection before/after; if changed and no reason, refuse. PO tools call `_human_check()` which builds check.
- **B18–B19:** localhost+token check in `may_write()` before body read. `MAX_BODY=4096`. `_body()` length check. Exact 403/400 responses.
- **B19:** `token()` in `system.py` (secrets.token_urlsafe(16)). Fixed via config or --token arg. Printed in URL, never in snapshot/events/logs.

**Module structure:**
- `backlog.py`: Pure (no I/O). `View`, `Ask`, `Placement`, `HumanCheck` dataclasses. Functions: `view()`, `order_version()`, `label()`, `stale_refusal()`, `sprint_refusal()`, `place_refusal()`, `guarded()`, `human_refusal()`.
- `reorders.py`: File I/O and apply. `Request`, `Requests`, `Desk` classes. `parse_ask()` parser. `told_section()` text builder.
- `story_files.py`: Dashboard file serving. `FOLDERS` table, `path_of()`, `read()`, `existing()` functions. `FileAsk` namedtuple.
- `priority.py`: `Source` enum (PO, HUMAN), `SOURCE_ROLES` dict, `Reorder.source` field.
- `po_tools.py`: `_human_check()` builder, `human_refusal()` call, PO tools' third check. `_take_reorders()` hand-over section.
- `dispatch.py`: `Runtime.reorder()` method (apply, emit event with source).
- State: `human_order`, `reorders`, `reorders_told` fields (defaults empty, old state.json compatible).
- Snapshot: `run.order_version`, `run.backlog`, `story.label`, `story.disputes`, `story.developer`, `story.commits`, `story.files`, `reorders` (last 20), source on all priority events.
- Server: `Dashboard.read_file`, `Dashboard.queue` callables. `Handler.do_POST` routes `/api/reorder` and `/api/file`. `may_write()`, `_body()`, `_reorder()`, `_file()` handlers. `WRITE_HOSTS` set. `TOKEN_HEADER`. `with_token()` URL builder.
- HTML: New Backlog tab, `TABS`, `ui.expanded`, `ui.files`, `ui.reorder`, `ui.note`, `ui.drag` state. Functions: `backlogGroups()`, `storyLabel()`, `backlogRow()`, `storyDetails()`, `backlogHtml()`, `renderBacklog()`, `toggleRow()`, `loadFile()`, `moveTarget()`, `postReorder()`, `reorderNote()`, `moveFromHandle()`. Handlers for expand, move, reload, drag-drop.
- Config: `DashboardSettings` dataclass with `token` field. `from_raw()` parsing.

**Test coverage (all items from design checklist pass):**
- Snapshot fields correct; order_version stable/changes; ranking shown.
- Refusals: sprint-story, stale (exactly "STALE"), bad place, human-order reason (exact text).
- Apply: move, event source, human_order updated, told line exact.
- Router: applies before work, no repeat.
- Requests: queue, all, pending, parse_ask edge cases.
- File route: 404 for all bad inputs.
- Write gate: 403 for wrong network/token, 400 for bad body, 202 on success.
- Token: absent from snapshot/events/logs/crash.
- Config: parsing, validation.
- State: legacy loaders.

**No test deleted or weakened. Coverage ≥95%, ruff clean. CLI prints exact `dashboard: http://localhost:<port>/?token=<token>` URL.**

**Pending (P1):** Node-harness tests (expand/collapse, handles, moveTarget edges, reorderNote cases, no drag while pending) and e2e test (real dashboard POST from 127.0.0.1, router applies). Design checklist items 18–23.

See design `agile-team/docs/design/s83.md`, ADR-0043, review round 4.

## s15: Markdown rendering safe and pinned (1 round, all ACs pass) — verdict ship

**Scope:** `agile-team/runner/agile_team/dashboard/index.html` (new markdown section), `tests/e2e/test_dashboard_markdown_e2e.py` (new file), `tests/e2e/test_dashboard_e2e.py` (one test renamed), docs. **Verdict: ship.** HTML matches design rules M1–M12 line for line. No Python code changed. E2E tests pass (payload inertness, link safety, plain fallback, load failure graceful, QA rendering, timeline kinds pick correctly, one function rule). Coverage unchanged. No new dependency (markdown-it is CDN-pinned, not imported). Ruff clean.

**Design rules enforced in HTML:**
- **M1:** `md(text)` sole renderer, `markdownit(` once in `safeMarkdown`, `.render()` on `markdown` once only.
- **M2:** Loaded shape `<div class="md">` + HTML + `</div>`; unloaded `<div class="md plain">` + escaped + `</div>`; null/undefined empty.
- **M3–M7:** Config `{ html: false, linkify: false, typographer: false, breaks: true }`, `disable("image")`, `validateLink = /^https?:\/\//i`, `link_open` rule adds `target="_blank" rel="noopener noreferrer"`.
- **M8:** Boot calls `loadMarkdown()` not awaited; promise resolves (never rejects) on success or error; uses `globalThis.markdownit` from UMD wrapper.
- **M9–M10:** Questions tab: open/raised/answered use `md()`; timeline: step-end/message/answer use `md()`, others use `esc()`; `MARKDOWN_KINDS` set and `bodyHtml()` helper data-driven.
- **M11:** Pinned URL in `MARKDOWN_URL` constant, `SAFE_LINK` with escaped slashes.
- **M12:** CSS `.md` (normal, overflow-wrap), `.md.plain` (pre-line), margins reset, block elements 6px, headings bold, lists indented, code/pre on surface-2, links on accent, blockquote on grid+ink-2.

**Module structure:** No new JS files; all code in `index.html` after helpers section. Helpers: `safeMarkdown(markdownit)`, `useMarkdown(markdownit)`, `loadMarkdown()`, `md(text)`. Changes to `boot()`, `renderQuestions`, `renderAnswered`, timeline row builder.

**Tests:** E2E only (real library needed). 10 cases: pin/copy version, syntax, links, 14 payloads inert, plain fallback, load failure graceful, questions render, timeline picks, one-function rule, two URLs exact.

**Old rule updated (new ADR-0042):** "Only outside URL is Mermaid" → "Exactly two: Mermaid and markdown-it". E2E URL scan verifies both pinned, no others (SVG namespace excluded).

No Python code, no new dependency, no test deleted or weakened. Snapshot and server unchanged. See design `agile-team/docs/design/s15.md`, ADR-0042.

## s51: Priority ranking, tier groups, pull logic (2 rounds, all defects fixed) — verdict ship

**Scope:** `priority.py` (new rules G1–G17), `state.py`, `dispatch.py`, `po_tools.py`, `dashboard/snapshot.py`, `dashboard/index.html`, `roles/product-owner.md`, ADR-0016 amendment. **Verdict: ship.** Diff matches design G1–G17, D1'–D5' line for line. No test deleted or weakened. Coverage 99.41%, ruff clean.

**Design rules enforced:**
- G1–G2: `Tier` enum, `started()` checks commit, `held()` checks hold/status, `tier()` returns group.
- G3: `key()` = `(done, RANK[tier], listed, natural(id))` replaces P2 (explicit order beats in-progress).
- G6–G9: `pulls()` finds not-started before last started, `set_pull()` judges when at least one started listed, `pull_refusal()` requires reason, `first_refusal()` short-circuits.
- G13–G16: `repulled()` maintains pulled list, `plan()` builds without groups, `with_first()` and `with_move()` build on plan (never queue), so held stories keep their place.
- State: `RunState.pulled` field, loads without it (defaults []).
- Snapshot: `tier` replaces `in_progress`. Dashboard shows `tier` per story.

All 18 test items pass (worked example end-to-end, all refusals, group ranking, held hold-release cycle, reorder while held). ADR-0016 amended.

See design `agile-team/docs/design/s51.md` (G1–G17, D1'–D5', test checklist).

## s65: Git confinement (one round, design matched, no new ADR) — verdict ship

**Scope:** `git_check.py` (new pure module), `guard.py`, `presentation.py`, `dispatch.py`, role files, docs. **Verdict: ship.** Diff matches design G1–G10 line for line. Coverage ≥95%, ruff clean. No test deleted or weakened.

**Design rules enforced in code:**
- **G1–G2:** `GIT_CONFINED` table (e2e, acceptance), `git_env(run_dir)` returns ceiling+cwd vars, `_confine_git` merges into launch.env.
- **G3:** `strip_prefixes(words)` skips assignments, WRAPPERS, returns command words after them.
- **G4:** `_read_only(call)` on unconfined segments, today's text.
- **G5:** `bases(links, start)` tracks cd moves (cd/pushd on AND only, unknown after other separators), `where(site, call, base)` resolves places (env -C, -C, --git-dir, --work-tree, -c) and args (PATH_ARGS), classifies Where (UNCONFINED/STEP_DIR/WORKSPACE/ELSEWHERE/UNKNOWN).
- **G6:** `GIT_RULES[Where]` table maps to `GitRule(allows, reason)`, `ALLOWS` predicates enforce them.
- **G7:** `_locked_mention(name)` denies GIT_ENV_LOCKED vars in confined steps.
- **G10:** `_check_view` order: secret, git (G7 then G3–G6), allowlist, tokens, waits, kills, suite.

**Module structure:** `git_check.py` pure (I/O only `resolve_in`), exports classes (Wrapper, Where, Allows, GitRule, Link, Stripped, GitCall, Site) and functions (strip_prefixes, parse_git, bases, where, git_denial, git_env); guard.py imports from git_check, `_check_git` lambda calls `git_denial(_site(scope), links)`.

**Regression tests:** Unconfined `git status`, `git cherry-pick -n x` allowed; `git commit`, `git -C x status` denied. Command prefixes (env, command, timeout) seen through. Option-first placement denied.

**All AC1–AC10 pass:** Environment stops discovery (test with git_env on real repo). Guard denies explicit access and sees through prefixes (parametrized tests). Workspace persists (lay_out creates/keeps). Denial texts name targets exactly.

See design `agile-team/docs/design/s65.md` (G1–G10, test checklist).

## s59: Rebase at sprint start (3 rounds, all defects fixed) — verdict ship (e2e pending)

**Scope:** `rewrite.py` (new), `upstream.py`, `boundary.py`, `boundary_runner.py`, `handover.py`, dashboard, docs. **Verdict: ship (e2e pending).**

**Round 1:** Design rules R1–R12 matched closely. No merge, no `-s ours`, linear result. Boundary gains `sync_from` field, outcome `REBASED`. `rebase_onto` reads start and target, runs exact argv, handles conflict by abort+read, checks for lost content. `rewrite.py` pure, pairing by stamp, remap by field table. Dispatch via `AFTER_REBASE` dict (R1–R12 data-driven). Fixture e93 (end-edge) becomes `pass` not `rebased` (R12: only START). No test deleted, no dependency added. **Changes requested:** R2 save before rebase (D1, D2), style (D3, D4).

**Round 2 defects fixed in round 3:**
- **D1, D2:** `_pin_sync_from` guard saves only when empty; two tests pin order (save before rebase on first run, rebase first on rerun).
- **D3:** Push test renamed; moved moved-assertion to separate test.
- **D4:** `_swap` helper reduces repeated swap-and-count; type hints on `_story`, `_interruptions`.

**Checked:** No `merge`, `-s`, or `-X` in sync. Team-branch push refusal pins both target and team (R11). `REMAPPED` table exact; `checked` not rewritten. No repeated blocks new. Coverage 99.43%, ruff clean.

**Pending:** AC6 e2e tests (5 cases: all upstream, copies+new, real conflict, hash rewrite, hand rebase after conflict). Integration-tester scope, design specifies all cases exactly.

See design `agile-team/docs/design/s59.md` (R1–R12, test checklist), review round 3, ADR-0041.

## s89: OS guard refined for 3.13 (test infrastructure, no new ADR) — verdict ship

**Scope:** `tests/os_guard.py`, `tests/test_os_guard.py`, `docs/architecture.md` (one row), `docs/design/s89.md`. **Verdict: ship.** Diff matches design line for line. Coverage 99.31%, ruff clean. No test deleted or weakened, no runtime code changed. Guard refined with rules T1–T6. New helper `call_audited_through` builds relay chains for testing multi-frame stacks (reuses `as_module`). `_modules()` is new generator yielding stack module names; `_caller()` refactored to use it (DRY). `_reading_source()` implements T1 (reader on stack inside guarded frame). AC1 (3.13 pass, 36 failures fixed), AC2 (traceback formatting test), AC3 (guard still catches real agile_team code) verified. AC4 will be checked at s81 CI boundary. See design `agile-team/docs/design/s89.md`.

## s81: CI module, boundary stage, Prs protocol — verdict ship (e2e work pending)

**Verdict: ship (e2e pending).** Scope: `ci.py`, `boundary.py`, `boundary_runner.py`, `upstream.py`, `po_tools.py`, `config.py`, `state.py`, `handover.py`, `test_s81_boundary.py`. Coverage 99.31%; ruff clean.

**Design review (CI1–CI16):**
- CI1: Stage added, runs after PUSH on every boundary that pushed.
- CI2: Only READY non-draft entries watched.
- CI3–CI4: Wait, grace, settle checks with retry loop.
- CI5–CI7: Verdict rules data-driven, GREEN only when all PRs green.
- CI8: Failing lines extracted from logs, safe patterns, max 20 lines.
- CI9–CI10: State and events recorded, four outcomes per verdict.
- CI11: Hold cleared only by green verdict or recorded bug story.
- CI12: READY_PHRASE appears only in green report and green hand-over.
- CI13: No PR or gh → NONE, not ready.
- CI14: Bug story first in sprint.
- CI15: Blocking acceptable, health green via `pulse.doing()`.
- CI16: Errors raised as UpstreamError.

**Module review:**
- `ci.py`: Verdict rules sound, failing_lines patterns correct, CiWatch contract met.
- `GhPrs` methods: argv exact, exit codes handled, log reads safe.
- `record_ci_bug`: refusals checked, settle_bug closes boundary, ci_bug field cleared on start_sprint.
- State loaders: legacy files load with defaults, round-trip tested.
- Handover rows: apply only to matching report shapes, ci_green on ci field not hold.
- `ci_timeout_s` validated positive, default 1800.

No test deleted or weakened. No dependency added.

**Pending:** AC7 e2e test (stub gh on PATH, capture argv, assert logs read). Integration-tester scope, design specifies it exactly.

All nine rule classes (CI1–CI16, not CI13 which has no rule class) enforced in code. See design `agile-team/docs/design/s81.md`, ADR-0040.

## Recent reviews (s77–s78, no new ADR)

- **s77:** Seam P3—import discipline enforced by ruff TID251.
- **s78:** Health accuracy—beat resilience, monotonic sleep, excuse logic.

See ADR-0036 (s71 seam), ADR-0038 (s78 health).

## Your focus

Verify design rules are enforced in code (not prompt). Check that verdict logic is data-driven (no branching on bucket type). Ensure Prs interface is unchanged (gh calls stay behind it). Confirm no new user-facing changes except hand-overs and tool.
