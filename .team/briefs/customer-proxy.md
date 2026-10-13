# Customer Proxy: Current context and conventions

**Last updated:** 2026-10-13 (s93 done; s110 done; s109 done; s107 done; s53 done; s100 done; s99 done; s98 done; s103 done; s92 done; s97 done; s104 done; s86 done; s85 done; s84 done; s83 done)

## s93 complete: A14a—"delivery" renamed to "acceptance environment" (AC1–AC4 verified; no new ADR)

**Verdict: All ACs pass.** Customer docs now use "acceptance environment" everywhere. **What you see:**
- **AC1:** Config section is `[[environment]]` (old `[[delivery]]` loads as environment with a warning). Both sections in one file error.
- **AC2:** All identifiers say "environment": prompts, refusals, error texts. Example: `"acceptance environment {name!r} is not configured"`. The `manual` kind is unchanged; `document` kind is new (see AC5).
- **AC3:** All docs say "acceptance environment"; `grep` pin verifies the old word appears only in config constant and its test. Design explains: "Environments are the repo's (names, prepare, url, commands); kinds are the skill's (sandbox.ENVIRONMENT_KINDS)."
- **AC4:** Dashboard shows `environment` (not old key); Backlog detail line reads `acceptance environment: <name>`.
- **AC5 (new kind):** `document` environment—for ACs with nothing to run (prompts, docs, design). Your tools are Read, Grep, Glob, Write (no Bash). You read the guide and changed files in the presentation, judge each AC against them, write a report. No service starts, no question posted. If story needs one, mark it with environment kind `document`.

**Your scope unchanged:** Same sandbox procedure, same service startup for web/manual. Presentation.md contract unchanged. When a story's environment is `document`, your sandbox gets Read/Grep/Glob/Write instead of the configured delivery's tools.

See design `agile-team/docs/design/s93.md` (rules E1–E13, the "document" kind in E11).

## s110 complete: CI rule documented in role file, SKILL.md, protocol.md (AC1–AC2 pass, no new ADR)

**Verdict: AC1–AC2 accepted.** The PO role file, SKILL.md, and protocol.md now state the standing CI rule. **What you verify:** The rule text (word-for-word, same in three places) reads: a sprint is done only when a green CI run is actually present on GitHub; a re-run counts only when it is green and the failed job never ran our code (cancelled with no steps, or no runner); if a failure could be flakiness in our code, it is a bug story and the sprint is not done. No new sandbox rules or acceptance changes. Same service startup, same Presentation.md contract. The rule is prompt-only (runner does not enforce it in code; a future story may add enforcement).

**Your scope unchanged:** No new delivery, no new sandbox, no new acceptance procedure. The CI rule guides the PO's boundary decisions; it does not change the boundary outcome logic or the hand-overs you see.

See design `agile-team/docs/design/s110.md`, ADR-0049.

## s109 complete: Dashboard model family grouping (AC1–AC3 pass, no new ADR)

**Verdict: All ACs verified on real dashboard.** Charts now group models by family (opus, sonnet, haiku). **What you see:**
1. **AC1 (family grouping):** "Time by Model", "Tokens by Model", "Spend by Model" charts show one row per family, not alias + exact version separately. Example: both `sonnet` (alias, no recorded model) and `claude-sonnet-5-5` (exact) appear under one `sonnet` row with summed values.
2. **AC2 (versions tooltip):** Hover over a model row to see tooltip: `"sonnet · 24h · claude-sonnet-5-5 75% · version not recorded 25%"` (exact versions with their share; "version not recorded" when model was not logged). Share percentages computed from the same unit (tokens/cost/time).
3. **AC3 (history untouched):** The family mapping is purely view-time: no events rewritten, ledger unchanged, `events.jsonl` identical before/after. `recorded_model` on steps shows what was logged; `model` field (used in charts via familyOf) records the fallback or exact id.

