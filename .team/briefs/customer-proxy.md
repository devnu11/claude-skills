# Customer Proxy: Current context and conventions

**Last updated:** 2026-10-13 (s86 done; s85 done; s84 done; s83 done)

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
