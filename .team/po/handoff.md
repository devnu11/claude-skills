# PO handoff (written 2026-10-25, sprint 53 just started)

## Mandate and limits (source: .team/run/liaison/messages/t237.md)
- Sprint 53 is the last sprint of this run. It holds exactly s174, s175, s176, s181 (bug fixes). Pull nothing else in, bug fixes included; ask the liaison first. s180 stays in the Product Backlog.
- Budget: spend was $1169.51 of $1500 when sprint 53 started. Soft stop at about $1229.5 (sprint spend $60): stop starting steps and tell the liaison. Hard stop about $1244.5 ($75). Call `budget_status` now and then.
- Deadline: any story not at `land` by 07:30 on 2026-10-26 goes back to the Product Backlog with `revert_story`; the sprint ends with what has landed.
- Tell the liaison at once (`notify_user`) if: a story is quarantined twice; a runner fault needs a pin change; GitHub rate-limits us; a story's rebase step bounces twice or hits the s180-style "not rebased" fault (that story goes to the Product Backlog at once with `revert_story`). The sprint then ends with what has landed.
- Architect allocates each story its own REQ and ADR ids; no two stories reserve the same id. If two collide, the story that lands later renumbers its own ids (rebase only, keep landed files).
- When sprint 53 ends: `notify_user` kind `sprint-end` (with the Review: line and carried items), then kind `done`. Start no further sprint. If the runner refuses `done` because Product Backlog stories are ready, tell the liaison and wait (do not start a sprint).
- Main stays linear. Budget raises only in small steps. NEVER call `story_status` (over 400k chars); use the prompt's hand-over lists.
- Tool names are `mcp__team__*`. `run_role` is refused when a story's current step needs another role, so route through `continue_story` notes. Put the m228 wording in every `continue_story` note: no role edits another story's tests or code, except a test whose behaviour the story's own design retires, with the R-ids in the handoff's `asserts` field. Nobody edits test_s94 or test_s107.
- Test-only review findings go to the unit-tester or integration-tester (follow the review's next_role), never to implement.

## State
- Sprint 52 closed: s172, s178, s179 landed. PR #69 (https://github.com/devnu11/claude-skills/pull/69) was CI-green and ready to merge by fast-forward only; the human was told (m367). s180 was reverted into the Product Backlog at design (branch dropped). Its next design must use REQ-200..202 and ADR-0092 from the start; its story file still cites REQ-190..192 (m357).
- Sprint 53 started: s174, s175, s176, s181. Next the runner runs the Manager, then the stories. Story files: .team/stories/s174.md, s175.md, s176.md, s181.md. Designs, reviews and acceptance reports appear under agile-team/docs/design/, .team/reviews/, .team/acceptance/.

## Pending questions to the liaison (no answers needed to proceed)
- m368: the runner kept re-prompting me to start a sprint after sprint 52; answered in effect by t237 (sprint 53).
- m357: s180's story file cites REQ-190..192 (story amend?). Goes with s180 in the Product Backlog.
- m353/m354: request_story follow-ups for the Product Backlog (check s159 against s179's REQ-160 change; s159 and s163 against s180's REQ-164/REQ-169 changes). Not in sprint 53.

## What I do next
- Handle only the hand-overs the runner lists. For `land_bounced` on id collisions, `continue_story` with the renumber note. For round cap, `run_role` manager then act on its ruling. For `ci_green` on sprint 53, tell the human once ("PR ready"), then sprint-end, then `done`. For `requirements changed ... affected_done_stories`, `request_story` a follow-up for the Product Backlog.

## Carried to the sprint-end note (beyond sprint 51's list in m337)
- Manager's proposals: devops story for the worktree report path and hook access in acceptance steps; a note on `/bin/cp` and split bash commands; real-git tests for s179 and s180; a gate that checks the files PRESENTATION.md names exist; a DevOps pre-check for id collisions.
- The code-reviewer role file should name unit-tester or integration-tester; `run_role` should accept a tests-owning role on a story sent back for tests.
- story_ci_red names no job or step at implement r0 (s172 fixed this). Round-cap hand-over lacks gate reasons and a rounds history; ops-review hold hand-over gives no reason; crash.log has the oldest entries first; the quarantine hand-over does not list the sha's files.
- Parallel stories collided on REQ ids (s178 fixed) and then ADR numbers (not covered). The architect step should check other open stories' branches for the next free ids. The pure-rebase story check rejects renumber commits (s180 bug; the Manager `advance` ruling gets past one step only, the check fires again at each later step).
- A Manager land-conflict ruling with now_at=implement sends the story back through implement; a land step would be cheaper.
- story_status is about 400k chars; a compact open-stories summary would cut PO cost.
- A story waiting on a liaison answer counts toward the stuck hand-over limit; `revert_story` drops the branch even when asked to keep it; the `until-blocker` cadence re-prompts to start a sprint and refuses done when a human said stop (a stop-after-this-sprint flag would help); the ci_green hand-over arrived twice after the human was told.
- Product Backlog, unscheduled: s169, s170, s171 (onboarding), s173, s177, s180, m284, the follow-up stories above.

## Friction answers to the Manager
- Per step I read only the hand-over, the story_status JSON in the prompt when present, and a liaison message file when named; no event log and no story files unless a ruling needs them. A compact open-stories summary in the brief would replace the large block. The $10.20 per step figure was the pre-s25 overcount.
- Routing: follow the review's next_role; test-only findings go to unit-tester/integration-tester, never to implement.
