# Product Owner: Current context and conventions

**Last updated:** 2026-10-13 (s103 done; s92 done; s97 done; s104 done; s96 done; s86 done)

## s103 complete: Guard refusal messages now clear and rule-named (no new ADR)

When a role's test command is refused (e.g., full-suite run), the guard now gives a clear message: `"refused by rule '{rule}': {why}. Allowed: {allowed}"`. This means no guesswork on what's allowed—the refusal names the rule and shows the exact permitted form. Roles can now save test output to a file: `pytest > out.txt`, `| tee out.txt` forms are allowed for named runs (full-suite still refused). Role files no longer say "run under `timeout` command" (macOS has none); they say "use the Bash tool's `timeout` parameter". No new hand-overs or tools; this is a clarity improvement to error messages. No new ADR (extends guard pattern from s69/s43/s41). See design `agile-team/docs/design/s103.md`.

## s92 complete: Gate failures route to file owners; no disputes, no rounds (no new ADR)

Gate failures (coverage, lint, static) now route by file ownership. A failing e2e test goes to integration-tester; ruff finding in tests/ goes to unit-tester; developer's files bounce to implement. Each owner gets a gate-fix step (queued, no round). Multiple owners → multiple fix steps before returning to implement. **Your new visibility:** Next `_advance_and_log` shows `"fixes": [{role, files}]` for each routed item. Hand-over says "Other roles fix items first, then this step runs again." No new tools, no new disputes. See design `agile-team/docs/design/s92.md` (rules R1–R20).

## s97 complete: Step time leaves out machine sleep (no new tool, no new hand-over)

Dashboard now shows awake time—machine sleep is subtracted from step durations. **What you see:**
- **Flow boxes and Time chart:** Times shown are "awake time" (machine awake only). On macOS/Linux, monotonic clock pauses during sleep; on Windows, the runner counts sleep via heartbeat, and wall time minus sleep gives awake time.
- **Running step:** Shows elapsed awake time. "may include sleep" note appears for old steps without sleep data.
- **Time legend:** Says "Awake time (agent steps only; runner stages: see A6)".

**How it works:** Step events record two clocks: monotonic (POSIX) and sleep counter (all). Heartbeat counts sleep between beats. Snapshot builds awake duration per step using platform-specific rules (POSIX: monotonic delta; Windows: wall delta minus sleep). Old steps without data fall back to wall time and are marked. No new tools, no new hand-overs. Verification: all unit tests pass, P1 node-harness page tests pending (integration-tester).

No new ADR (extends snapshot data pattern from s96). See design `agile-team/docs/design/s97.md` (rules AW1–AW13, snapshot contract).

## s104 complete: Flow chart readable in all scopes—unused roles hidden (no new tool, no new hand-over)

Bug fixed. Flow chart labels were stacked at top-left in Story scope, boxes empty. **Cause confirmed:** WebKit renders opacity-applied HTML in foreignObject on its own layer at SVG origin. 

**What you see now:**
- **Flow chart is readable:** Every role's label sits inside its box, in Story, Sprint, and Run scopes. Works after tab switch, live update, window resize.
- **Unused roles not shown:** A built-in role that has never run (e.g., `developer-db`) doesn't clutter the chart. The chart draws only roles the pipeline routes to or that have run. A role becomes visible with its first step event.
- **Dimmed roles by colour:** Roles with no data in a scope are dimmed by colour, not faded—no WebKit rendering bug.
- **Idle indicator:** A dimmed box shows "idle" instead of `$0.00`, making it clear no activity happened.

**No changes to your workflow.** No new tools, no new hand-overs. The dashboard continues to show the team's state at a glance. All ACs verified by the runner on Chromium; AC1's Safari check left to the human per this ruling.

No new ADR (extends s27/s4 snapshot pattern). See design `agile-team/docs/design/s104.md` (rules FL1–FL9), ADR-0047.

## s96 complete: Time per role on Flow chart and "Time by" chart (no new tool, no new hand-over)

Dashboard now shows step wall time (agent steps only, from events.jsonl). **What you see:**
- **Flow boxes:** Each role's box now displays total time spent (e.g., "architect · 124 tokens · $0.42 · 2 h 5 min"), updated as steps finish. Active (running) box adds a live line (e.g., "⏱ running 12 min") updated once per minute without new snapshot.
- **Time measure on "Tokens by" chart:** New third measure button next to Tokens and Dollars. Shows time spent per group (Role, Story, or Model), largest first, with step count and share in tooltips. Legend: "Step time (agent steps only; runner stages: see A6)".
- **No runner stages counted:** Only agent work (dev, architect, unit-tester, etc.) counts. PO queries, gate runs, syncs, and presentation builds are excluded.

