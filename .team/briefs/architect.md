# Architect: Current context and conventions

**Last updated:** 2026-10-13 (s104 done; s96 done; s86 done; s85 done; s84 docs done)

## s104 complete: Flow chart dimming and unused roles (design rules FL1–FL9, ADR-0047, docs due with ship)

Pure snapshot building, no new event kind or state. `roles[]` section gains `used: bool` field. Rules FL1–FL9 enforced: no compositing styles (opacity/filter/transform/mix-blend-mode) on classDef (FL1–FL2), nodes dimmed by colour only, every role has `used` (FL7), chart draws only used + PO (FL8), natural-size SVG with scroll (FL5–FL6), "idle" text for no-data roles (FL4), first step-start shows box (FL9). No dependency added; snapshot/dashboard/index.html changes only. Code review done (ship). E2E test pending (integration-tester P1).

**Data contract:** Each role gains `"used": bool` (routed to by STEP_ROLES or has step-start event). **Module pattern:** `_used_roles` = `_routed_roles(files)` ∪ `_stepped_roles(events)`. `_routed_roles` maps pipeline steps to roles via STEP_ROLES with generic developer expansion to assigned developers (or itself if none assigned). `_stepped_roles` reads events for step-start role keys. Functions ≤8 LOC.

**Your work:** Update `reference/protocol.md` (roles section: `used` field definition, FL7 rule), `reference/protocol.md` Flow paragraph (used roles only, PO always, colour dimming, "idle" text, natural size, scroll), `docs/customer/dashboard.md` (Flow section, same points in customer words), `docs/architecture.md` (one row: snapshot.py _used_roles, _routed_roles, _stepped_roles).

See design `agile-team/docs/design/s104.md` (FL1–FL9, per-module changes), ADR-0047.

## s96: Time per role and role-by-time chart data (design rules ST1–ST15, docs due with ship)

Pure snapshot building, no new event kind or state. `steps` section (new list after `ledger`) records agent step wall times paired from events.jsonl: role, story, model, sprint, at, ended_at, seconds (null for killed steps), status. Rules ST1–ST8 pair and count steps; ST9 formats spans (0 min, <1 min, N min, H h M min); ST10–ST11 scope filtering and running time on Flow boxes; ST12–ST14 Time unit in chart. No dependency added; snapshot/dashboard/index.html changes only. Code review done (ship). E2E test pending (integration-tester P1). **Your work:** Update `reference/protocol.md` (steps section, Flow paragraph, Time measure entry), `docs/customer/dashboard.md` (Flow and Tokens entries), `docs/architecture.md` (index line, `step_times.py` row).

See design `agile-team/docs/design/s96.md` (ST1–ST15, test checklist), no ADR.

## s86 complete: Story dependencies as data (design rules DP1–DP15, ADR-0046, docs complete)

Dependencies recorded as `depends_on: [s1, s2]` lists in story file frontmatter. Loaded and validated at three points (cmd_start, start_sprint, open_story) as a graph (no cycles, self-references, unknown ids). Router skips stories waiting on undone dependencies (skip reason: `waiting on sN`). Backlog tab shows dependencies with ` (done)` markers and warns when human reorders a story above one it depends on (⚠ pill, timeline warning with tone). Migration complete: all prose "Depends on sN" → frontmatter, drop-done rule applied, no prose remains outside HISTORY.

**Architectural pattern:** Pure module `dependencies.py` (~350 LOC), file I/O for reads, no writes from runner. Graph validation (DP4, DP7) is deterministic (DFS from natural order). Snapshot adds three keys per story (`depends_on`, `waiting_on`, `dependency_warnings`). No new dependency (PyYAML already present). Data-driven: validation text is exact for each refusal, cycle walk is deterministic.

**Data contract:** Snapshot each story gains `depends_on: [...]` (state list), `waiting_on: [...]` (list order, undone or missing), `dependency_warnings: ["msg1", "msg2"]` ([] if done). Event `priority` gains `warnings` field (new inversions only, or [] if none). Stalled reason is `waiting on {ids}` (list order).

