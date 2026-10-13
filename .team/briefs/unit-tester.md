# Unit Tester: Current context and conventions

**Last updated:** 2026-10-13 (s99 done; s98 done; s105 done; s103 done; s92 done; s97 done; s104 done; s96 done, P1 pending; s86 done)

## s99 complete: Runner stages table, timing, config loading (coverage ≥95%, ruff clean, all pass)

New modules `stages.py` and `stage_log.py`. Test areas: **AC1 table:** 21 stages with unique names, descriptions, when/attach enums, exact table match (env.prepare, presentation.layout, checkout.guard, gate.tests+coverage, boundary.sync, runner-tool.run_tests, etc.). Unlisted stages fail KeyError. Mappings (QUALITY, BOUNDARY, RUNNER_TOOL) cover their sources. **RS3:** notes with no open stage do nothing; inside unlogged block reach run; after block reach nothing; asyncio.to_thread inside stage reaches it. **RS5:** notes (a,0), (b,0) → detail b, code 0; (a,0), (b,2), (c,0) → b, 2; no notes → detail "", code 0 or null. Masking: TOKEN=abc → TOKEN=*** in 80-char detail. **RS6:** raise GitError → event with raised "GitError", exception propagates. **AC4 awake:** fake Marker, POSIX monotonic delta, Windows wall minus sleep, rounded to 3 decimals. **RS7/RS8:** event keys in order, role "runner", story/step from Place. **RS10:** OSError suppressed. **AC2 tools:** [[tool]] loads, name clash refused (gate.*, po.*, etc.), empty description/command refused. **AC2 agile-team tools:** prints JSON with built_in (21 rows) and repo lists. All checklist items pass. No test deleted. See design `agile-team/docs/design/s99.md` (RS1–RS14).

## s105 complete: Seed tests—delivery config, planting, checks, problem reporting (coverage ≥95%, ruff clean, all pass)

New module `seeds.py` (pure + I/O, ~220 LOC): `seed_dir()` resolves delivery seed (S1 table: None→default for kind via `DEFAULT_SEEDS`; `""` → None; path → repo/path), `Seeds` class plants files and checks problems (S2–S3), `CHECKS` table with `config_problem` validator. Tests cover: config load/defaults (None absent, web→PACKAGED_SEED, package→None, ""→None), seed_dir table rows, Seeds.names (skips dirs), plant (missing only, creates workspace, preserves existing), problems (SEED_GONE message, BROKEN for unparsable config and bad DASHBOARD_TOKEN, good config→[]). `FakeSystem.PACKAGE_DATA` gains `"dashboard/seed/.agile-team.toml"`. `Delivery.seed` field moves before `probe` (probe still last, per AC). `config.py` seed load as `None`/string. `Prepared.seeds` field and `seed_problems()` method. `presentation.lay_out` and `sandbox._present` plant seeds into source and sandbox workspaces. `_not_up_reason` includes seed problems. `presentation.missing` ignores seeded files via `_has_content(workspace, seeds)`. All 14 checklist items pass (table rows, planting, problem checks, broken config, packaged seed, NotUp reason, lay_out/missing). No test deleted. Coverage ≥95%, ruff clean.

## s103 complete: Keep unit test output with redirects; refusals name rules (no new ADR)

You can now save a unit test run's output: `pytest tests/test_x.py > out.txt`, `>> out.txt`, `2> err.txt`, `| tee out.txt`. Full-suite runs are still refused. When the guard refuses your command, the reason now names the rule violated and the allowed form, so you know what to try next (no guesswork). Role files no longer say "use `timeout` command"; they say "use the Bash tool's `timeout` parameter". This is for macOS (which has no `timeout` command). See design `agile-team/docs/design/s103.md` (rules R1–R8).

## s92 complete: Gate fix steps for lint findings in test files (no new ADR)

