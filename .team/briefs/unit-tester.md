# Unit Tester: Current context and conventions

**Last updated:** 2026-10-13 (s83 done)

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
