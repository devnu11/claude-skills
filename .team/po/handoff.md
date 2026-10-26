# PO handoff (written 2026-10-25, sprint 53 in progress)

## Mandate and limits (source: .team/run/liaison/messages/t237.md)
- Sprint 53 is the last sprint of this run. It holds exactly s174, s175, s176, s181 (bug fixes). Pull nothing else in, bug fixes included; ask the liaison first. Product Backlog stays: s180, s182, s183, s184, s185, s186, s169-s171, s173, s177 and older.
- Budget: $1169.51 of $1500 at sprint 53 start. Soft stop about $1229.5 (sprint spend $60): stop starting steps and tell the liaison. Hard stop about $1244.5. Call `budget_status` now and then.
- Deadline: any story not at `land` by 07:30 on 2026-10-26 goes back to the Product Backlog with `revert_story`; the sprint ends with what has landed.
- `notify_user` at once if: a story is quarantined twice; a runner fault needs a pin change; GitHub rate-limits us; a story's rebase step bounces twice or hits the s180-style "not rebased" fault (that story goes to the Product Backlog with `revert_story`).
- Architect allocates each story its own REQ and ADR ids; if two collide, the later-landing story renumbers (rebase only).
- When sprint 53 ends: `notify_user` kind `sprint-end` (Review: line, carried items), then kind `done`. Start no further sprint. If `done` is refused because Product Backlog stories are ready, tell the liaison and wait.
- Main stays linear. NEVER call `story_status` (over 400k chars); use the prompt's hand-over lists.
- Every `continue_story` note carries the m228 wording: no role edits another story's tests or code, except a test whose behaviour the story's own design retires, with the R-ids in the handoff's `asserts` field. Nobody edits test_s94 or test_s107. Test-only review findings go to the unit-tester or integration-tester (the review's next_role), never to implement.

## State of the sprint (last seen)
- s174 (venv hidden from gate commands): PR #70; story CI was red once (test_s118_tally_watch) and sent back to implement; now at land. Code-reviewer F1 (acceptance-environment sandbox.sandbox_env commands) answered: out of scope, follow-up requested (m371) and written as s186 in the Product Backlog.
- s175 (landing error text): implement r1 after CI red (13 tests: test_s175_land_error plus stage-event key tests); now review.
- s176 (story-rebase local git): implement; CI red twice (test_s103 Rule.GIT_OWN_BRANCH, then ruff I001/E501 in git_check.py and story_rebase.py, and house-rules verb names). Sent back each time with a note.
- s181 (heartbeat chore row): implement; CI red twice (unit chores/heartbeat v3 tests, then 5 e2e tests: page.js:364 errors, chore panel text, gate health amber/green). Last note told the developer to fix the code first and to flag any e2e test that its design retires in `asserts`, not edit it (e2e files belong to the integration-tester).
- Story files: .team/stories/s174.md, s175.md, s176.md, s181.md. Designs under agile-team/docs/design/, reviews under .team/reviews/, acceptance under .team/acceptance/.

## Pending questions / open items (none block a story)
- m368, m357 (s180 story file cites REQ-190..192; its next design must use REQ-200..202 and ADR-0092), m353/m354 (request_story follow-ups for the Product Backlog), m371 (answered by s186). None need an answer to proceed.
- Messages t238-t242 announced Product Backlog stories s182-s186; all left unscheduled on purpose (sprint closed to additions). Mention them to the liaison only if asked.

## What I do next
- Handle only the hand-overs the runner lists. Story CI red: `continue_story` with the failing tests, the run link and the m228 wording. Round cap: `run_role` manager, then act on the ruling. `ci_green` on sprint 53: tell the human once ("PR ready"), then sprint-end, then `done`. `affected_done_stories`: `request_story` a follow-up for the Product Backlog.
- Watch the 07:30 deadline and the budget soft stop.

## Carried to the sprint-end note
- Manager's proposals: devops story for the worktree report path and hook access in acceptance steps; a note on `/bin/cp` and split bash commands; real-git tests for s179 and s180; a gate that checks files PRESENTATION.md names exist; a DevOps pre-check for id collisions.
- The code-reviewer role file should name unit-tester or integration-tester; `run_role` should accept a tests-owning role on a story sent back for tests.
- Hand-over gaps: round-cap lacks gate reasons and rounds history; ops-review hold gives no reason; crash.log oldest first; quarantine hand-over doesn't list the sha's files; story-CI hand-over lists "N errors" without names.
- Lint (ruff, house-rules) and e2e failures reached story CI on s176 and s181; the implement gate does not catch them. A gate running ruff, house-rules and the e2e files a story touches before landing would save rounds.
- Parallel stories collided on REQ ids (s178 fixed) and ADR numbers (not covered). The architect step should check other open stories' branches for the next free ids. The pure-rebase check rejects renumber commits (s180; now s182).
- A Manager land-conflict ruling with now_at=implement sends the story back through implement; a land step would be cheaper.
- story_status is about 400k chars; a compact open-stories summary would cut PO cost.
- A story waiting on a liaison answer counts toward the stuck hand-over limit; `revert_story` drops the branch even when asked to keep it; the `until-blocker` cadence re-prompts to start a sprint and refuses done when a human said stop (a stop-after-this-sprint flag would help); ci_green arrived twice after the human was told.

## Friction answers to the Manager
- Per step I read only the hand-over lines and, when a line names it, a message file or one story file/grep; no event log. A compact open-stories summary would replace the large story_status block. The $10.20 per step figure was the pre-s25 overcount.
- Routing: follow the review's next_role; test-only findings go to unit-tester/integration-tester, never to implement (s152 F1 to integration-tester; s179 not to implement).