When the implement gate fails with a lint finding (ruff, flake8, mypy, etc.) in `tests/` files, the runner creates a gate fix step for you. Your brief lists only your items (failing tests or lint findings in files you own) and the exact ruff output. Fix only those items, then hand off `done`. The story pops the queue and returns to the developer, no round counted. **Dispatch notes:** Failing unit tests stay with the developer (TDD rule: red tests are theirs to make green). Lint in unit-test files comes to you. E2E test failures go to integration-tester. Design spec: rules R1–R20, test checklist items 1–27 in `agile-team/docs/design/s92.md`.

## s97 complete: Awake-time calculation—clocks, heartbeat, platform rules (24 unit tests pass, P1 pending)

**Files:** `tests/test_s97_step_times.py` (pure, ~350 LOC), `tests/test_s97_clocks.py` (runner clocks with FakeSystem), `tests/test_s97_snapshot.py` (snapshot awake building).

**Unit tests (step_times.py, pure):**
- POSIX: mono 1000→1100, wall 100→400 gives seconds=100, clock="awake", slept=200 (AC2, AC5).
- Windows: wall 100→400, slept 30→230 gives seconds=100 (same formula); mono-only falls back to wall (AC3, AC5).
- Fallback: no clocks → wall, clock="wall", slept=0 on both platforms (AC2, AC5).
- Reboot: end mono < start mono → wall fallback. Windows end slept < start slept → wall (AW5–AW6).
- Bool/string mono → missing. `number()` rejects non-numeric (AW3).
- Killed: seconds/clock/slept all None (AW8).
- Running: start at=100, mono=1000; now at=700, mono=1300 → seconds=None, clock="awake", slept=300 (AW9).
- Platform POSIX: win32→Windows, darwin/linux/cygwin→POSIX (AW4).
- AWAKE has exactly two keys (Platform.POSIX, WINDOWS) (AW7).

**Runner tests (live.py, Pulse with FakeSystem):**
- `_count_sleep`: gap=beat_s adds 0; gap=2×beat_s adds 0 (boundary); gap=10×beat_s adds 9×beat_s. Rounding to 0.1 (AW2).
- `clocks()`: returns {"mono": fake monotonic, "slept": counter} (AW1).
- Step events carry mono/slept on start/end (AW1, AC1).
- `_close_interrupted` writes them on interrupted end (AW1).
- `system.platform()` returns `sys.platform` (seam test). (missing, m2)

**Snapshot tests (snapshot.py):**
- Platform darwin/win32: step with mono 1000→1100, wall/at 100→400 gives seconds=100 on both (AC5).
- Windows: running step with slept uses heartbeat counter (AW9).
- Running without heartbeat → wall time (AW9 fallback).
- Fixture contract: steps have clock/slept; fixture-build test unchanged (s96 contract holds).

**Coverage 99.47%, ruff clean. No test deleted. S96 exact-dict test gains two keys (clock/slept). S44/S78 heartbeat tests gain slept key.**

See design `agile-team/docs/design/s97.md` (AW1–AW13, test checklist, known limits).

## s98 complete: Tool call recording—spans, labels, detail, masking, time splits (all pass, no new ADR)

New `tests/test_tool_calls.py` + additions to `test_live.py`, `test_dispatch.py`, `test_po_tools.py`, `test_tool_groups.py`, `test_config.py`, `test_snapshot.py`. **Test areas:** (1) **tool_calls.py** (pure): call to result → one span (TC11 keys in order, status ok/error/timeout/unfinished); repeated use id ignored; timeout on "timed out" text; parallel calls → separate spans with union for tool_s; `abandon` closes unfinished; labels (po.run_role, runner-tool.run_tests, Dev: <reason>); detail (first 80 chars, masked secrets); masking (GH_TOKEN, api_key, MY_SECRET, AWS_SECRET_ACCESS_KEY, not PATH); PO waiting_s split; union of intervals. (2) **live.py, dispatch.py, po_tools.py** additions: Pulse.take writes spans on result, not use; Pulse.close closes unfinished; step-end has opened_at, tool_s, model_s, waiting_s; po-turn event emitted per PO query. (3) **tool_groups.py** (new): gathering by limit, valid rows, group split. (4) **config.py**: collapse_under_s validation (number, ≥0). (5) **snapshot.py**: tools section present, uses collapse_under_s. All 24+ checklist items pass. No test deleted. See design `agile-team/docs/design/s98.md` (TC1–TC18, AC5–AC6).

