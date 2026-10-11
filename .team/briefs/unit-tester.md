# Unit Tester: Current context and conventions

**Last updated:** 2026-10-11 (s37 done)

## s37: Unattended wake time and reason sources

Fixed stale `next_wake` after resume/offline, and reset time from wrong source. Test coverage (design `agile-team/docs/design/s37.md`, section 7):

1. **Rules N1/N2:** `mark()` clears both wake fields. After limit+resume, status=running, next_wake=null. After offline wait, status=waiting, next_wake=null, wake_on=network.
2. **R1 source order:** Halt line beats status.json, status.json beats free text. Last halt-line match wins. Free text with no time → fallback wait. Default fallback value passes.
3. **R2 tightened reset:** `RESET_NOTE` needs readable time (H[:MM]am|pm + optional date/zone). "resets the count/soon/tomorrow" don't match. "resets 7pm" matches.
4. **R3 fallback vs reset:** Readable time → `Wake(..., RESET)`. No time → `Wake(now+fallback, FALLBACK)`. Test grace period included in reset.
5. **S1 wake_on field:** Status/list/wait report wake_on after next_wake. Wait event carries "on". Exact output format.
6. **L1 legacy load:** Missing wake_on key → None. Null → None. String → WakeOn enum.
7. **AC5 exact case:** Halt line "session limit, resets 9pm" + PO text "resets the count" → halt wins, parse 9pm. Oct 10 17:26 Chicago → Oct 10 21:03 Chicago.
8. **Coverage ≥95%** for unattended/runner; ruff clean.

See ADR-0020, `agile-team/docs/design/s37.md` test checklist.

## s30: Dispute gate now checks content, not commits

The dispute gate (s11 T6) now compares the disputed test file's **content hash** against the baseline stored when the dispute was raised, ignoring whitespace and comments. A real change passes; cosmetic (comment/whitespace only) or no change bounces with reason including file and baseline hash. New: test file paths are resolved to repo root at raise time; unresolvable paths are rejected with `UNTRACKED`. Test checklist (design section 7): fingerprint tests (comments, blanks, indents, assertions, strings), resolution (exact + suffix matching, git ls-files), raise (resolve, baseline capture, unresolvable bounce), gate (real/cosmetic/no change, confirmed, legacy, no git command), repeat escalates. See ADR-0019, design `agile-team/docs/design/s30.md`.

## s9: Interrupted steps—save and offer edits, not stash them

When a role step is cut short, the runner saves its edits in a commit + revert. On resume, the edits are offered to the next step on that story. Test coverage checklist (16 areas from design section 7):

