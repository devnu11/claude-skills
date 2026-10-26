# PO handoff (written 2026-10-25, sprint 53 in progress)

## Mandate and limits (source: .team/run/liaison/messages/t237.md, t243-t245)
- Sprint 53 is the last sprint of this run. It holds exactly s174 (done, landed), s175, s176, s181 (done, landed). Pull nothing else in; ask the liaison first. The Product Backlog stays as is: s180, s182-s186, s169-s171, s173, s177 and older.
- Budget: $1185.52 of $1500 at last check. Soft stop about $1229.5, hard stop about $1244.5. Call `budget_status` now and then. At the soft stop, stop starting steps and tell the liaison.
- Deadline: any story not at `land` by 07:30 on 2026-10-26 goes back to the Product Backlog with `revert_story`; the sprint ends with what has landed.
- `notify_user` at once if: a story is quarantined twice; a runner fault needs a pin change; GitHub rate-limits us; a story's rebase step bounces twice or hits the s180-style "not rebased" fault (that story goes to the Product Backlog with `revert_story`).
- When sprint 53 ends: `notify_user` kind `sprint-end` (Review: line, carried items below), then kind `done`. Start no further sprint. If `done` is refused because Product Backlog stories are ready, tell the liaison and wait. `notify_user` blocked/done is refused while a Sprint Backlog story can move; use kind `update` then.
- Main stays linear. NEVER call `story_status` (over 400k chars); use the prompt's hand-over lists.
- Every `continue_story` note carries the m228 wording: no role edits another story's tests or code, except a test whose behaviour the story's own design retires, with the R-ids in the handoff's `asserts` field. Nobody edits test_s94 or test_s107. Test-only review findings go to the unit-tester or integration-tester, never to implement.
- `run_role` and `continue_story` are refused while the story has a step running; leave it to the runner and retry on the next hand-over.

## State of the sprint (last seen)
- s174: landed (done). s181: landed (done).
- s175: at land. Manager ruled upgrade_model (rounds reset, now_at land). I set developer-api to opus/medium (manager review of that override is due) and released it with a note: developer-api rebases team/story-s175-r1 onto the sprint head and resolves the docs-only conflict in agile-team/docs/architecture.md; then land reruns. Files: .team/stories/s175.md, agile-team/docs/design/s175.md, .team/reviews/s175.md, .team/acceptance/s175.md (PR #72). Watch for a second land bounce: if the rebase bounces twice or hits the "not rebased" fault, notify_user and `revert_story`.
- s176: sent back to the tests step by manager ruling (fault unit-tester, rounds reset). Findings R5-1..R5-7 in .team/reviews/s176.md are test-only gaps for design R1-R6; the unit-tester checks each against current tests and adds tests only for open ones. Released with continue_story. Files: .team/stories/s176.md, agile-team/docs/design/s176.md (PR #73). If it hits the round cap again, run the manager with a brief naming story file, design, review and history; consider `revert_story` if the 07:30 deadline is close.

## Pending questions / open items (none block a story)
- m368, m357 (s180's story file cites REQ-190..192; its next design must use REQ-200..202 and ADR-0092), m353/m354 (follow-ups for the Product Backlog), m371 (answered by s186). m380 (flaky-test story request) was withdrawn by the liaison in t245; no story will be written.
- Messages t238-t242 announced Product Backlog stories s182-s186; left unscheduled on purpose.

## What I do next
- Handle only the hand-overs the runner lists. Story CI red: check whether the failure is in the story's changed files; if so `continue_story` with the failing tests, the run link and the m228 wording. Known flake (test_system.py::test_a_timeout_stops_the_whole_process_group): just rerun. Round cap: `run_role` manager with a brief naming the story file, design, review and history, then `continue_story` with the ruling. `ci_green` on sprint 53: tell the human once ("PR ready"), then sprint-end, then `done`. `affected_done_stories`: `request_story` a follow-up for the Product Backlog.
- Watch the 07:30 deadline and the budget soft stop.

## Carried to the sprint-end note
- Manager's proposals: devops story for the worktree report path and hook access in acceptance steps; a note on `/bin/cp` and split bash commands; real-git tests for s179 and s180; a gate that checks files PRESENTATION.md names exist; a DevOps pre-check for id collisions; fix-step briefs name the gated commit and whether the tree moved (the liaison will file it).
- The code-reviewer role file should name unit-tester or integration-tester; `run_role` should accept a tests-owning role on a story sent back for tests.
- Hand-over gaps: round-cap lacks gate reasons, rounds history, open-finding ids per role, and the step the story is at; ops-review hold gives no reason; crash.log oldest first; quarantine hand-over doesn't list the sha's files; story-CI hand-over lists "N errors" without names, doesn't say whether the failing test is in the story's changed files or which package owns it, and arrives while the next step is already running. Review briefs lack a "since last review" commit range.
- Lint (ruff, house-rules) and e2e failures reached story CI on s176 and s181; the implement gate does not catch them. A gate running ruff, house-rules and the e2e files a story touches before landing would save rounds.
- Parallel stories collided on REQ ids (s178 fixed) and ADR numbers (not covered). The architect step should check other open stories' branches for the next free ids. The pure-rebase check rejects renumber commits (s180; now s182).
- A Manager land-conflict ruling with now_at=implement sends the story back through implement; a land step would be cheaper (s175 got now_at=land this time).
- story_status is about 400k chars; a compact open-stories summary would cut PO cost.
- A story waiting on a liaison answer counts toward the stuck hand-over limit; `revert_story` drops the branch even when asked to keep it; the `until-blocker` cadence re-prompts to start a sprint and refuses done when a human said stop; ci_green arrived twice after the human was told; `run_role` is refused while a step runs, so a liaison request to run the manager can't be done at once.

## Friction answers to the Manager
- Per step I read only the hand-over lines and, when a line names it, a message file or one story file/grep; no event log, no story_status. A compact open-stories summary would replace the large state block. The $10.20 per step figure was the pre-s25 overcount.
- Routing: follow the review's next_role; test-only findings go to unit-tester/integration-tester, never to implement (s152 F1 to integration-tester; s179 not to implement).