## s96 complete: Step time pairing and dashboard display (23 tests pass, P1 pending)

**File:** `tests/test_s96_step_times.py` (pure, no files) + `tests/test_s96_snapshot.py` + `tests/test_s96_time_page.py` (node harness on dashboard_node.py).

**Unit tests (step_times.py):**
- Pairing: start/end pairs give seconds rounded to 0.1 with status/model from end, at from start.
- Matching by (role, story): two roles stepping same story don't cross.
- Running step: open start at log end has null ended_at/seconds/status.
- Killed step: cause="killed" gives null seconds, ended_at set, status="interrupted". Halt preserved time.
- Duplicate key (ST2): second start drops first, ignored end. End with no open start ignored.
- Sprint (ST6): last sprint-start before step gives sprint; null before any.
- Clock rewind (ST3): end before start gives 0, not negative.
- Non-step kinds skipped; result in start order.

**Snapshot tests (snapshot.py):**
- `build` has `steps` after `ledger`.
- Model fallback: end model wins; else configured role model; else "unknown" for unknown role.
- Fixture contract: steps equal `_steps` over fixture events/roles; last step running.

**Dashboard tests (dashboard_node.py, st9–st15 checks):**
- `fmt.span`: 0→0 min, 30→<1 min, 125→2 min, 3725→1 h 2 min.
- `stepTotals(view, k)` sums finished steps grouped by role/story/model; killed steps count, add 0.
- Scope toggle (story/sprint/run): `scopeTotals()[role].seconds` hand-computed sums match.
- `nodeLabel` contains role's fmt.span total.
- Running line: open step 600s before clockNow gives "⏱ running 10 min"; no open step gives "".
- UNITS.time.label="Time", title="Time by", three buttons, title renders.
- `barRows` with time: largest first, tooltip has step count and % of time, value is fmt.span.
- `timeLegend()` exact text "agent steps only; runner stages: see A6".
- `costRow` (Dollars) unchanged by whole rename.
- `stepsAsOf`: start after cursor dropped, end after cursor running.

**Coverage ≥95%, ruff clean. 23 tests pass. P1: node-harness (scope/running/chart tests) and e2e (animation) pending.**

See design `agile-team/docs/design/s96.md` (ST1–ST15, test checklist).

## s104 complete: Flow chart labels pile up fixed—snapshot `used` field, static checks (coverage ≥95%, ruff clean, all pass)

New unit tests `tests/test_s104_snapshot.py` (build on scratch/config fixtures from test_snapshot.py):
- A built-in role that never ran (developer-db, no events, not assigned, not routed to) has `used: false`. After a `step-start` event, next `build` gives `used: true` (AC5, FL7b, FL9).
- With pipeline `design, tests, implement` and no events, `architect` and `unit-tester` are used (FL7a).
- A story with `developer = "developer-cli"` makes `developer-cli` used, then generic `developer` unused. With no story assigned, `developer` is used. `po_developer` same way (FL7a).
- A step left out of pipeline (e.g. no e2e) → integration-tester unused unless that role has `step-start` (FL7).
- Every `roles[]` entry has `used`. Fixture-shape and fixture-value tests from test_snapshot.py still pass.

Static source checks (new file `tests/test_s104_flow_page.py`, no node/process):
- `.flow svg` has no `max-width: 100%`; has `max-width: none`.
- `useMaxWidth: false`, `FLOW_FONT_PX = 16`, `initialize(mermaidConfig(vars))` all present.
- No `idle opacity` in code; `idleClassDef` sets only fill/stroke/color.
- `r.used !== false` filter and `statsText` returning "idle" both present (exact).