**No changes to your workflow.** No new tools. No new hand-overs. Time is data-driven from the snapshot like tokens and cost. Runner stages (A6) are not yet measured (future story).

All ACs pass (23 unit tests, code review done; P1 tests pending). See design `agile-team/docs/design/s96.md` (no ADR: extends snapshot data pattern).

## s86 complete: Story dependencies as data (ADR-0046)

Stories now have `depends_on: [s1, s2]` lists in frontmatter. The runner loads them at start and `start_sprint`, validates as a graph (no cycles, unknown, self), and won't start a story until its dependencies are done (skip reason: `waiting on sN`). The Backlog tab shows dependencies and warns when the human reorders a story above one it depends on; the warning is in the timeline.

**What's new for you:**
- **New `open_story` parameter:** `depends_on` is a list of story ids that must match the story file's frontmatter. Pass the same list to both. Unknown ids, self-references, and cycles are refused (exact error messages naming stories). Done dependencies are valid (story is satisfied).
- **New `start_sprint` check:** The runner reloads `depends_on` from every open story's file before the sprint begins. A bad list (shape, self, unknown, cycle) refuses the sprint.
- **Skip reason on stall:** When the pipeline stalls because a story is waiting on dependencies, the hand-over reads `s5 at design: waiting on s1, s2` (in list order, not natural order).
- **No new tool.** Your `open_story` and `start_sprint` tools work as before; the new `depends_on` parameter is optional and must match the file.