**Docs written:** `agile-team/reference/protocol.md` (Story dependencies section, load points, checks a–d, open_story arg, routing, warnings, snapshot keys, Backlog row), `agile-team/docs/customer/dashboard.md` (Backlog row: depends/waiting with (done) marker, ⚠ pills), `agile-team/docs/customer/backlog-and-sprints.md` (updated), `agile-team/SKILL.md` step 6 (open_story and start_sprint descriptions), README row (updated). Code review done (D1 fixed). P1 work (DP16 migration pin, page harness node-harness tests) for integration-tester.

See ADR-0046, design `agile-team/docs/design/s86.md` (DP1–DP16, known limits).

## s85 complete: Liaison opinions on backlog stories (design rules O1–O20, ADR-0045, docs done)

Opinions are a view over three append-only JSONL files: `opinions.jsonl` (CLI writes), `reviews.jsonl` (liaision summary), `opinion-acts.jsonl` (server writes). Latest opinion per story wins (line order). Acts route via two paths: moves to reorder queue (s83), others to PO as thread posts (s84). Dashboard shows badges, filters suggestions, renders details, review bar with ask button (fires `liaison_message` watch trigger), dismiss/apply buttons with token gate. Snapshot carries items with route/act, asked_at, review; events merge opinions/acts with thread and reorder events.

**Architectural pattern:** Append-only JSONL files like s84 threads (one writer per file). Pure module `opinions.py`, view-time merging at snapshot build. No new dependency. Rules O1–O20 in code, no branching (Kind/Act/Route enums, Board/Opinions classes, table-driven dispatch).

**Data contract:** Snapshot sections: opinions (items, asked_at, review); events gain opinion/opinion-act kinds; watched_files add three JSONL paths. CLI gains opinion/reviewed commands; server gains /api/review and /api/opinion POST routes; thread posts to PO tagged with opinion id.

Code review done (m4 docstring minor, carries to next touch). P1 work (node-harness, e2e) for integration-tester.

See ADR-0045, design `agile-team/docs/design/s85.md` (O1–O20).

## s84: Story threads—human discusses with PO and liaison (design rules H1–H21, ADR-0044) [DOCS PENDING]

Story shipped in code. Unit tests pass (coverage ≥99.44%, ruff clean). Code review done (all ACs pass). P1 work: node-harness and e2e tests (integration-tester). **Your pending work:** Write the docs listed below.

**Architectural decisions (ADR-0044 D1–D30):**

**D1–D2: Thread as a view, not a store.** Four append-only files, each with one writer: relay.tell (posts to PO), outbox/reply (PO replies), liaison/inbox.jsonl (posts to liaison), liaison/replies.jsonl (liaison replies). `Threads.all()` reads and merges by time at view-time, no aggregation. Entry structure: (id, story, author, to, text, at).

**D3–D5: Validation.** Party enum (HUMAN, PO, LIAISON). Text: non-empty after strip, ≤4000 chars. Story: in state.stories (done allowed). Refusal functions called by all writers (server, PO tool, CLI).

**D6–D7: POST shape.** Dashboard form: JSON with story (regex), to ("product-owner"|"liaison"), text. Dashboard checks: localhost + token (403), Content-Length 1–32768 (400), parse (400), post (400), reply 202.

**D8–D10: To PO.** Posts via `Relay.tell(tagged(story, text))` with head `<!-- thread story={story} at={at} -->`. Router's `_told_lines` dispatches to `threads.told_line` (thread head → THREAD_TOLD_LINE, else TOLD_LINE). Stories in _deliver = answers + tagged stories.

**D11–D12: PO replies.** New tool `reply_story(story, text)`. Refusals H3 (story), H4 (text), posts Note(REPLY, text, [story]). `notify_user(kind==REPLY)` refused with USE_REPLY before posting.

**D13–D14: To liaison.** Posts append to `liaison/inbox.jsonl`. Watch gains `liaison_message` trigger: `Seen.posts`, `Look.posts`, `new_posts(seen)` method, posts in `line()`, `_next` keeps seen.posts. Old memory loads with posts=0. First watch records current posts as seen.

**D15: Liaison replies.** CLI `reply <story> <source>` (file or -). Text/story checks via functions. Appends to `liaison/replies.jsonl`. Works while run stopped.

**D16: All entries merged by time.** `to_po() + po_replies() + liaison_posts() + liaison_replies()` sorted by (at, id). JSONL read leniently (blank/torn/non-object lines skipped).

