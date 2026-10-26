# PO handoff (written 2026-10-25, sprint 53 in progress)

## Mandate and limits (source: .team/run/liaison/messages/t237.md, t243-t245)
- Sprint 53 is the last sprint of this run. It holds exactly s174 (done, landed), s175, s176, s181. Pull nothing else in; ask the liaison first. The Product Backlog stays as is: s180, s182-s186, s169-s171, s173, s177 and older.
- Budget: $1185.52 of $1500 at last check. Soft stop about $1229.5, hard stop about $1244.5. Call `budget_status` now and then. At the soft stop, stop starting steps and tell the liaison.
- Deadline: any story not at `land` by 07:30 on 2026-10-26 goes back to the Product Backlog with `revert_story`; the sprint ends with what has landed.
- `notify_user` at once if: a story is quarantined twice; a runner fault needs a pin change; GitHub rate-limits us; a story's rebase step bounces twice or hits the s180-style "not rebased" fault (that story goes to the Product Backlog with `revert_story`).
- When sprint 53 ends: `notify_user` kind `sprint-end` (Review: line, carried items), then kind `done`. Start no further sprint. If `done` is refused because Product Backlog stories are ready, tell the liaison and wait. `notify_user` blocked/done is refused while a Sprint Backlog story can move; use kind `update` then.
- Main stays linear. NEVER call `story_status` (over 400k chars); use the prompt's hand-over lists.
- Every `continue_story` note carries the m228 wording: no role edits another story's tests or code, except a test whose behaviour the story's own design retires, with the R-ids in the handoff's `asserts` field. Nobody edits test_s94 or test_s107. Test-only review findings go to the unit-tester or integration-tester, never to implement.
- `run_role` and `continue_story` are refused while the story has a step running; leave it to the runner and retry on the next hand-over.

## State of the sprint (last seen)
- s174: landed (done).
- s175: held at implement r3 after the round cap. I ran the manager (ruling applied, now_at implement) and released it with continue_story. Developer fixes D12, D13, D14, C1 (code only); then unit-tester adds T1-T8 and integration-tester adds the e2e landing test. Details: .team/reviews/s175.md, agile-team/docs/design/s175.md, .team/stories/s175.md. tests/test_router.py::test_a_crash_in_a_step_hands_over_an_error_and_holds is an old assertion ('error') the design retires ('error: <reason>', AC3). Story CI was red on it at d92f504 (PR #72).
- s176: held at tests r3 after the round cap. Manager ruling applied (now_at implement) and released with continue_story. Developer fixes ruff I001/E501 in git_check.py and story_rebase.py and renames five helpers (_after_sub, _value_of, _short_create, _rebase_operands, _positions); then unit-tester updates test_s103 and adds 5 get_next_head cases and 3 chained refusal cases to test_s176_branch_guard.py. Files: .team/stories/s176.md, agile-team/docs/design/s176.md, .team/reviews/s176.md (PR #73).
- s181: after the liaison's t243/t244 messages the quality gate passed on rerun, and the story moved on (review, e2e, then land). Last seen at implement r2 after a further red story CI, so check the latest hand-over. Its story CI had also failed once on tests/test_system.py::test_a_timeout_stops_the_whole_process_group: a known flake in render-markdown's test helper (t245). Rerun the CI rather than routing it to a role. Files: .team/stories/s181.md, agile-team/docs/design/s181.md (PR #71).

## Pending questions / open items (none block a story)
- m368, m357 (s180's story file cites REQ-190..192; its next design must use REQ-200..202 and ADR-0092), m353/m354 (follow-ups for the Product Backlog), m371 (answered by s186). m380 (flaky-test story request) was withdrawn by the liaison in t245; no story will be written.
- Messages t238-t242 announced Product Backlog stories s182-s186; left unscheduled on purpose.

## What I do next
- Handle only the hand-overs the runner lists. Story CI red: check whether the failure is in the story's changed files; if so `continue_story` with the failing tests, the run link and the m228 wording. Known flake: just rerun. Round cap: `run_role` manager with a brief naming the story file, design, review and the history, then `continue_story` with the ruling. `ci_green` on sprint 53: tell the human once ("PR ready"), then sprint-end, then `done`. `affected_done_stories`: `request_story` a follow-up for the Product Backlog.
- Watch the 07:30 deadline and the budget soft stop.

## Carried to the sprint-end note
- Manager's proposals: devops story for the worktree report path and hook access in acceptance steps; a note on `/bin/cp` and split bash commands; real-git tests for s179 and s180; a gate that checks files PRESENTATION.md names exist; a DevOps pre-check for id collisions; fix-step briefs name the gated commit and whether the tree moved (the liaison will file it).
- The code-reviewer role file should name unit-tester or integration-tester; `run_role` should accept a tests-owning role on a story sent back for tests.
- Hand-over gaps: round-cap lacks gate reasons, rounds history and open-finding ids per role; ops-review hold gives no reason; crash.log oldest first; quarantine hand-over doesn't list the sha's files; story-CI hand-over lists "N errors" without names, doesn't say whether the failing test is in the story's changed files or which package owns it, and arrives while the next step is already running.
- Lint (ruff, house-rules) and e2e failures reached story CI on s176 and s181; the implement gate does not catch them. A gate running ruff, house-rules and the e2e files a story touches before landing would save rounds. The integration-tester's "passes on the current tree" on s181 was wrong.
- Parallel stories collided on REQ ids (s178 fixed) and ADR numbers (not covered). The architect step should check other open stories' branches for the next free ids. The pure-rebase check rejects renumber commits (s180; now s182).
- A Manager land-conflict ruling with now_at=implement sends the story back through implement; a land step would be cheaper.
- story_status is about 400k chars; a compact open-stories summary would cut PO cost.
- A story waiting on a liaison answer counts toward the stuck hand-over limit; `revert_story` drops the branch even when asked to keep it; the `until-blocker` cadence re-prompts to start a sprint and refuses done when a human said stop; ci_green arrived twice after the human was told; `run_role` is refused while a step runs, so a liaison request to run the manager can't be done at once.

## Friction answers to the Manager
- Per step I read only the hand-over lines and, when a line names it, a message file or one story file/grep; no event log. A compact open-stories summary would replace the large story_status block. The $10.20 per step figure was the pre-s25 overcount.
- Routing: follow the review's next_role; test-only findings go to unit-tester/integration-tester, never to implement (s152 F1 to integration-tester; s179 not to implement).