Coverage ≥95%, ruff clean. E2E tests (AC4 cause/hidden-then-shown, AC3 size, AC2 idle text, AC5 unused roles, AC1 resize after full run) carried to integration-tester P1. See design `agile-team/docs/design/s104.md` (FL1–FL9, test checklist).

## s86 complete: Story dependencies as data—validation, routing, warnings, snapshot (coverage 99.46%, ruff clean, all pass)

New module `dependencies.py` (~350 LOC, pure + file I/O). Tests cover: `listed` (dedupe, None cases), `declared` (file reads, missing/bad/no-key), `load_refusal` (shape/self/unknown/cycle order), `find_cycle` (DFS, DP7), `graph_refusal` (DP4 b–d), `apply`, `waiting_on` (list order), `above`/`inversions`/`warnings` (DP11–DP13). Routing: skip non-picked story waiting on undone deps, stall line exact. `StoryState.depends_on`, `Runtime.load_dependencies`, `_load_dependencies` CLI. Snapshot: three keys per story. `open_story` accepts `depends_on`, `start_sprint` loads from files. Refusal texts and MISMATCH exact. All texts match design word for word. No tests deleted; coverage 99.46%, ruff clean. See ADR-0046, design `agile-team/docs/design/s86.md` (DP1–DP15, test checklist).

## s85 complete: Liaison opinions—recording, validation, acts, routing, snapshot (coverage 99.46%, ruff clean, all pass)

New `opinions.py` module (pure + file I/O, ~250 LOC) for opinion recording and act handling. Tests cover: recording opinions with refusals (unknown story/kind, empty text); latest-per-story rule; `reviewed` summary; ask_review posting to liaison inbox; act parsing and refusals (unknown, superseded, keep, settled); dismiss/apply routing (move to reorder, others to PO); snapshot building with items, route, acts, events; write gate (403/400/409/202). Design O1–O20, 12 checklist items, snapshot contract match. No tests deleted, coverage 99.46% (opinions.py 100%, threads.py 100%), ruff clean.

See ADR-0045, design `agile-team/docs/design/s85.md` (O1–O20, test checklist).

## s84: Story threads—parsing, validation, file I/O, read merging, dashboard/router/watch/PO integration (coverage ≥99.44%, ruff clean, all pass)

New `threads.py` module for story discussion via dashboard and CLI. Tests cover all 19 design rules (H1–H19) and checklist items 1–13.

**Module tests:**