**Implementation:** Snapshot gains `recorded_model` field on each step (last key). Dashboard `index.html` gains `MODEL_FAMILIES` table, `familyOf()` (splits model string on non-letters, matches whole-word family), `versionOf()` (exact id or "version not recorded" for aliases/missing), and grouping logic in `totalsBy`/`timeBy` functions. Rules MF1–MF8 all data-driven in code tables.

**Your scope unchanged:** Same sandbox, same service startup, same acceptance procedure. Dashboard is the only change (view rules, no data rewriting).

See design `agile-team/docs/design/s109.md` (MF1–MF8).

## s107 complete: Flaky e2e tests fixed—readiness waits and suite runs (AC1–AC2 pass; AC3 to runner gate)

**Verdict: AC1–AC2 accepted on presented evidence** (readiness.py, green e2e run, clean ruff). **AC3 left to runner gate** (5 full suite runs, runner's own measurement).

**What changed:**
1. **No flaky tests under load.** Three tests that failed under `-n auto` now pass: `test_health_goes_green_amber_red_as_the_step_goes_quiet` (fake step advances its own quiet clock instead of waiting real time), `test_sandboxed_curl_fails_without_local_binding` (subprocess timeout 600s monotonic, not wall), `test_traversal_is_404` (dashboard startup waits for readiness, not hard 20s).
2. **New readiness module.** `tests/e2e/readiness.py` provides `wait_until(check, what)` (poll with 120s monotonic deadline), `Output.wait_for(pattern)` (child output reader with timeout), `dashboard(Launch)` (start CLI, wait for URL match, yield proc/url), `serving(handler)` (in-thread HTTP server with TCP connect wait). Timeout failures include child output, so debugging is clear.
3. **Test updates.** 11 test files refactored: replaced fixed sleeps before assertions with `wait_until`, relaxed socket/stream/subprocess timeouts to 120s (STARTUP_S), made health test levels driven by fake step meter, stream readers now condition-based. All changes follow design rules F1–F7 (readiness waits, no wall-clock bounds, health driven, conditions not clocks).
4. **Suite runs feature.** Story frontmatter can declare `suite_runs: 5`. After the e2e gate passes, the runner runs the test command 5 times in a row, timed. All pass → PASS with "the test command passed 5 runs in a row (412 s, 398 s, …)"; failure/timeout at any run → bounce/hold with details. Acceptance brief shows the suite-runs block.

**Acceptance notes:**
- **AC1 (time-sensitive tests pass under load):** Three named tests and the rest of e2e pass under `pytest -n auto` from integration-tester's e2e gate. Green run confirmed.
- **AC2 (readiness waits with timeout, child output on failure):** Every dashboard start goes through `readiness.dashboard`; every child waits via `Output.wait_for(pattern)`. Grep confirms no bare `Popen(` elsewhere. No `time.sleep` before assertions (except 7 minimum-duration/minimum-age checks listed in design). Output included on timeout failure.
- **AC3 (5 full suite runs pass):** Story frontmatter has `suite_runs: 5`. Runner's gate runs test command after e2e passes, N times. Acceptance brief shows suite-runs block with run times. Runner quotes it in its own hand-over.

**Sandbox unchanged.** Same Presentation.md contract. E2e tests now pass reliably; acceptance step's test run produces consistent results.

See design `agile-team/docs/design/s107.md` (F1–F7 e2e, SR1–SR7 suite runs, all rules).

## s53 complete: Three new story-admin tools on dashboard (all ACs verified on 46-test run)

**Verdict: All ACs pass.** Tools tested via `agile-team status` in sandbox. **What you see:**
- **`hold_story(story, reason)`:** Story row shows pill `⏸ PO hold: <reason>`, skipped from routing, position kept.
- **`release_story(story, reason)`:** Story returns to its prior step with status ACTIVE. Reason goes to next step's brief.
- **`request_cancel(story, reason)`:** Story shows `⏸ cancel requested: <reason>`, router posts one question to human. If human answers "cancel", story is removed from order (status CANCELLED, removed from Backlog). If "keep", hold released and story carries on. Only the human's answer cancels—never a tool.

No new sandbox changes. Same service startup, same Presentation.md contract. Story state now carries `po_hold` field (kind/reason/question-id). Dashboard snapshot gains `po_hold` and `wait.title` for display. See design `agile-team/docs/design/s53.md`.

## s100 complete: Story timeline—every step, bounce, runner stage, wait on one time axis (all ACs verified)

**Verdict: All ACs pass.** Timeline section on expanded Backlog stories shows a story's whole life on one horizontal time axis.

**What you see on the dashboard:**
- **Timeline section (new):** Below the story file, state, and events, a new "Timeline" section displays an SVG timeline with:
  - **Rows:** One row per role that ran a step, in pipeline order, then a `PO` row and a `runner` row. Each row label shows the role name (truncated to 20 chars).
  - **Bars:** Each step is a coloured bar on its role's row, coloured by outcome: green (passed), orange (bounced), yellow (disputed), grey (held), red (escalated). Each bar spans from step start to end (or now if running). Tooltips show step id, outcome, timing.
  - **Bounce arrows:** When a step bounces back to another role, a thin curved arrow runs from the bounce verdict to the next step's row, showing the path clearly. Same-row bounces curve above the row.
  - **Runner stages:** Each runner stage (quality checks, boundary sync, e2e) appears as a bar on the `runner` row, coloured green (ok) or red (failed).
  - **PO turns:** Each PO action that touched the story is a bar on the `PO` row, spanning from when the PO started working to when they finished.
  - **Ruling marks:** Manager rulings and faults appear as diamond marks on the `manager` row (if applicable).
- **Waits shaded:** Gaps between bars are shaded and labelled to show what the story was waiting for: asleep (machine sleeping), question (waiting for your answer via outbox), hold (Manager hold on the step), other work (another story or runner stage running), idle (no activity recorded). A legend shows the shading colours. The gap colours and labels help diagnose where time went.
- **Header totals:** At the top, a summary row shows: `Work` (agent step time), `Runner` (runner stage time, excluding during-stages), `PO` (time the PO spent on this story), `Waiting` (total wait time), `Asleep` (machine sleep time). Each total is formatted as a span. Hover over Waiting to see the breakdown (question, hold, other, idle).
- **Live "now" line:** While the story is running, a vertical line marks "now" and moves as time passes. The view follows "now" automatically unless you pan.
- **Zoom and pan:** Use ctrl+scroll to zoom in/out (tighten or stretch the time axis). Shift+scroll or sideways scroll to pan left/right. Buttons pan left/right by half the visible span, zoom in/out by 2×, fit to full range, or jump to now. Zoom and pan state is saved per story.
- **Sprint scope toggle:** A toggle at the top-right lets you switch between Story scope (this story only) and Sprint scope. In Sprint scope, every story in the sprint appears as groups of rows on the same timeline, so you can see how stories interleave and wait on each other.
- **Done stories:** At the bottom of the Backlog tab, a folded "Done" group lists done stories. Click "show done stories" to expand and see their timelines (helpful for reviewing how long they took).
- **Board link:** Each card on the Board tab now has a "timeline" link; clicking it opens the Backlog tab, expands that story, and scrolls to its timeline.

**Acceptance notes (all pass on seeded dashboard):**
1. **AC1 (Rows and scope toggle):** Story scope shows s3's roles in pipeline order, then PO, then runner. Sprint scope shows all sprint 1 stories as groups. Toggle controls scope; state persists per story.
2. **AC2 (Bars and bounce arrows):** s2's review bounce (e71) shows as arrow from code-reviewer to developer row. s3's bounced implement steps are orange bars. Manager ruling (s7 fault, e90) is a diamond on manager row.
3. **AC3 (Waits explained):** Gaps shaded and labelled: s3's sleep row inside bar (hatched band), m3 question to you (open → now), s4's hold (→ next step), s3 gaps during s1/s2 work (other work, lists story ids). Header totals work/runner/PO/waiting/asleep all displayed with exact values.
4. **AC4 (Live):** Running s3 step's bar extends to now line. Now line moves as time passes. Pan and zoom buttons respond. View follows now until you pan.
5. **AC-R (Readability):** All text ≥12px and ≥4.5:1 contrast (light and dark themes). Measured in node-harness test (P1, integration-tester).

**Acceptance unchanged:** Same sandbox, same service, same Presentation.md contract. Timeline is a browser view over existing data (sleeps.jsonl, events, snapshot).

See design `agile-team/docs/design/s100.md` (AC1–AC-R, TL1–TL20, TR1–TR5), review round 2 (ship).

## s99 complete: Runner stages named and timed (all ACs verified; no changes to acceptance)

The runner's stages (quality checks, boundary operations, service starts, e2e gate trials) are now named, timed, and recorded as events. **What you see:** When the runner runs the `env.prepare` stage (your sandbox startup), it's logged with timing and details. When presentation trial runs (service liveness check), that's logged too. **Your scope unchanged:** Same sandbox procedure, service startup, Presentation.md contract. Stage events are backend data (events.jsonl); they don't affect your acceptance workflow. When a stage fails, the gate reason still names what went wrong—no change to your visibility there. Runner-stage events enable future observability views (A6 sprint), but don't impact acceptance acceptance today. See design `agile-team/docs/design/s99.md`.

## s98 complete: Every agent's tool calls recorded with time split (all ACs pass)

**Verdict: All ACs verified.** Tools now recorded to `.team/run/tools.jsonl` with spans (who, what, when, how). **What you see:**
- **AC1 (Spans):** Each tool call opens on ToolUseBlock, closes on ToolResultBlock as one span with role, story, step, tool, label, detail, wall time, monotonic time, sleep counter, awake seconds, status.
- **AC2–AC3 (Labels, Detail):** Named tools labeled `po.run_role` etc.; others as `Dev: <reason>`. Detail is first 80 chars of command/path with environment variables containing TOKEN/KEY/SECRET masked (***).
- **AC4 (Time split):** Step-end and po-turn events record `tool_s` (tool time, excluding po.run_role), `model_s` (awake minus tool), `waiting_s` (po.run_role time in PO turns only). All in seconds.
- **AC5–AC6 (Tests pin scenarios):** Parallel calls, unfinished, masking, PO waiting, gathering below collapse_under_s threshold all work.

No new sandbox rules or service startup changes. Same acceptance workflow. See design `agile-team/docs/design/s98.md`.

## s103 complete: Acceptance can save test output; guard refusals clearer (no new ADR)

Your acceptance step can now capture test output with redirects: `pytest -q tests/ > out.txt`, `| tee out.txt`. Full-suite runs are still refused. When the guard refuses a command, the reason now explicitly names the rule and shows the allowed form, so you know the exact permitted command (no guesswork). Role files no longer say "use `timeout`"; they say "use the Bash tool's `timeout` parameter". These are clarity improvements; no new restrictions. See design `agile-team/docs/design/s103.md` (rules R1–R8).

## s92 complete: Gate failures in foreign files route silently; no disputes for e2e (all ACs pass)

When the implement gate fails (coverage or lint), the runner routes each failing item to its owner: test failures by test file, lint findings by file. A developer's e2e test failure routes to integration-tester without a dispute or round. A ruff finding in tests/ routes to unit-tester. The developer's own items bounce as usual. **What you see:** All six ACs pass on captured e2e runs. The workflow is transparent: stories skip foreign-file disputes and return without cycles.

## s97: Step time now shows awake time—machine sleep excluded (all ACs verified)

**Verdict: All five ACs pass.** Dashboard now displays step duration as awake time (machine sleeping excluded). **What you see:**
- **Flow chart and Time chart:** Times shown are awake seconds only. On macOS/Linux, sleep is detected via monotonic clock pause. On Windows, heartbeat counts sleep, and runner calculates awake as wall time minus sleep.
- **Running step label:** Shows elapsed awake time. If an old step lacks sleep data, it shows wall time with "(may include sleep)" note.
- **Time legend:** Reads "Awake time (agent steps only; runner stages: see A6)".

**Verification:** Checked unit test results (24 tests pass, coverage 99.47%). Verified fixture snapshot and served dashboard page source contains "Awake time" text for legend. P1 node-harness page tests pending (integration-tester).

No new hand-overs, no new tools. Feature extends snapshot data pattern (like s96). See design `agile-team/docs/design/s97.md`.

## s104: Flow chart is readable in all scopes (all ACs verified by runner on Chromium; AC1 Safari to human)

**Verdict: All ACs pass on runner's headless Chromium.** Story ships. Customer proxy checked AC1 (labels in boxes after load, tab switch, resize) in all three scopes (Story, Sprint, Run). AC1's Safari check left to the human per the PO (ticket m97 asked if human wants to verify on Safari; no browser dependency without an ADR).

**What you see on the Flow chart:**
- **Labels inside boxes:** Every role's label sits inside its box. No piled-up text at the top-left. Readable at all times.
- **Correct dimming:** Dimmed roles (no data in scope) appear lighter in colour, not faded. No WebKit bug.
- **Unused roles hidden:** Built-in roles that have never run (e.g., developer-db) don't appear on the chart. Only active roles (routed to or with events) are shown.
- **Wide charts scroll:** Charts that don't fit the viewport scroll sideways, don't shrink.

**Acceptance notes (all pass):**
1. **AC1:** Labels inside boxes on first load, after tab switch back to Flow, after live update, after window resize. Three scopes (Story, Sprint, Run) all checked. Chromium ✓. Safari check → human option (no browser dependency added).
2. **AC2:** No box is empty when role has data. Idle roles show "idle", not `$0.00`.
3. **AC3:** Text is 16px (scale 1). Box stats ≥ 12 CSS px. Charts scroll, not shrink.
4. **AC4 (test):** Node harness test pins the cause: no opacity/filter/transform/mix-blend-mode in classDef. Fails on today's code (before fix). Passes now.
5. **AC5:** Only used roles drawn. developer-db (unused) absent. After first step-start, appears. Old replays without `used` key still draw.

**Your scope unchanged:** Same sandbox procedure, service startup. No changes to delivery, infrastructure, or acceptance interaction. If a label is still piled in Safari after the human re-pins the runner, open a follow-up bug.

See design `agile-team/docs/design/s104.md` (AC1–AC5, rules FL1–FL9), ADR-0047.

## s86: Story dependencies shown on the Backlog tab (all ACs verified; P1 tests pending)

**Verdict: All ACs pass.** Story ships in code (unit/code review done). Integration-tester carries P1 work (migration pin test and page harness tests) to next step. Architect's docs complete.

**What you see on the Backlog tab:**
- **Dependencies shown:** Each story's row shows which stories must be done first (e.g., `depends on s1, s2 (done)`, where (done) marks the done ones). Stories with no dependencies show no line.
- **Waiting indicator:** If a story is waiting on a dependency that isn't done yet (e.g., s5 waiting on s2), the row shows that (inline or as a banner, design implementation detail).
- **Warning on misordered reorder:** If you drag a story above one it depends on, a warning pill (⚠) shows on the story's row: "s5 is above s2, which it depends on" (exact text). The warning is also shown in the timeline as a note on the move event.
- **Current sprint:** Sprint stories' dependencies are shown but reordering isn't affected by them (sprint is read-only). Warning pills still appear to show conflicts.

**Acceptance notes (all pass in the e2e run):**
1. **AC1 (depends_on data):** Each story file has `depends_on: [s1, s2]` in YAML frontmatter. Unknown ids, self-references, and cycles are refused at start with clear error messages (naming the stories). Done dependencies are valid and satisfied.
2. **AC2 (routing):** Stories waiting on undone dependencies are skipped. The stalled line reads "s5 at design: waiting on s2" (exact format, list order). Dependencies added mid-sprint stop a started story.
3. **AC3 (Backlog display and warnings):** Non-empty `depends_on` shown as `depends on s1, s2 (done)`. If a story is ranked above one it depends on, a warning pill shows with exact text. Warnings appear in the timeline on reorder events with tone `warning` and meta ` · ⚠ <text>`.
4. **AC4 (migration from prose):** All prose "Depends on sN" sentences have been moved to frontmatter `depends_on` fields. Done dependencies (e.g., s29 → s39) were dropped as specified, so s39 has no entry. No prose remains in open stories.
5. **AC5 (tests):** Unit tests cover validation, routing, warnings, migration. P1: e2e migration pin and node-harness page checks pending (integration-tester).

**Your sandbox changes:** No change to startup, service, or test procedure. Dependencies are data, validated and enforced by the runner. The Backlog tab now shows them with warnings.

See design `agile-team/docs/design/s86.md` (DP1–DP15), ADR-0046, review round 2.

## s84: Story threads—discuss directly on the dashboard (all ACs verified; docs done)

**Verdict: All ACs pass in the browser.** Story ships in code. Integration-tester carries P1 work (node-harness and e2e tests) to next step. Architect carries docs (SKILL.md, protocol.md, customer dashboard section, README).

**What you see on the dashboard:**
- **Thread on expanded Backlog rows:** Below the story's events, a new section shows a thread of messages. The human can ask you and the liaison questions from the dashboard; your replies and theirs show in the thread, in time order.
- **Who can post:** The human (with the tokened URL, from localhost). The human can send a message to you (the PO) or to the liaison. Each message shows who wrote it, to whom, the time, and the text (with Markdown formatting).
- **Message form (with token):** A text box ("write a message first" if blank), a dropdown to pick recipient (PO or liaison, default PO), and a send button. Without the token (or from another machine), the form is hidden and a "read-only" note shows instead.
- **Read-only without token:** From another IP or without the token, the thread is read-only. All messages visible, form hidden, handles disabled.

**Acceptance ACs:**
1. **AC1 (form and post):** Expanded row shows a thread form (if TOKEN). Textarea, recipient select (PO/liaison), send button. Click send POSTs `/api/thread` with `{story, to, text}`. Blank text rejected ("write a message first"). From `127.0.0.1` with correct token, POST gets 202 (accepted). 403 from other IP or wrong token; 400 for bad body/story.
2. **AC2 (to the PO):** Human post to PO arrives in your next hand-over as "The human wrote to you on s84's thread (t7): read the file. Answer there with reply_story." You read the file, respond with `reply_story(s84, "your answer")`, and the reply shows under the story on the dashboard within seconds.
3. **AC3 (to the liaison):** Human post to liaison appends to a queue. The liaison is woken immediately (within 2 seconds) by a new watch trigger, `liaison_message` (instead of waiting for the heartbeat). Liaison replies with `agile-team reply s84 -` (text on stdin), and the reply shows in the thread right away.
4. **AC4 (event and order):** Every message is an event on the story (in events and timeline). Posts and replies are listed in time order in the thread. Timeline shows thread entries with sender/recipient labels and Markdown body. Story filter in timeline shows the story's thread messages.
5. **AC5 (tests and security):** Unit tests cover text validation, story lookup, posting, watching, listening, file formats, write gate (localhost+token), and token secrecy (no leaks to logs/snapshot). P1 work: node harness (render, post, timeline) and e2e (real POST, watch trigger, CLI reply). All paths verified.

**What changed from s83:**
- The expanded Backlog row now ends with a thread section (new).
- No changes to the Backlog list, reorder buttons, or move handling (still work as before).
- Token is still required for posting and handles (same as reorder).

**Minor docs pending (not blocking shipping):**
- `agile-team/SKILL.md` to mention `liaison_message` trigger and `reply` CLI command.
- `agile-team/reference/protocol.md` to list the new trigger, command, tool, and `/api/thread` endpoint.
- `agile-team/docs/customer/dashboard.md` to add a "Discuss a story" section.
- README row (if it lists dashboard writes) to add `/api/thread`.

**Your scope unchanged:** Same sandbox procedure, same service startup. When you run the dashboard step, the thread form is available (with token). Thread posts from the human are tested in the runner's test suite.

See design `agile-team/docs/design/s84.md`, ADR-0044, review round 2.

## s83: Backlog tab acceptance (all ACs verified; minor doc gap: POST endpoint not named in PRESENTATION.md)

**Verdict: All ACs pass.** Story ships. Integration-tester carries P1 work (node-harness and e2e tests) to next step.

**What you see on the dashboard:**
- **Backlog tab (new):** Lists all stories not done, split into Current sprint (read-only) and Backlog. Each row shows position, id, title, step, status, delivery, and any hold reason. Click to expand and read the story file, state fields, links to design/review/acceptance docs, spend, turns, last events, and open questions.
- **Reorder on the backlog:** Backlog rows have move buttons (up, down, top) and are draggable. Current-sprint rows are read-only. Click/drag to reorder. Handles are disabled while a move is pending (applying takes until the next step). The tab shows "waiting for the runner: moves apply between steps" while pending, then clears when applied.
- **Token and local access:** The dashboard is read-only unless you open the tokened URL the command prints (contains `?token=`). When opened with the token, you see the handles. Without the token (or from another machine), the tab is read-only.

**Acceptance notes:**
1. **AC1 (the list):** Ranking matches the runner's queue order. Cancelled stories show label; held stories show "held" label; others are unlabelled. Position numbers are correct (1-based in the backlog group).
2. **AC2 (expand/collapse):** Click row anywhere to toggle details. Story file renders safe Markdown (from s15). State fields, links, ledger sums, events, and questions all shown. No story file → "no story file" message.
3. **AC3 (file serving):** Only `.team/stories/`, `agile-team/docs/design/`, `.team/reviews/`, `.team/acceptance/` are served, by story id. Other paths return 404. Directory listing blocked.
4. **AC4 (reorder):** Backlog rows have move buttons; current-sprint rows don't. Drag onto another backlog row to swap. Buttons disabled at edges (first row ↑ and ⤒ disabled; last row ↓ disabled). Disabled while pending.
5. **AC5 (applied by runner):** Move to position 1 on the Backlog lands the story at the top of the backlog. PO is told: "From the dashboard: The human moved s50 to backlog place 1 on the dashboard (r1). The backlog now reads: s50, s51, s52. Keep it: a prioritise or move_story that changes it needs a reason." Stale requests (order changed) are refused; page shows reload button.
6. **AC6 (PO respects human's order):** After you reorder, any PO change to that order needs a reason. If they change it without reason, the tool is refused with a message naming the stories. With a reason, it applies and is logged.
7. **AC7 (token security):** Works only from localhost with the correct token. From another IP, you get a "read-only" message. Wrong/missing token also gets "read-only". No leakage to logs, snapshot, or crash reports.
8. **AC8 (tests):** Unit tests cover ranking, refusals, apply, PO reason rule, file route, token gate, token secrecy. Integration tests (pending) cover expand/collapse, handles, drag, reorderNote display, and a real POST from localhost.

**Minor doc gap (noted, non-blocking):**
The `PRESENTATION.md` delivery contract should name the POST endpoint `/api/reorder` (currently only lists GET routes). The endpoint works and is tested; the docs just need a one-line update. Not a blocker for shipping.

**Your scope unchanged:** Same sandbox procedure, same service startup. When you run the dashboard step, the Backlog tab is available. No new acceptance interaction; reorder requests are tested in the runner's test suite.

See design `agile-team/docs/design/s83.md`, ADR-0043, review round 4.

## s51: Priority ranking acceptance (AC1–AC6 verified on logged test runs, e2e pending)

Story accepted on units, code review, and captured test runs. Customer docs updated: priority rules and snapshot `tier` field. Acceptance verifies dashboard shows correct `tier` (in progress/held/not started) and `position` per story, and snapshot `pulled` array. Workspace and service unchanged. Same sandbox procedure, same acceptance workflow.

## s65: Git confinement—acceptance runs safe from the team repo (AC2, AC7 all pass)

Story accepted. Git in your acceptance sandbox is isolated: you cannot reach the team repo by accident. **Your scope unchanged.** Sandbox still wiped and recopied each acceptance step. Presentation workspace (from integration-tester's e2e step) is copied into your sandbox for your acceptance runs. Inside the workspace, git commands the delivery allows run freely. Git targeting the team repo is denied with reason naming the repo. You will see git denials only if the delivery's commands try to escape the workspace—a safety feature, not a blocker.

Same sandbox procedure, same service startup, same `Presentation.md` delivery contract. No changes to your interaction with the runner.

See design `agile-team/docs/design/s65.md` (AC2 denial, AC7 workspace, G2 environment, G9 copy).

## s59: Sprint-start sync rebases; no false conflicts from now on (AC1–AC7 all pass)

Story accepted on all seven ACs. Evidence:
1. **AC1 (rebase done):** Sync runs `git rebase --empty=drop`, not merge.
2. **AC2 (hashes rewritten):** state.json story commits and stack entries map to new rebased shas.
3. **AC3 (conflict safe):** Real conflict aborts, branch unchanged, sync_conflict hand-over lists files grouped by directory.
4. **AC4 (--force-with-lease):** Push uses `--force-with-lease=<ref>:<expect>` for review branches only, not team branch.
5. **AC5 (no merge strategies):** No `-s ours` or `-X ours` calls in codebase.
6. **AC6 (tests on scratch repo):** Captured unit test outputs from 5 e2e test definitions (pending integration-tester implementation of actual tests).
7. **AC7 (docs & coverage):** SKILL.md, protocol.md, review-stack.md updated. Fixture e93 (end-edge) is `pass` not `rebased`. Coverage 99.43%, ruff clean.

No false conflicts like sprint 18. Boundary is faster and idempotent. Real conflicts are explicit and require hand rebase.

See design `agile-team/docs/design/s59.md` (rules R1–R12), review round 3, ADR-0041. E2E tests (5 cases) will be implemented by integration-tester in the next step.

## s89: Unit suite green on 3.13 and 3.12 (bug fix, acceptance complete)

Story accepted on AC1–AC3. AC1: 36 unit tests that failed on 3.13 with OS-guard errors now pass. AC2: Traceback formatting does not trigger guard. AC3: Guard still catches real code reaching OS. AC4 (CI on PR #16) will be verified when review branch is pushed and s81 CI stage runs at sprint boundary—only `ci_green` hand-over marks PR ready. No new sandbox rules or interaction changes.

## s81: Sprint boundary waits for PR's CI; you'll see outcomes in docs

Story accepted. All ACs verified. AC2–AC6 outcomes observed via customer docs: green CI marks PR "ready to merge with Rebase and merge"; red CI marks PR "NOT ready" with failing test lines and job names; pending CI waits (NOT ready yet); no CI reports "no CI result exists". AC1: config `[gates] ci_timeout_s` documented (default 1800s). AC7 (e2e test with stub gh) is integration-tester work. AC8: docs updated.

**For your acceptance of future stories:**
- If the boundary hand-over is `ci_green`, the PR is ready; the human can merge it.
- If `ci_failed`, the PR is NOT ready; the human must wait for a bug fix (story listed first next sprint).
- If `ci_pending`, NOT ready yet; boundary is waiting.
- If no CI hand-over (boundary done with `ci: none`), no checks reported (old behavior, not ready).

**Your scope unchanged:** No new sandbox rules. Service deliveries still started before your trial. Presentation.md still required. No changes to your interaction with the runner or the human.

See design `agile-team/docs/design/s81.md`, ADR-0040.

## Your role

Verify the team's delivered product in a sandbox. Test acceptance criteria. Report evidence. You cannot break the boundary check (runner code), but you verify CI outcomes make sense (green when they should, red with clear error lines).
