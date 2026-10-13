# Code Reviewer: Current context and conventions

**Last updated:** 2026-10-13 (s84 done; s83 done)

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