**D17–D21: Dashboard (H14–H21).** Events: `thread-<id>` kind, role from EVENT_ROLES (PO only). Snapshot: new `thread` array (5 dicts per story), watched_files adds inbox/replies/told files. Page: `threadHtml(story, view)` on expanded row, form with textarea/select/button (TOKEN gated). `postThread` posts with header and token. `keepFocus` saves/restores focus. Timeline: `TIMELINE.thread` with author/to/body.

**D22–D30: Implementation modules.**
- New `threads.py` pure module: Party enum, Entry/Post/Tag dataclass, validation/tagging/reading functions, Threads class.
- `relay.py`: REPLY added to KINDS, tell draft `.draft-{token()}`.
- `router.py`: _told_lines uses threads.told_line, _deliver deduplicates stories.
- `po_tools.py`: reply_story tool, notify_user refuses REPLY.
- `watch.py`: Seen/Look.posts, liaison_message trigger.
- `cli.py`: cmd_reply command.
- `server.py`: BODY_LIMITS table (per-route), _thread handler (H4 order).
- `snapshot.py`: _thread section, _thread_event, _events excludes reply from message.
- `index.html`: thread state (drafts, to, sending, note), functions, listeners, timeline.

**Data contract extends:** Snapshot adds `thread` array, `thread` events (no `message` for reply lines), watched_files. Relay adds REPLY kind. Watch adds `liaison_message` trigger with `posts`. Outbox reply messages no longer dual-logged.

**File formats:** Relay head `<!-- thread story=<id> at=<time> -->\n\n`. Inbox/replies JSONL: `{story, text, at}` per line, append-only, torn reads OK.

**Boundaries:** Server ↔ Files (POST → relay/inbox), Router ↔ Files (told files, inbox for trigger), PO Tool ↔ Outbox (reply messages), CLI ↔ Files (append replies). No dependencies added; watch and relay already exist.

**Data-driven:** Party enum, RECIPIENTS frozenset, EVENT_ROLES dict. Refusals are functions (not branching). SENDERS dict dispatches post routes. `_lines` helper reads both JSONLs leniently.

**Consequences:**
- Human can discuss stories directly on dashboard without explicit request cycle.
- Threads are auditable (all files append-only, time-stamped, tagged with story).
- View-based (no new store) keeps writers independent.
- Liaison wakes fast (2s via new trigger, not heartbeat wait).
- PO and liaison flows differ by design (async vs interactive).

**Docs (your work, due with this story to ship to customer):**
1. **`agile-team/SKILL.md` step 5–6:** Dashboard writes now include thread posts (/api/thread). Watch triggers gain `liaison_message` with `posts` array. Liaison answers with `reply <story> -`.
2. **`agile-team/reference/protocol.md`:** Watch trigger table (liaison_message), `reply` CLI command, `reply_story` PO tool, `reply` outbox kind, thread files (relay head, inbox/replies JSONL), POST /api/thread, snapshot thread and thread events.
3. **`agile-team/docs/customer/dashboard.md`:** New section "Discuss a story" (form, posting, thread view, recipient choice, read-only without token).
4. **README row (if dashboard writes are listed):** Add `/api/thread` to dashboard's POST routes.

No ADR needed (docs move with behaviour as per charter). See ADR-0044, design `agile-team/docs/design/s84.md` (H1–H21).

## s83: Backlog reorder on dashboard; human order binding (design rules B1–B20, ADR-0043)

Human can read stories and reorder the backlog on the dashboard. Requests queue as files, apply between steps through the PO, and record the human's chosen order. The PO cannot change that order without a stated reason.

**Architectural decisions (ADR-0043 D1–D18):**

**D1–D4: Request flow.** Dashboard stateless; POST → file queue in `.team/run/reorders/`. Between steps (router._tick after checkout), `desk.apply()` processes pending requests, updates state, emits events. No apply = no hand-over; human sees result in next snapshot (SSE). One pending request at a time (handles disabled while pending).

**D5–D7: Human order record and rule.** When applied, backlog order → `state.human_order`. PO `prioritise`/`move_story` that changes the guarded projection (stories the human moved) requires a non-blank `reason`, recorded in event. Empty `human_order` guards nothing; `start_sprint` never triggers the rule.