1. **In-flight tracking (I1–I2):** During a role step, `in_flight = {role, story, brief}` (brief is the request's brief, no runner additions). After `settle`, it is `None`. A refused step never sets it.
2. **Save tree (I3, AC7):** Interrupted step with one in-scope and one out-of-scope file: both in commit, revert follows, tree clean, subject `chore(team): interrupted step by <label>`, no `QUARANTINE` event. `story.commit`, step, rounds unchanged.
3. **Capture (I4):** No step in flight + clean tree → `None`. In flight + clean tree → interruption with `sha=None` (pending list, not story). No step in flight + dirty tree → `product-owner` with no story.
4. **Limit halt (I5, AC2):** Note text = `message()` + suffix with sha from state; stderr unchanged. Second `halt_run` records nothing new.
5. **Halt at top level (I5, SIGTERM, crash):** In-flight role set. Tree clean after exit. Cause `sigterm` or `crash`.
6. **Error (I6):** Non-limit exception still propagates (s8 holds). Tree clean. Story has `interrupted` with cause `error`. `state.interrupted` empty.
7. **Salvage robustness (I8):** `git.commit` raises → halt completes, tree dirty, `GitError` in `crash.log`, nothing recorded.
8. **Resume after kill (I9, AC7, AC3):** State `running`, `in_flight` set, dead pid in `runner.pid` (and separately, no `runner.pid`), dirty tree. `start --resume` saves cause `killed`, preflight passes, stderr names sha.
9. **Still refused (I9, AC7):** Dirty tree with status `idle`; `running` + live pid; `running` + dead pid + plain `start --task`. Each exits 1, no commit.
10. **Offer in next brief (I10, AC8):** For each cause (error, limit, crash, sigterm, killed): next role on story gets exact offer with sha from `state.json`. After step settles, offer gone. Later interruption no sha keeps earlier offer.
11. **Resume prompt (I11, AC4):** Session resumed, no `--task`, pending interruption → first query is PO turn (not router pass) with `## Interrupted steps` section, role, story, brief, cherry-pick line. `state.interrupted` empty after. With `--task`, section after "New from the human". No session → after `first_prompt`. Empty list → unchanged.
12. **Liveness (I12, AC5):** `runner_pid` handles missing file, `"abc"`, `"0"`, `"-5"` → `None`. `pid_alive` maps `ProcessLookupError` → `False`, `PermissionError` → `True`. Monkeypatch `os.kill`.
13. **Shown status (I13, AC5, AC7):** State `running` + dead pid → `"status": "interrupted"`, `"running": false`. State `running` + live pid → `"running": true`. Others pass through. `state.json` stays `running` (never stored).
14. **Status keys (I14):** `status_report["in_flight"]` and `status_report["interrupted"]` right after `"running"`. Stories carry their `interrupted` field in `asdict`.
15. **Legacy state (I15):** Load `state.json` without `in_flight`, `interrupted`, story `interrupted` → defaults to `None` / `[]`. Cause string round-trips via `Cause(cause)`.
16. **Coverage ≥95% (currently 100%); ruff check and ruff format clean (AC7).**

Contract changes: Fixture has `in_flight` and `interrupted` fields; `status_report` keys are new. See design checklist for exact strings and cause values. ADR-0017.

## s40: Story priority ranking and explicit order

The router now ranks stories by an explicit priority order instead of creation order. Test coverage checklist:

1. **Ranking rule (P2):** `Priority.key()` = `(done, listed, not in_progress, natural(id))`. Done stories last. Explicit position beats in-progress. In-progress breaks ties among unlisted stories. Natural id sorts digit runs as numbers (s9 < s10).
2. **Order state (P1, P7):** `RunState.order` persists in state.json. Legacy load without it takes `[]`. After any change, order holds the full unfinished queue.
3. **PO tools (P5–P8, AC2):** `prioritise(ids, reason)` sets order and refuses unknown/done/empty. `move_story(story, position, reason)` moves to 1–queue_length, refuses unknown/done/bad position. `start_sprint` treats list as order.
4. **Router by order (AC3):** `_story_work` and `_repeat_work` pick first movable story in `priority().ranked()`, not creation order.
5. **Hold semantics (P4, AC6):** Held story skipped by router; position never changes. `continue_story` releases it to run from original position.
6. **Waits (W1–W2, AC6):** `waits.wait()` returns first matching `WAITS` row (blocked→needs human, needs_manager + repeated→manager, needs_manager→round cap, questions hold, any hold, open asking). Board shows hold pill and reason.
7. **Events (P9, AC5):** `priority` event on every change: set/move/sprint, full order, moves (1-based from→to), reason. Timeline shows label and meta.
8. **Snapshot (D1–D5, AC4):** `run.order` = queue. Stories in ranking order. Each story: `position` (int/null), `in_progress` (bool), `hold` (str/null), `wait` ({reason, on}/null).

Fixture gains `order` key, story `position`/`in_progress`/`hold`/`wait` fields, and at least one held story with open question matching it. Timeline has one `priority` event with move.

Contract changes: `story_status` returns `order` key, `story_status_data` iterates `ranked()`. `start_sprint` emits `priority` event after `sprint-start`. Tests bouncing a story twice need `repeat=2` config or change reasons. Coverage ≥95%; ruff clean. See design `agile-team/docs/design/s40.md` (test checklist).

## s11: Test dispute gate and test-dispute events

When a developer hands off from `implement` with a `dispute`, the story goes to `tests` with `story.dispute` set. Your gate is now `checks.dispute_settled(dispute)` while it's open:
- `done` + file changed (git diff exit 1) → pass to `implement` (dispute cleared)
- `done` + file unchanged → bounce to `tests` (reason: "the disputed test file {file} has not changed…", round +1)
- `changes_requested` + `next_role: architect` → move to `design`, set `dispute.stage = confirmed`, round +1

Your brief line (T9): `Test dispute (raised): {test} contradicts {rule}: {reason}` while open, `(confirmed)` after architect is scheduled. Test coverage: dispute settled gate (exit codes 1/0/128), confirmed status, `changes_requested` → architect, unchanged file bounce reason exact, tests_red not called while dispute open. See ADR-0018, design `agile-team/docs/design/s11.md`.

## s29: Boundary runner tests (sync, rebuild, check, push, stacked PRs)

Sprint boundaries are runner steps that execute at start and end. Key test areas from the design checklist:

1. **Skip conditions (U4):** No remote, empty remote, fetch fail, no target → one `skipped` event, no other stage.
2. **Merge in (U5):** Upstream commit merges (HEAD moves), no commit on no new upstream, recompute all shas as ancestors, merge conflict → hold `sync_conflict`, tree unchanged, exact hand-over text.
3. **Full checks (U7):** Order: lint, static, test, coverage, then e2e per delivery. Every check runs; none skipped. Coverage baseline applies. Reason format exact.
4. **Team fix (U9–U11):** Fail on team branch → `failure` set, next work `devops` with brief quoting output. After done, `rounds==1`, check reruns, pass moves on.
5. **Stack and rebuild (U6, U8, U15–U16):** Entries added at end, ranges drop merged entries. Cherry-pick loop handles real conflicts and empty picks. Rerere replays recorded resolutions. Bottom and top checked once each (skipped if `checked==head`).
6. **Push (U17, U19):** Permission `unasked` → hold `push_permission`, branches listed, hand-over exact. Permission `no` → `local` report, done. Permission `yes` → branches pushed with lease, no team branch or main push.
7. **PRs (U18):** Bottom created `ready` with base main, others `draft` with base = previous branch. Body has `STACKED_LINE` (not on bottom). Rerun edits only what differs. After bottom merges, next PR's base → main, mode → ready. Closed PR left alone with `CLOSED_NOTE`.
8. **Finish (U22):** End boundary finishes with `done`, `closed==sprint`, report set. Sprint-end note includes `Review: <report>`. Start boundary without restack finishes after `check`.
9. **Errors (U3):** Exception in stage → hold `error`, traceback in `crash.log`, `boundary_error` hand-over, `continue_boundary` reruns.
10. **Permission tool (U20):** `set_push_permission("yes"|"no")` emits `boundary` event, clears hold, refused on other values.
11. **Continue tool (U21):** `continue_boundary(note)` refuses on no boundary or unheld; clears hold, failure, streak/rounds on escalated/reviewed.
12. **Dashboard (U25):** Snapshot has `upstream` shape (stack, boundary), fixture keys match builder, Review stack card renders from fixture, timeline has `boundary` rows.

Contract changes: `start_sprint` opens a boundary (one step, event); sprint-end note lines may include `Review:`. See design `agile-team/docs/design/s29.md` (test checklist section) and ADR-0015.

## s24: Reworked stories and test claims

When a story returns to `tests` with code from an earlier pass (ruling, review, or dispute), the brief says `Code from an earlier pass is in`. The suite may already be green. If so and you've updated tests, hand off `done` with `"tests": "changed"`. If existing tests already cover the new design, hand off `done` with `"tests": "confirmed"`. Without a claim, a green suite bounces once with `tests pass on code from an earlier pass; write a failing test, or hand off "tests": "changed" or "tests": "confirmed"`. On a first pass (no brief line), the old rule holds: green bounces with `tests pass before implementation; write a failing test`.

See ADR-0012; design `agile-team/docs/design/s24.md` (rules G1–G9, unit-tester's role file).

## Context reduction: work lean (s23)

Your session context is reduced by disabling Claude.ai connectors and following guided reads:

- **No connectors:** You cannot use Claude.ai integrations during your step (other roles don't either, except PO and Proxy). Focus on code.
- **Start from design:** Each story has a focused `docs/design/<id>.md` with rules, exact signatures, and a test checklist. Read only helpers you reuse; read source only for what the design leaves open.
- **Read little:** Find with Grep before reading. Use `Read` with `offset` and `limit` to target lines. Never `cat` long files; avoid double-reads. Run tests quietly and fail-fast.
- **Write lean:** Write test files in one go with `Write`, fix with `Edit`. See the design's test checklist for what to cover.

Target context per turn: under 60k tokens (s19 was 113.9k). See ADR-0011.

## s25: Cost delta tracking – test notes

s25 fixed PO cost overcounting by ledgering only the delta from the previous running total per session. Key test cases (design checklist section 8):

1. `SessionCost.own_cost()`: 7 cases (fresh, same-session delta, other session, equal, drop, default store, `None` mismatch).
2. `Ledger.last_cost()`: role lookups, ignoring other roles' entries, empty ledger → 0.0.
3. `RunState` round-trip: `po_cost` persists as `SessionCost`; missing key loads `None` (legacy files).
4. **Resumed session deltas:** three PO turns reporting running totals 1.0, 1.5, 2.25 ledger as 1.0, 0.5, 0.75.
5. **Across processes:** `po_cost` from saved state is used; new process with same session gets the delta.
6. **Handoff renewal:** `po_cost` from old session, fresh session ID → entry is full amount.
7. **Legacy seed (C6):** `po_cost = None`, `po_session = "old"`, ledger has PO entries → delta against last PO cost.
8. **Drop (counter reset):** `po_cost` higher than reported → entry is just reported.
9. **No result:** `ResultMessage` is None → `po_cost` unchanged, ledger 0.0.
10. **Free provider:** `po_cost.reported` stores raw total; ledger entry is 0.0.
11. **Checkpoint:** real spend (not running total) triggers checkpoint.
12. **Role steps:** `resume=None` always; own cost equals reported cost.

A contract change: tests that assert a resumed PO entry's cost must now use design rule C1. `conftest.FakeQuery` returns the same cost/session per call; for deltas, use a fake that returns a list `[1.0, 1.5, 2.25]`. See design section 7 "Test checklist".

## Process constraint: developer cannot edit tests

The developer role cannot write to `tests/unit/` or `tests/conftest.py`. Before finishing, verify every test matches the design. If a test passes but doesn't match what the developer built, update the test (not the feature).

## s19: Routing in code – test notes

Code review passed with one blocking defect (D1: done stories with holds were not scribed) found and fixed in round 2. Final coverage 99% (router and handover at 100%), all 964 tests pass.

Design's test checklist (section 7 of `agile-team/docs/design/s19.md`) calls for 12 areas:
1. **Automatic advance** (AC1): one `run_po` runs architect through pipeline to done, scribe, then hands `SPRINT_END` to PO; assert step order and PO query count (2).
2. **Standard brief** (AC1, AC3): each BRIEF_PATHS case (design file/architecture fallback, review present/absent), previous with/without summary, bounce/return verdicts, pass suppresses "Sent back", note line, scribe and Manager headings.
3. **Hand-over triggers** (AC2): parametrized test per HANDOVERS row; multi-match gives all in order; clean `done` gives none. Router: `HUMAN_MESSAGE`, `SPRINT_END`, `STALLED` cases, wait (R8), quiet end (R9), round cap.
4. **Holds** (R6): report → hold, router skips held story, `continue_story` clears hold and note, PO step clears hold, refused PO step leaves state untouched.
5. **Bounce briefs** (AC3): `changes_requested` with `next_role: developer-gui` → next step runs that role with "Sent back" line. Red gate → same developer reruns with test tail.
6. **Specialisation choice** (AC4): parametrized over ROLE_HINTS; `po_developer` beats bounce, bounce beats architect pick, retry keeps `previous.role`. Architect sets `story.developer`, other roles do not. Bad `developer` field is a bad handoff. Three `set_developer` refusals.
7. **Automatic Scribe and Manager** (AC5): done story queues `scribe_due`, router runs scribe next with scribe heading. Scribe entry cleared on bad handoff (which hands over). Done story blocked by open question is skipped until answered. Held done story is scribed (D1 fix: `_scribable` allows unheld or DONE). `manager_due` makes router run manager story-less before any story step.
8. **Driver ends** (R10): stop file, limit halt in router step (no PO turn, exit 75), `notify_user` sprint-end (each end the run). Status ends `idle` only when still `running`.
9. **Errors** (R18): step raises RuntimeError → `error` report, crash logged, story held. Limit halts (not Exception), so not caught.
10. **State** (R16, legacy): old state.json loads with new fields defaulting to None/[]. `previous` round-trips. `delivered=None` → every existing answer id (old answers never handed over).
11. **Event** (R17): each hand-over turn preceded by one `handover` event with correct trigger/story/step counts.
12. **Coverage ≥95%** (target 100%), `ruff check` and `ruff format` clean (AC7).

Pitfall for round-trip tests (previous, delivered, scribe_due): nested dataclasses and lists; use `NESTED` dict to deserialize.

## s13: Team presents product in ready-made environment – test notes

Code review passed with no defects. Unit coverage for s13 is at 100%; overall stays at or above 95%.

Key test constructs and expectations:

| Aspect | Test cases | Notes |
|--------|-----------|-------|
| **E2: lay_out** | Wipes old dir, creates workspace with .git for kinds that need it, manual has no workspace, refuses `../x` before touching anything | Pitfall: pytest's `tmp_path` may be inside a git repo; use `GIT_CEILING_DIRECTORIES` |
| **E5: missing** | No dir, blank guide, guide but no workspace, workspace with only .git, complete, manual with guide only, no delivery (guide only) | Exact reason strings match design; guide checked before workspace |
| **E4: e2e done gate** | Bounce to e2e on missing, pass to acceptance on complete, `changes_requested` still bounces to named role, no acceptance step → pass without check | Rounds increment on bounce; gate checks only when acceptance step exists |
| **E6: Proxy unpresented** | Story returns to e2e (no round, no status change) on missing, gate event emitted with `verdict: "return"`, no prepare call, story stays at acceptance if complete | Refusals (backlog, done, blocked) come first; return applies only at acceptance |
| **E7: copy_into** | `shutil.copytree(symlinks=True)`, symlink stays a symlink, copy asserted inside fake runner before prepare | Symlink does not escape s7 guards (Read resolves to real path) |
| **E8: prompt_section** | With presentation: heading + path line + rule line + guide text; without: empty string | No unguarded read on stale dir (follow-up: handle FileNotFoundError gracefully) |
| **E9: Proxy read scope** | Can Read `.team/acceptance/s8.md`, denied `agile-team/runner/agile_team/cli.py`, read globs + allowed reads have new entries, `web`, `harness`, `manual` kinds have Read tool | Scope intersection: role has Read, kind has Read → tool available |
| **E11: init outside git** | `main(["--repo", str(tmp_path), "init", …])` outside git returns 1, stderr is exact `agile-team init: not a git repository: <tmp_path>; run git init first` | Use `GIT_CEILING_DIRECTORIES`; also test missing path |
| **Integration-tester write scope** | Can write `.team/run/presentation/s4/PRESENTATION.md`, denied other roles | Role scope Check |

## s8: Clean halt – test notes

Code review round 2 accepted the fixes and deferred three e2e regression tests to the Integration Tester (see their brief). Unit coverage for s8 is at 100% (halt.py, po_tools.py, dispatch.py, cli.py); overall stays above 95%.

Key test constructs:
- `conftest.RaisingQuery(exc, before=N)`: yields N messages, then raises exc (for mid-stream errors)
- Real `ResultError` must include `exit_code=1` to match SDK behavior; ` (exit code: 1)` is appended to str(exc)
- Fake limit error: `ResultError("Claude Code returned an error result: You've hit your session limit · resets 2:20pm (America/Edmonton)", data={…}, exit_code=1)`
- Trace all halt paths: PO level (cli._run), role level (Runtime._step_failed), both in one turn, resume after halt

Check that tests match the HALTS table values exactly: statuses `blocked`, `failed`, `stopped`; exit codes 75, 70, 143; note kinds and advice text.

## s5: Dashboard UI test notes

**Known gaps (by design, not defects):**
- No executable test for live dot animation, halo movement, or reconnect. These are DOM operations verified by hand in headless Chrome and in review. Add them in a follow-up story.
- No test for sparse event data handling (e.g., `sprint-start` with missing fields). The runner always writes complete data; test fixtures are the only place this happens. Consider a parametrized test for defensive rendering with `normalize()`.
- Escaping rule (ADR-0005): all snapshot strings in HTML must go through `esc()`. Tests check string presence, not injection prevention. Consider adding a test that verifies no unescaped interpolations exist in the shipping `index.html`.

Review round 1 found two defects (D1: bad Mermaid selector, D2: unescaped strings) that were fixed and verified by round 3. Round 4 fixed a crash on empty sprint-start data, verified by the customer. Tests are green at 100% coverage.

## s26: Service lifecycle and liveness testing

s26 added service startup, probe, and liveness testing. Key test areas:

1. **Absolute paths (L1):** Relative `--repo` resolves to absolute; `expand` with relative repo gives absolute `{repo}` and `{sandbox}`.
2. **Placeholders (L2):** `{host}` and `{port}` from `http://127.0.0.1:8799/`, from `http://h/` (default 80), no url.
3. **Liveness data (L3):** `PRESENTATIONS["web"].check is Check.SERVICE`; others are `FILES`; SERVICE ⇔ BACKGROUND `Start` kind.
4. **Start and probe (L4–L5):** Fake `popen` with live process, probe true on 3rd call → prepare returns, sleep twice, pid/log files exist. Probe fail: process exited → `NotUp` "exited with code X", never answers → `NotUp` "did not answer…within Ys". **Real hung process test:** `exec sleep 60`, `attempts=2` → "did not answer…within 0.5s", never "exited with code -15" (reason before stop).
5. **Stale cleanup (L7):** Start real sleep, write pid, `stop_stale` → gone, file gone. Dead pid → silent. **SIGKILL escalation test:** trap TERM, `STOP_WAIT_S=0.2`, assert `-SIGKILL`.
6. **Port conflict (L8):** `listening` true → `PortBusy` exact text, `popen` never called. `port_in_use` true for bound socket.
7. **Teardown (L9):** `Prepared.stop` idempotent, deletes pid file. `Runtime.plan` exception after prepare → `stop` called.
8. **Gate trial (L10):** Missing files → bounce (liveness never called). Files ok + `liveness` pass → pass. `NotUp` → bounce e2e, round +1. `PortBusy` → hold, rounds unchanged. `Check.FILES` never calls prepare.
9. **Return (L11):** Fake `prepare_fn` raising `NotUp` → returned, no round, no query. No e2e → refused.
10. **Gate hold (L12):** Report with `hold` verdict → `GATE_HOLD` line with reason. Blocked → `STOPPED`.
11. **Make pipeline:** Wires `Trial(config).liveness`.
12. **HTTP probe (L5):** Real `ThreadingHTTPServer`: 200 JSON → true, 204/201 → false, 500 → false, nothing listening → false.

Coverage 100%, ruff clean. See design `agile-team/docs/design/s26.md` test checklist.

## s27: Repeated setback escalation and backstop

s27 detects when a story bounces for the same reason and escalates to the Manager instead of looping. Key test areas:

1. **Normalisation (L2):** `test_loops.py` asserts each NORMALISE pattern exactly; same reason with different numbers/ports/paths/ids/times/shas gives one key; stored keys recompute on load.
2. **Streak (L3):** `extend` appends on same key, restarts on different; `repeats` is 0 for empty or different last key, else `len(streak)`.
3. **Repeat rule (L4–L5):** With `repeat=2`, first setback bounces (move, +1 round); second same-key setback → `ESCALATE`, step/rounds unchanged, `NEEDS_MANAGER`. With `repeat=3`, escalation on third. Different reason resets. A pass in between does **not** reset. Dispute never counts.
4. **All setback kinds (L1):** `changes_requested` bounce, command-gate bounce, `blocked` hold, `NotUp` return, malformed handoff — each lands in `streak` with gate event id. On repeat, each escalates.
5. **Escalation event (L5):** `escalation` event (not `gate`) carries `step`, `verdict: "escalate"`, `reason`, `now_at` (=step), `story_status: "needs_manager"`, `rounds` (unchanged), `key`, `author`, `count`, `history` (earlier event ids). Repeat escalation has `rule: "repeat"`.
6. **Zero rounds (L6):** Before/after escalation equal. Manager adds none. After applied fault: `rounds==0`, `disputes==0`, `streak==[]`, `repeated is None`.
7. **Manager hand-over (L7):** Escalated story queues Manager with `REPEAT_HEADING` (count 2) in brief, `repeated_setback` in context. Router picks it before Scribe. Held escalated story waits for `continue_story`. Open question blocks it too.
8. **Fault (L8):** `fault: "integration-tester"` → step `e2e`, `active`, `fault` event kind `pipeline`, applied true. `fault: "devops"` → step kept, `off_pipeline_fault` hand-over. `fault: "runner"` → `blocked`, event kind `runner`, outbox note, `runner_fault` hand-over.
9. **Fault refusal (L9):** Missing → `FAULT_MISSING`. Unknown name → `FAULT_UNKNOWN`. Story unchanged, ruling not applied, `fault_not_applied` hand-over.
10. **Fault + ruling (L10):** `fault: "developer-cli"` + `ruling: "revise_design"` → step `design`, both in report. On non-repeated story, `fault` ignored.
11. **Backstop (B1–B4):** `extend_run` appends on same pair (different reasons OK), restarts on new pair. `bounces` is 0 for empty/different pair/hold/in-place, else `len(run)`. With `backstop=4`, fourth bounce between same steps escalates with `rule: BACKSTOP`, regardless of reason.
12. **Pass reset (B3):** `after_pass(run, upper)` returns `[]` when upper step just passed; `after_pass(run, lower/other)` returns `run` unchanged. Both fault and ruling clear `run` and `escalated_by`.
13. **Backstop vs. repeat (B5):** Both fire; repeat wins. Neither resets the other.
14. **Config/state (L16):** `gates.repeat ≥ 2` (default 2), `gates.backstop ≥ 2` (default 4). `streak`, `repeated`, `run`, `escalated_by` round-trip in `state.json`; older files load with `[]`/`None`.
15. **Dashboard (L17, B9):** Snapshot stories have `repeated`. Board shows `needs_manager · repeat`, reason line. Timeline: `escalation` event (`repeat` or `backstop`), `fault` event. Replay handles both.

Contract changes: `Pipeline(...)` gains `repeat` and `backstop` (both with defaults). Tests bouncing the same reason 2+ or same pair 4+ times must adjust these or change the reason to keep intent.

Coverage ≥95%; ruff clean. See design `agile-team/docs/design/s27.md` test checklist (18 areas).

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. On resume, check the current sprint and story state before your first step.