**Migration complete (AC4):** Table M stories (s2, s6, s16, s32, s33, s35, s36, s94, s95, s102) now have `depends_on` in frontmatter, prose removed. Done-dependent stories (s10, s34, s39, s54, s55) have no `depends_on` entry (dropped by AC4's rule). No prose "Depends on sN" remains in open stories. A test (P1, integration-tester) will pin this.

See ADR-0046, design `agile-team/docs/design/s86.md` (DP1–DP15, known limits).

## s85 complete: The liaison's opinions on backlog stories (ADR-0045)

The liaison can now suggest changes to any backlog story. Opinions are recorded as data (like s84 threads), shown on the dashboard with badges and a filter, and the human can act on them from there. Applied opinions (other than moves) arrive as thread posts to you, suggesting the human agrees with the liaison's recommendation.

**What's new for you:** When a human applies a non-move opinion (fold, close, scope, ask, or move on a sprint story), the hand-over arrives as a thread post: "The human applied the liaison's opinion <oN> on <story>: <kind>. <opinion text>." Treat it as the human's decision/request, answering with `reply_story` as you would any thread post. (Move opinions go to the reorder queue; close goes to you, not yet a cancel.)

**Snapshot:** New `opinions` section with items, review status, and last-asked time. Opinion and opinion-act events merged into timeline by date.

No new tools; no change to your workflow beyond new thread post types. All ACs pass; P1 work (node-harness and e2e) for integration-tester.

See ADR-0045, design `agile-team/docs/design/s85.md`.

## s84: Story threads—human discusses directly on the dashboard (ADR-0044)

The human can now post questions to you on a story's thread on the Backlog tab. You reply with a new tool, `reply_story`, and the answer shows under the story. All ACs pass (code review done; node harness and e2e tests pending for integration-tester).

**What's new for you:**
- **Thread discussion:** When the human writes to you on a story's thread, the hand-over says "The human wrote to you on sN's thread (tK): read the file." Open the file (or find it in `liaison/messages/tK.md`) and read the question. Respond with `reply_story(story, text)`.
- **New tool:** `reply_story(story: str, text: str)` - "Answer the human on a story's thread (shown under the story on the dashboard)." Unknown story, empty or over-long text (>4000 chars) refused with exact error. On success, the reply appears under the story within seconds (via SSE). Posts a `reply` message to the outbox, tagged with the story.
- **Distinction from `notify_user`:** If the hand-over names a thread post, use `reply_story` (not `notify_user`). The thread is a conversation, not a change order; respond as you would to a `tell`. `notify_user` refuses `kind="reply"` automatically, so the tool won't let you post replies outside the thread.
- **Thread as a view:** The thread shows all human posts (to you or to the liaison), your replies, liaison replies, and the liaison's posts. It's read-only on the dashboard without the token; write access is localhost-only, guarded like the Backlog reorder form.

**Hand-over integration:**
- No new hand-over section. Thread posts arrive as `human_message` passes (existing). The line names the story and tells you to read the file. `told` stories in _deliver include tagged relay files.

**Snapshot:** New top-level `thread` array with entries (id, story, author, to, text, at). Events gain `thread` kind entries (no longer as `message`). Outbox `reply` messages no longer dual-logged as message events.

**Implementation:** New `threads.py` module (reads four file sources and merges by time). Relay adds REPLY kind. Router uses `threads.told_line`. CLI adds `reply` command. Watch adds `liaison_message` trigger. Dashboard adds `/api/thread` endpoint and thread form on expanded Backlog rows.

**Shipped:** Code review done (minor findings: m1 nested div in page, m2 bool check in snapshot). All 19 design rules (H1–H19) enforced in code. No changes to your existing tools or workflow beyond `reply_story` as a new option for hand-over questions.

See ADR-0044, design `agile-team/docs/design/s84.md`.

## s83: Backlog tab with human reorder requests (ADR-0043)

Human can read and reorder the backlog on the dashboard. The Backlog tab lists every story not done, in two groups: Current sprint (read-only) and Backlog. Each row shows position, id, title, step, status, delivery, label, and hold reason. Click a row to expand and see the story file, state fields, design/review/acceptance links, spend/turns, and last 10 events. To reorder: click or drag a Backlog story to a new position.

**What's new for you:**
- **Human's order binds you.** When the human reorders the backlog on the dashboard, `state.human_order` records their backlog. A `prioritise` or `move_story` that changes their order is refused unless you give a non-blank `reason`, which is logged. Empty `human_order` guards nothing; you can change the order freely until the human reorders once.
- **Reorder requests come between steps.** The dashboard queues requests in `.team/run/reorders/`. Between steps, the router applies them via `desk.apply()`, emitting `priority` events with `source: "human (dashboard)"`. You are told in the hand-over ("From the dashboard: …") about applied moves and the new backlog order. Stale requests (order changed since they were sent) are refused; the human reloads the page.
- **New hand-over section (`_take_reorders`):** Appears between lead and prompt. Lists applied reorder ids with reasons and resulting backlog. Clears `state.reorders_told` after hand-over.
- **New tool:** None. The tools you have (`prioritise`, `move_story`) still work; they now check the human-order rule.

**Implementation:** New modules `backlog.py` (groups, order version, refusals) and `reorders.py` (request queue, apply). Snapshot adds `order_version`, `backlog`, `reorders` (last 20). Events gain `source` field. Fixture and contract in `agile-team/docs/design/s83.md` (rules B1–B20) and design spec.

**Shipped:** Code review done (all ACs pass); P1 work (node-harness and e2e tests) for integration-tester. No changes to your existing tools or workflow beyond the new hand-over section and human-order rule.

See ADR-0043, design `agile-team/docs/design/s83.md`.

## s15: Dashboard renders Markdown safely (ADR-0042)

Questions tab and timeline handoff summaries now display formatted text (headings, lists, emphasis, code blocks, tables, links). Safe: raw HTML escapes, links limited to http(s), images disabled. Falls back to plain text if markdown-it library doesn't load. One renderer function, pinned URL like Mermaid, no build step.

**What's changed:** Human-facing—Questions are now readable with formatting. No new hand-overs or tools for you. Integration-tester writes e2e tests for 10 cases (syntax, link safety, payload inertness, plain fallback). Code-reviewer checks rules M1–M12. Rule change: "exactly two pinned URLs" (Mermaid + markdown-it).

See ADR-0042, design `agile-team/docs/design/s15.md` (rules M1–M12).

## s51: Started stories rank first; pulls need reasons (ADR-0016 amended)

Stories with commits always rank first, held started ones after in-progress, then stories not yet started. Your order ranks stories within each group. To pull a not-started story ahead of started ones, use `prioritise` or `move_story` with a reason; without one the tool is refused. `start_sprint` never pulls. **ADR-0016 amended:** ranking rule is `(done, RANK[tier], listed, natural(id))` where `RANK` = {in progress: 0, held: 1, not started: 2}. New `state.pulled` field holds pulled story ids. Priority events now include `"pulled"` in data for audit.

## s65: Git safety—presentations and acceptance run in isolated git (no new ADR)

S61 incident fixed: integration-tester's demo no longer has a path to the human's branches. Two safeguards now:
1. **Environment:** Confined steps get `GIT_CEILING_DIRECTORIES` so git can't climb out of `.team/run`.
2. **Guard:** New `git_check` module sees through `env`, `command`, prefixes; denies git targeting the team repo, allows git in the workspace.

**What changes for you:** Nothing. No new hand-overs, no new tools. Presentations and acceptance work as before, but safer. If a delivery's script accidentally targets the team repo, the guard denies it with a clear message (naming the repo). S67's e2e watch test passed, so the workspace demo rebuilt safely.

No new dependency, no ADR (extends guard pattern). See design `agile-team/docs/design/s65.md` (rules G1–G10).

## s59: Sprint-start sync rebases the team branch onto main (ADR-0041)

Sync no longer merges; it rebases, dropping commits already upstream. False conflicts from sprint 18 (~100 on m54) are gone. Hashes pinned before rebase and rewritten after; nothing is lost. Real conflicts abort cleanly; human rebases by hand and continues. End-edge unchanged. One new boundary outcome: `rebased` (tree kept, hashes rewritten; tone: `good`).

**What changed for you:**
- `sync_conflict` hand-over now lists conflicting files grouped by directory with counts, e.g. ". (1): README.md; src (2): a.py, b.py".
- No more `-s ours` or `-X ours` merges. The branch is always linear.
- New tool: none (the old `merge_in` is gone; `rebase_onto` is internal).

See ADR-0041, design `agile-team/docs/design/s59.md` (rules R1–R12), review round 3 (all defects fixed; e2e pending for integration-tester).

## s89: Unit suite passes on 3.13 (OS guard refined, test infrastructure, no new ADR)

Bug fix. 36 unit tests failed on 3.13 when formatting tracebacks because Python 3.13's `linecache` read source via a path the guard charged to the wrong caller. Guard refined with rules T1–T6: allow stdlib source reads inside guarded frames, still catch real code. Accepted on AC1–AC3 (unit pass, traceback works, guard still catches real OS). AC4 (CI green on PR #16) verified at s81 CI boundary. No runtime changes, no new ADR (extends s71).

## s81: Boundary waits for PR's CI checks; "ready to merge" only from green (ADR-0040)

Sprint boundary now has a CI stage that waits for GitHub Actions checks via `gh pr checks --watch`. All ACs pass (e2e test work carried to integration-tester step).

**Your new hand-overs (three rows in `handover.py`):**
- **`ci_green`:** PR is ready to merge. Tell the human to merge with "Rebase and merge". Only this hand-over names a PR ready.
- **`ci_failed`:** PR is NOT ready. Failing checks and lines are in the `checks` field. At once: `open_story` a bug story, `record_ci_bug(story)` to record it, tell the human the PR is NOT ready, and list the story first in the next `start_sprint`.
- **`ci_pending`:** PR is NOT ready yet (checks still running or timeout). Pending check names in the `checks` field. Tell the human NOT ready, then `continue_boundary` to wait again.

**Your new tool:** `record_ci_bug(story)` closes a boundary held on failed CI. The story must exist, be open, and be named. The boundary then finishes. Refusal if boundary has no CI hold, story unknown, or story done.

**Config:** `[gates] ci_timeout_s` (default 1800.0, ~30 min). Raise it if CI is slow. No "ready" wording outside `ci_green` hand-over.

**In all paths (pushed, local, red, pending, none):** Never call a PR "ready" unless the hand-over is `ci_green`. A timeout or no checks means not ready, hold stands, or boundary completes with "not ready" text.

See ADR-0040, design `agile-team/docs/design/s81.md` (rules CI1–CI16).

## Previous decisions (brief summary)

- **s78:** Health no longer false-red during work. Sleep detection via monotonic time. See ADR-0038.
- **s75:** DevOps scopes test runs; exemption from s69 exists only for onboarding. ADR-0039.
- **s74:** Graceful stop is neutral (plain `stopped`). See ADR-0037.
- **s4:** Dashboard backend snapshot, SSE server, CLI. See ADR-0027.
- **s62:** Liaison has `tell` and `watch` commands. See ADR-0029.
- **s61:** Runner halts if branch/commit changes. See ADR-0028.
- **s29:** Boundary steps (sync, push, review). See ADR-0015.

## Your role (unchanged)

Judge boundary holds and hand-overs. Run tools and make decisions. The router drives the pipeline. Your brief updates with each role step.