**D8–D10: Write security.** Localhost (127.0.0.1, ::1) + token required. Random token on start (printed in URL), fixed via config for presentations. Token never logged; appears only in URL.

**D11–D12: Event audit.** Priority events gain `source` field ("product-owner" or "human (dashboard)"). Human moves have `role=None`.

**D13–D14: Request refusals.** Five checks in order (stale, unknown/done, sprint-story, bad-place, move-refusal). First refusal recorded; nothing else changes.

**D15–D16: File serving.** By story id via `/api/file?kind=K&id=I`. Kind from whitelist (story, design, review, acceptance), id matches pattern, story exists, file exists and is regular. Path built only from table and validated id.

**D17–D18: Implementation scope.** New `backlog.py` (pure, groups/version/refusals), `reorders.py` (queue/apply), `story_files.py` (file table/read). Updated `priority.py` (Source enum), `po_tools.py` (human check), `state.py` (three fields), `dispatch.py` (Runtime.reorder), `router.py` (Desk instance), `config.py` (DashboardSettings), `server.py` (POST/GET routes), `snapshot.py` (order_version, backlog, reorders, new fields), `index.html` (Backlog tab).

**Data-driven design (rules B1–B20):**
- `STORY_ID` regex: the id pattern.
- `View.of(state)`: one definition for groups.
- `order_version()`: pure hash function.
- `story_files.FOLDERS`: whitelist table (kind → path getter).
- `backlog.label()`: label logic (cancelled/held/"").
- Refusal checks: `stale_refusal()`, `sprint_refusal()`, `place_refusal()`, then `priority` move-checks.
- Human-order guarded projection: checked by `human_refusal(HumanCheck, reason)`.
- Event source: `Source` enum, `SOURCE_ROLES` map.
- Request status: "pending"/"applied"/<reason text> recorded in `state.reorders`.

**Module boundaries (no branching on type):**
- `backlog.py` pure → `dispatch.py` and `po_tools.py` call functions; result handed to data.
- `reorders.py` handles I/O → router and dashboard call methods.
- `story_files.py` serves files → server routes via callables.
- Snapshot builds once per SSE tick; no caching.

**Consequences:**
- **Interactive backlog steering:** Human can read and reorder on the dashboard without asking for PO requests.
- **Auditable decisions:** Events show source. `human_order` records intent. PO's reason logs overrides.
- **Data contract extends:** Snapshot adds order_version, backlog, label, disputes, developer, commits, files per story, reorders list, source on events.
- **Three new state fields:** `human_order`, `reorders`, `reorders_told` (empty defaults for old state.json).
- **Request pattern:** File queueing (like `reorders/rN.json`) works for async decisions outside the PO's tools.

**New boundaries & seams:**
- Dashboard ↔ Server: POST /api/reorder, GET /api/file (no state.json writes from server).
- Request file ↔ Router: `.team/run/reorders/` watched by router._tick.
- Human order ↔ PO tools: guarded projection check before applying `prioritise`/`move_story`.
- Event source ↔ audit: Source enum on Reorder, recorded in events and snapshot.

See ADR-0043, design `agile-team/docs/design/s83.md` (B1–B20).

## s51: Tier-based priority ranking, pull semantics (design rules G1–G17, ADR-0016 amended)

Refined s40's explicit order with **story tiers**: in-progress (started, not held) > held (started) > not-started. Ranking rule: `(done, RANK[tier], listed, natural(id))` replaces "explicit order beats in-progress". **Pull logic:** To move a not-started story ahead of started ones, the PO calls `prioritise` or `move_story` with a reason; without reason the tool is refused. `state.pulled` records pulled ids. **Plan vs queue distinction:** Changes build on plan (no groups) never queue (with groups), so reordering while a story is held does not move its held place in order.

**Data-driven:** `Tier` enum, `RANK` dict. **Key functions:** `started()`, `held()`, `tier()`, `plan()`, `pulls()`, `set_pull()`, `pull_refusal()`, `with_first()`, `with_move()`, `repulled()`, `first_refusal()`. **Modules changed:** `priority.py` (new), `state.py` (+pulled field), `po_tools.py` (pull checks), `dispatch.py` (priority method), `dashboard/snapshot.py` (tier field). **Coverage 99.41%, ruff clean.** See design rules G1–G17, ADR-0016 amendment.