**`threads.py` (new, pure + file I/O):**
- **Text and story checks:** `text_refusal` refuses blank/whitespace and >4000 chars exactly; `story_refusal` refuses unknown (exact text) and allows done.
- **Parse post:** Valid body (text unstripped OK) → Post; non-object, missing key, bad `to`, bad id, non-str text, blank, over-long → None.
- **To PO (H6–H8):** `Threads.post(Post("s5", PO, text))` writes `liaison/messages/t1.md` with exact head, returns `Entry("t1", "s5", HUMAN, PO, text.strip(), at)`. Two posts → t1, t2. Relay.told() lists them. Router's next `_tick` delivers `human_message` with `THREAD_TOLD_LINE` and stories=[s5]. Plain tell still gives `TOLD_LINE`, no story.
- **`reply_story` (H9):** Unknown story → `UNKNOWN_STORY`, empty → `EMPTY`; neither writes. Good call appends outbox `{kind: "reply", stories: ["s5"], text}`, returns `{"status": "posted", "id": "m<N>"}`. `notify_user(kind="reply")` refused with `USE_REPLY`, posts nothing.
- **To liaison (H10–H11):** `Threads.post(Post("s5", LIAISON, text))` appends one line to `liaison/inbox.jsonl`, returns `lp1`. Second post → lp2. Watch with saved memory fires `liaison_message` trigger, `posts` holds one entry, next watch doesn't repeat. Shorter inbox reports all. Old memory loads with posts=0. First watch takes existing posts as seen. Heartbeat has `posts: []`. Outbox reply still fires `message` trigger.
- **Liaison reply (H12):** `cmd_reply` with file appends to `liaison/replies.jsonl`, prints `replied lr1 on s5`, returns 0. `-` reads stdin. Unknown story, empty file, over-long text raise `CliError` (exact texts), write nothing. Works without running runner.
- **Thread view and order (H13):** One entry of each kind, out-of-file order. `Threads.all()` gives sorted by (at, id) with right authors/to. Torn last line in JSONL skipped, earlier ids unchanged. Outbox reply without stories not an entry. t*.md without head not an entry.
- **Snapshot (H14–H15):** `build` has `thread` (4 dicts), 4 `thread` events (role `"product-owner"` only for PO's reply), no `message` event for reply line, sorted by time. Fixture keys match build (contract test). `watched_files` includes inbox, replies, told files.
- **Write gate (H4):** POST from 127.0.0.1 with token and good body → 202 with id/status. From 10.0.0.5 with token, localhost with bad/missing/empty token, no token in app → 403, body unread. Bad body, unknown story, bad `to`, Content-Length 0/32769, or app.post=None → 400. `/api/reorder` still refuses 4097 bytes.
- **Token never leaks:** Snapshot, told file, inbox line have no token.

**Watch, router, PO tools, relay, CLI integration:**
- Watch: `Seen.posts`, `Look.posts`, `new_posts` logic, `liaison_message` trigger, `posts` in line, `_next` keeping posts. Old memory loads with posts=0.
- Router: `threads.told_line` used; stories = answer stories + tagged stories, deduplicated.
- PO: `reply_story` tool with schema; `notify_user` refuses REPLY kind.
- Relay: REPLY added last in KINDS; `tell` draft named `.draft-{token()}` (collision test).
- CLI: `cmd_reply` and COMMANDS row; refusal texts exact.
- Snapshot: `_thread` section, `_thread_event`, `_events` drops reply from message, `watched_files` includes thread files.

**Checklist items (design) all covered, no tests deleted, coverage ≥99.44%, ruff clean.**

See ADR-0044, design `agile-team/docs/design/s84.md`.

## s83: Backlog, reorders, request parsing, file serving, PO rules tests (coverage ≥95%, ruff clean, all pass)

New modules for dashboard backlog tab and reorder requests. Test all refusals, apply logic, file route, PO human-order rule, state loaders. Design rules B1–B20 enforced in code (test checklist items 1–17 below).

**Module tests:**

**`backlog.py` (pure):**
- `View.of(state)`: Builds queue, backlog, version from state; handles empty, mixed states.
- `order_version()`: Hash changes with queue or backlog change; stable for same state.
- `label()`: Cancelled (hold starts with "cancelled"), held (via `priority.held()`), empty.
- `stale_refusal()`: Exact `STALE` text when version mismatch.
- `sprint_refusal()`: Story in current sprint → `SPRINT_STORY` text; backlog story → None.
- `place_refusal()`: Int 1..len → None; 0, len+1, True, "2" → `BAD_PLACE` with count.
- `guarded()` and `human_refusal()`: Human order guards only in `before` order; changes in `guarded` require reason.

**`reorders.py` (I/O: file queue, apply):**
- `parse_ask()`: Valid {story (matching `STORY_ID`), position (int not bool), version (str ≤64)} → Ask; invalid → None.
- `Request.to_json()`, `Request.from_json()`: Round trip; bad JSON → None.
- `Requests.queue()`: Writes rN.json (draft then hard link, increment on clash, no draft left).
- `Requests.all()`: Lists in order, skips unreadable, skips non-r*.json.
- `Requests.pending()`: Only ids not in settled dict.
- `Desk.apply()`: Applies pending requests in order, calls refusals, records applied/reason, emits event with source and reason.

**`story_files.py` (dashboard file serving):**
- `path_of()`: Valid kind+id+story+file → Path; invalid kind/id/unknown story/missing/directory → None.
- `read()`: Regular file → text; missing/directory → None.
- `existing()`: List kinds with existing files (no state load).
- **File route checks (AC3):** kind=story/design/review/acceptance only; id matches STORY_ID; id in state.json; <folder>/<id>.md regular file. Rejects `kind=secrets`, `id=../x`, `id=/etc/passwd`, `id=s1/..`, `id=s999` (unknown), missing file, missing parameter, directory in any folder.

**PO tools (`po_tools.py` updates for human-order rule):**
- `_human_check()`: Builds HumanCheck with guarded (in before order that changed), before/after queues.
- `human_refusal()`: If guarded is non-empty and before≠after, refuse with exact `HUMAN_ORDER` text naming guarded ids. With reason, apply.
- `prioritise()` and `move_story()` add third check: human_refusal after existing checks.
- `_take_reorders()`: Returns section text with `TOLD_HEAD` and lines; clears `state.reorders_told`; saves.

**State loaders (AC1 compatibility):**
- Old `state.json` without `human_order`, `reorders`, `reorders_told` loads with empty defaults.

**Dispatch and router (`dispatch.py`, `router.py`):**
- `Runtime.reorder()`: Builds before, applies move, saves, builds after, emits event with source and reason.
- `Router._tick`: Calls `self.desk.apply()` right after checkout check, before news and work.
- No request applied twice (skips ids already in state.reorders).

**Test items (design checklist, all pass):**
1. Ranking shown: order, backlog in snapshot match Priority.queue order; labels correct (cancelled/held/"").
2. Snapshot fields: disputes, developer, commits (deduped, no None), files (existing kinds in table order), order_version.
3. Order version stable and changes on order/sprint change.
4. Sprint-story refusal: `SPRINT_STORY` recorded, order/events unchanged.
5. Stale refusal: exactly `STALE`, order unchanged, second request from same version is `STALE`.
6. Bad place (0, len+1, True, "2"), unknown, done stories.
7. Apply: Backlog move to place 1 lands at top. Event: role=None, source="human (dashboard)", reason="moved on the dashboard (rN)". human_order equals new backlog; state.reorders["rN"]="applied"; reorders_told has exact `TOLD` line.
8. PO events: source="product-owner", role="product-owner".
9. PO reason rule: human_order=[s5,s6]: move swapping them with no reason refused with exact `HUMAN_ORDER` (naming s5,s6), nothing changes. Same move with reason applies; reason in event. Sprint-story move leaving s5/s6 order needs no reason. Empty human_order needs none. start_sprint never refused.
10. PO told: After applied request, next hand-over contains `TOLD_HEAD` and line; reorders_told empty and saved.
11. Router: _tick applies pending requests before picking work. Request in state.reorders not applied again.
12. Requests: queue writes r1, r2, no draft. Clash on N → N+1. all skips unreadable/wrong names. parse_ask rejects non-object, missing key, bool position, bad id, version>64.
13. File route: GET /api/file?kind=story&id=s1 → text/plain. 404: kind=secrets, id=../state, id=/etc/passwd, id=s1/.., id=s999, missing, missing param, directory.
14. Write gate: 127.0.0.1 + right token → 202. 10.0.0.5 + right token → 403. 127.0.0.1 + wrong token → 403. Empty app.token + empty header → 403. No body read on 403. Bad body/size → 400. POST elsewhere → 404.
15. Token never leaks: absent from snapshot JSON, events.jsonl, request file, crash.log.
16. CLI: Prints `dashboard: http://localhost:<p>/?token=tok1` (fake). --token abc → ?token=abc. [dashboard] token="cfg" and no --token → ?token=cfg. --token wins. token="" → fake random tok1.
16a. Config: No [dashboard] → token="". token="x" → "x". token=1 → ConfigError with exact `DASHBOARD_TOKEN` text.
17. State: Old state.json without three fields loads with empty defaults.

**No tests deleted. Coverage ≥95%, ruff clean.** Design rules B1–B20 enforced (see design `agile-team/docs/design/s83.md`).

See ADR-0043.

## s51: Priority ranking tests (2 rounds, 99.41% coverage, ruff clean, all pass)

Test `priority.py`: `started()` (commit=None false), `held()` (hold, BLOCKED, NEEDS_MANAGER true), `tier()` (three groups + pulled), `pulls()` (not-started before last started), `set_pull()` (Pull.judged and Pull.ahead), `pull_refusal()` (reason required text), `plan()` (listed by place, unlisted by natural), `with_first()` (builds on plan order), `with_move()` rules 1–3, `repulled()` (cleanup), `first_refusal()` (calls in turn, short-circuit). PO tools: move without reason refused, with reason pulls; prioritise lists before started, unpulls when listed after started; start_sprint with CI bug pulls it. Worked example end-to-end (s45/s38/s21 case). `state.json` loads without `pulled` (defaults []). Router tests: started story routes first. Coverage ≥95%, ruff clean. See design test checklist, all items done. ADR-0016 amended.

## s65: Git confinement (unit tests, coverage ≥95%, no new ADR)

Tests for `git_check.py` (new pure module), `guard.py` (G3, G4, G7 checks), `presentation.py` (workspace survival), `dispatch.py` (confined setup). Key test areas:

**`git_check.py`:** Strip prefixes (G3: `X=1`, `env`, `command`, `timeout`, etc.), parse git (first/sub words, options), bases (cd tracking, unknown on unanchored move), where (D location: UNCONFINED/STEP_DIR/WORKSPACE/ELSEWHERE/UNKNOWN), denial reasons (G4/G6/G7 applied). Path resolution through `-C`, `--git-dir`, `--work-tree`, `-c name=value`. Outside words (URLs, scp, flags). Cd tracking across separators (`&&` carries base, `;` makes it unknown).

**Guard integration:** G3 sees through `env -C`/`-S`, finds git after wrappers. Git segment check returns denial reason or None. Environment vars in `GIT_ENV_LOCKED` denied (G7) in confined steps. Regression: unconfined `git status`/`cherry-pick -n` allowed, `git commit`/`git -C x status` denied with today's text.

**Presentation:** Workspace persists across bounce (lay_out creates dir and runs `git init -q` only when missing). Integration-tester's workspace contains git repos.

**Dispatch:** `GIT_CONFINED` table maps `e2e`/`acceptance` to workspace getter; `_confine_git` sets `scope.git_workspace` and `launch.env` with ceiling/cwd-keep. Developer steps unconfined (neither set).

**E2E** (new `tests/e2e/test_git_confinement.py`, isolated_git + set_git_identity): in a scratch "team" repo, workspace below `.team/run/presentation/<id>/workspace`, git inside workspace passes (init, cd, commit, checkout, rebase, clone), git at team repo fails (guard denial or ceiling).

All existing tests pass; no test deleted. Coverage ≥95%, ruff clean. See design `agile-team/docs/design/s65.md`.

## s59: Rebase at sprint start (unit tests, coverage 99.43%, no new ADR scope)

Unit tests cover pairing (match, all dropped, middle dropped, first dropped, merge commit), remap (count, REMAPPED fields yes/no, staleness safe), rebase (argv exact, current, rebased with pairing, conflict with abort, lost-path reset), sync_from (set once, reused, save before rebase order), dispatch (conflict hold, rebased event, current emit), push guard (team branch refused), and group_files (directory grouping). Fixture e93 (end-edge) is now `outcome: pass`, not `rebased` (R12: only START edge rebases).

**No tests deleted; removed `merge_in` tests replaced by rebase tests.** E2E tests (5 cases: all upstream, copies+new, real conflict, hash rewrite, hand rebase after conflict) belong to integration-tester's e2e step, not unit.

See design `agile-team/docs/design/s59.md` (test checklist), review round 3 (all defects fixed).

## s89: OS guard refined to allow stdlib source reads on 3.13 (test infrastructure, no new ADR)

Guard rules T1–T6 (design): T1 allows source reads by `traceback`/`linecache` inside a guarded frame. T2–T4 unchanged (exempt callers, code under test still fails, no other relaxation). T5 names the caller in violations. T6 patched calls unchanged. **Changes:** `tests/os_guard.py` (add `_modules()` generator, `_reading_source()`, `SOURCE_READERS` tuple, `CALLER_NOTE`); `tests/test_os_guard.py` (new helper `call_audited_through` for multi-frame stacks, 7 parametrized T1/T3/T4 test cases, AC2 test `test_formatting_a_real_traceback_passes_the_guard`). All existing tests unchanged and pass. 36 earlier 3.13 failures now pass. Coverage 99.31%, ruff clean. See design `agile-team/docs/design/s89.md`.

## s81: Test CI module, boundary changes, fake Prs (no new ADR)

New test file `tests/test_s81_boundary.py` (and helpers). Test areas:

**`ci.py` module (pure):**
- `bucket_of`: unknown → FAIL (safe side, never green).
- `verdict_of`: [] → NONE; all skipping → NONE; mixed (pass+pending) → PENDING; any red → RED.
- `overall`: all checks are computed per-PR then ranked PR-wide. GREEN only when all PRs green.
- `failing_lines`: strips gh prefix/timestamp, keeps pytest/go patterns, max 20, fallback last 10.
- `green_report`: raises ValueError for any non-green or empty list.

**`CiWatch` (fake clock, fake Prs via s29_helpers):**
- Green on first look (one watch, one read, no sleep).
- No checks at first, then on 3rd look (sleep twice, CI_POLL_S).
- Timeout: watch Hang's, read shows pending, result is PENDING.
- Red: `failed_log` called with link, lines recorded.

**`boundary_runner` integration (green, red with lines, timeout, no PR, hold until bug story):**
- After push, stage is `ci`; watch only non-draft READY PRs.
- Green → `done` event with `ci: green`, `results`, `prs`. Report has READY_PHRASE.
- Red → `held` with `hold: ci_failed`, `ci: red`, checks with job name and lines.
- Timeout → held `ci_pending` with reason naming pending checks.
- No checks / no non-draft PR → done with `ci: none`, no READY_PHRASE.
- Push permission `no` → local event, never reaches ci.
- Hold until bug story recorded (via settle_bug).

**`po_tools.record_ci_bug`:**
- Refused: no CI hold, unknown story, done story.
- Accepted: boundary closes, upstream.closed == sprint, report says "checks failed, story sN opened", ci_bug == sN.

**`state.py` loaders:**
- Legacy files without `ci` or `ci_bug` load with None and "".
- CiResult round-trips through asdict/reload.

**`handover.py` rows (ci_green, ci_failed, ci_pending):**
- Apply only to their report shapes (ci field exact).
- ci_green triggers only on report with `ci == "green"`, not on hold field.

**`config.py`:**
- `ci_timeout_s` defaults 1800, must be positive.

All tests on fake. Exit code 124 (timeout) handled. No test deleted or weakened. Coverage ≥99%, ruff clean.

See design `agile-team/docs/design/s81.md` (test checklist, AC7 e2e pending).

## Recent completions (s77–s78)

- **s77:** P3 closes seam; all 31 LEGACY files migrated. Ruff TID251 enforces import discipline.
- **s76:** P2 seam—13 process/signal/network functions faked, moved 4 test files to e2e.
- **s78:** Health accuracy—beat thread resilience, monotonic sleep detection, excuse logic for active work.

See ADR-0038 (s78), ADR-0036 (s71 seam architecture).

## Your scope (unchanged)

Unit tests only. Run named tests with `run_tests` tool. Never full suite or `--cov`. Design file is contract; read source only for gaps.