## s65: Git confinement—S61 incident solved, no ADR (extends s41/s43/s69 guard pattern)

During s61, integration-tester's git demo had no `.git`, so git climbed to the team repo and moved the human's `main`. Two-layer solution in code:

**Layer 1: Environment (G2).** Confined steps (e2e, acceptance) get `GIT_CEILING_DIRECTORIES=<run_dir>` and `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1` in launch env. Git can't climb above `.team/run`, so a demo with no `.git` fails "not a git repository", not reaching the team repo.

**Layer 2: Guard (G3–G7).** New pure module `git_check.py` classifies git segments. The PreToolUse hook now sees through command prefixes (env, command, timeout, etc.) via `WRAPPERS` table (G3). For each git segment, tracks where it works via cd tracking and places (G5), looks up `GIT_RULES` by `Where` (G6), and denies writes/reads to elsewhere. In confined steps, additionally denies mentions of locked env vars (GIT_CEILING_DIRECTORIES, GIT_DIR, GIT_WORK_TREE, GIT_DISCOVERY_ACROSS_FILESYSTEM, CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR) (G7).

**Data tables (no branching):** `GIT_CONFINED` (e2e, acceptance → workspace getters), `WRAPPERS` (env, command, timeout, etc.), `PATH_ARGS` (init, clone, push, etc. → ALL/FIRST), `GIT_RULES` (Where → allows/reason), `ALLOWS` (READ_ONLY/ANY/NONE predicates).

**Modules:** New `git_check.py` (pure, ~380 LOC, I/O only via `paths.resolve_in`). Changed: `guard.py` (moves SAFE_GIT/NO_COMMIT_FLAGS, calls git_check), `presentation.py` (workspace survives bounce via `_ensure_workspace`), `dispatch.py` (GIT_CONFINED table, _confine_git call at setup end).

**Coverage:** ≥95%, all AC1–AC10 pass. E2E test `test_git_confinement.py` runs in real git (isolated_git fixture). No new dependency. See design `agile-team/docs/design/s65.md` (G1–G10, test checklist).

## s59: Rebase at sprint start (ADR-0041, rule R1–R12, docs updated)

Sprint-boundary sync rebases the team branch onto main instead of merging, dropping commits already upstream. False conflicts from sprint 18 (~100) are gone. The decision replaces ADR-005 decision 1 ("merge in, never rewrite").

**Key rules (R1–R12):**
- **R1:** `git rebase --empty=drop`, no merge, no `-s ours` or `-X ours`. Result is linear.
- **R2:** Boundary.sync_from pinned before rebase; save before rebase on first run guards against crash losing old hash map.
- **R5:** Commits paired by stamp (author, date, message); dropped commits map to last matched copy or rebase base.
- **R6:** Hashes rewritten in `REMAPPED` fields only (story commits, code commits, interrupted shas, stack entries); `checked`, `head`, `pushed`, `base` left alone.
- **R7:** Lost-content check validates no path changed without one side touching it; reset on violation.
- **R9:** New outcome `REBASED` (sha, rewritten count); tone is `"good"`.
- **R12:** Only START edge rebases; END edge unchanged.

**Docs updated:** `agile-team/SKILL.md` (sprint boundaries section), `agile-team/reference/protocol.md` (hold table, start step), `agile-team/docs/customer/review-stack.md`, fixture e93 (end-edge sync: `outcome: pass`, not `rebased`).

**Process in code:** `rewrite.py` pure, `Rebase` dataclass, `SyncOutcome` enum, dispatch via `AFTER_REBASE` dict (table-driven, no branching). E2E tests (5 cases) pending for integration-tester.

See design `agile-team/docs/design/s59.md` (R1–R12, test checklist, known limits), review round 3, ADR-0041.

## s89: Guard refined to let stdlib read source on 3.13 (no new ADR, extends s71)

Python 3.13 changed `linecache.updatecache` to use `__spec__.loader.get_source`, causing `open` calls charged to a non-exempt module (e.g. `_pytest.assertion.rewrite`). Rules T1–T6 fix the guard:

- **T1:** Source read is stdlib's. An audited event allowed when a frame of `SOURCE_READERS` (`traceback`, `linecache`) is on the stack **inside** the nearest guarded frame (`agile_team`, `tests`). With no guarded frame, whole stack counts.
- **T2:** Opener rule unchanged. `"traceback"` joins `EXEMPT_CALLERS`.
- **T3:** Code under test still fails. An open from `agile_team.*` or `tests.*` is refused even while traceback formats.
- **T4:** No new relaxation elsewhere. No event allowed by outer exempt modules (xdist, coverage).
- **T5:** Violation names its caller with `(caller: {caller})` suffix.
- **T6:** Patched calls (line 209) unchanged.

New helper `call_audited_through(names, event)` builds relay chains from synthetic modules for testing multi-frame stacks. See design `agile-team/docs/design/s89.md`.

## s81: CI stage at boundary; verdict rules data-driven (ADR-0040, extends s29)

New CI stage runs after the boundary pushes. Waits for `gh pr checks --watch` under `ci_timeout_s` deadline (default 1800s). Verdict is green only when every watched PR is green. Red or timeout holds the boundary until a bug story is recorded.

**Architectural decisions:**
1. **One new stage in pipeline:** `STAGES = (SYNC, CHECK, REVIEW, PUSH, CI)`. Runs after PUSH on every boundary that pushed, and at start only when restacking.
2. **Data-driven verdicts:** `Bucket` enum, `BUCKET_VERDICT` table (fail/cancel→red, pass→green, pending→pending), `CHECK_ORDER` = (red, pending, green), `PR_ORDER` = (red, pending, none, green). No branching on verdict type.
3. **Failing lines extracted:** Job id from link, log via `gh run view --job <id> --log-failed`. Match pytest/go patterns, max 20 lines, fallback last 10 non-blank.
4. **Only green marks ready:** Phrase "ready to merge" appears only in `ci_green` hand-over line and green report. Never from red, pending, none, local, or pushed reports.
5. **Hold until bug story recorded:** `record_ci_bug(tool)` writes `upstream.ci_bug`, closes the boundary with "checks failed, story sN opened". Bug story must be first in next sprint.
6. **No new dependency:** `gh` stays behind `Prs` interface. Unit tests fake it via `system.run` seam.

**Modules:** New `ci.py` (CiWatch class, verdict rules, text builders). Changed: `boundary.py` (stage, holds, state fields), `boundary_runner.py` (outcome methods), `upstream.py` (Prs protocol), `po_tools.py` (record_ci_bug tool), `config.py` (ci_timeout_s), `state.py` (loaders), `handover.py` (ci_green/ci_failed/ci_pending rules).

See ADR-0040, design `agile-team/docs/design/s81.md` (rules CI1–CI16).

## Seam completion (s77, no new ADR)

P3 closes s71 architecture. Six new `system.py` names: `home`, `which`, `on_signal`, `open_browser`, `async_sleep`, `HttpServer`. All 31 pre-P1 LEGACY tests migrated to fake or e2e. Ruff TID251 enforces `from agile_team import system` import discipline across all code.

**Consequence:** Seam is complete. Every OS interaction auditable and testable. All code follows one pattern. No branching on test type (world enum decides timeout). See ADR-0036 (s71 architecture).

## Key design principles (your domain)

- **Process in code, not prompt:** Gate rules, hold clearing, verdict logic, bounds are data tables or code functions, never prose agreements.
- **Data-driven over branching:** Tables (BUCKET_VERDICT, PR_ORDER, HALTS, WAITS, NORMALISE) let new cases be added without conditionals.
- **Single source of truth:** Snapshot carries raw data; browser derives views. Heartbeat carries both clocks; reader detects sleep. State.checkout is only branch record; check runs everywhere.
- **Blocking is safe:** CI stage blocks router up to 30 min; health stays green via `pulse.doing()`. Resume works (push saved before CI, resume reruns wait).

See ADRs 0007, 0009, 0013, 0015, 0027, 0040 for decisions on design patterns.

## Your focus (unchanged)

Review step sequences, gate checks, role boundaries. Ensure snapshot contract, state transitions, and error paths. Verify integration at role boundaries (tester → proxy, git ops seam, HTTP seam).
