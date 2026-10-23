# PO handoff (written 2026-10-23, sprint 52 running)

## Mandate and limits
- Sprint 51 closed. Sprint 52 is the one extra sprint the liaison allowed (`.team/run/liaison/messages/t225.md`, `t226.md`). It holds exactly s178, s180, s179, s172. Pull nothing else in, bug fixes included; ask the liaison first.
- Budget: about $60 for the sprint. Last `budget_status` was $1129.36 of $1500, before the sprint's steps. Call `budget_status` once soon. Over $60 of sprint spend: stop starting steps and tell the liaison.
- Stop and tell the liaison at once if a story is quarantined twice, a runner fault needs a pin change, or GitHub rate-limits us. The sprint then ends with what has landed.
- Liaison plan t214: a story that bounces twice more goes to the Product Backlog.
- When sprint 52 ends: `notify_user` kind `sprint-end`, then kind `done`. Start no further sprint.
- Raise the budget only in small steps. Main stays linear. NEVER call `story_status` (over 400k chars); the prompt's hand-over lists stories.
- Tool names are `mcp__team__*`. `run_role` is refused when the story's current step needs another role, so route through `continue_story` notes.
- Put the m228 wording in every `continue_story` note: no role edits another story's tests or code, except a test whose behaviour the story's own design retires, with the R-ids in the handoff's `asserts` field. Nobody edits test_s94 or test_s107.

## Story state
- s178 (REQ ids reserved per story): DONE, landed (merge b3afc69, PR 69).
- s179 (resume keeps worktrees): DONE, landed (merge a5f800d). Its new REQs sit above 192.
- s172 (red story CI with job, step, lines): at land r2, held after a land bounce on the REQ-190..192 and ADR-0090 collision with landed s178. I released it with a note: developer-api rebases only, keeps landed files, renumbers its own new REQs and its ADR to the next free ids, updates references, and renames the old ids in `.team/reviews/s172.md` and `.team/acceptance/s172.md` only if in scope (else lists them), and names the new ids in its handoff. Files: `.team/stories/s172.md`, `.team/reviews/s172.md`, `.team/acceptance/s172.md`, design `agile-team/docs/design/s172.md`.
- s180 (runner commits move the sprint head): BLOCKED by a runner fault (m359 below). Background: the land hit the same REQ/ADR collision. The Manager ruled it a fault on developer-cli with no extra round. I released it with a rebase-and-renumber note, and its ids are now REQ-200..202 and ADR-0092. The story-rebase check then said "team/story-s180-r1's commits are not team/story-s180's commits rebased". It is held at quality r0. Files: `.team/stories/s180.md` (still cites REQ-190..192), `.team/reviews/s180.md`, `.team/acceptance/s180.md`, design `agile-team/docs/design/s180.md`. Quarantine 6dfc6e6 was told to be ignored.

## Pending questions to the liaison (notify_user, no answers yet)
- m359 (s180 blocked): the runner rejects a renumber commit in the story-rebase check. Options offered: (a) the liaison fixes or relaxes the check, then I run the manager on s180 with an `advance` ruling; (b) allow one renumber commit; (c) end sprint 52 with s178 and s179 landed and move s180 and s172 to the Product Backlog. Waiting for the liaison. s172 may hit the same check.
- m357: s180's story file still cites REQ-190..192; does the liaison want `story amend`? Not blocking.
- m355/m356: REQ-190..192 collisions; my rule is that the story that lands later renumbers its own ids. Applied to s179, s172 and s180.
- m353, m354: request_story follow-ups for the Product Backlog (check s159 against s179's REQ-160 change; s159 and s163 against s180's REQ-164 and REQ-169 changes). The runner tells me the story ids when they open. Not in sprint 52.
- m352: runner crash "AttributeError 'NoneType' has no attribute 'data'" at sprint start; no answer seen.

## What I do next
- Read the liaison's answer on m359 first. If (a) or (b) and the fix is in: `run_role` manager on s180 with an `advance` ruling, then `continue_story` with the m228 wording. If (c): `revert_story` or `request_cancel` as fits, end the sprint with what landed.
- `land_bounced` on s172: if it repeats and is the id collision again, check the `friction` and `continue_story` with the renumber note. If s172 hits the same rebase-check fault, tell the liaison in one message and do not retry blindly.
- `story_ci_red` at implement: expected; no action. If it stays red afterwards, ask the liaison for the failing job and step via `notify_user` kind `update`.
- Round cap: `run_role` manager, then `continue_story` with its ruling if "fault ... applied".
- Test-only review findings go to the unit-tester or integration-tester (follow the review's next_role); never to implement. A review that names "tester" makes `run_role` refuse, so route via `continue_story` telling the current-step role to hand off with next_role set to the tester.
- `requirements changed ... affected_done_stories`: `request_story` a follow-up for the Product Backlog.
- On `ci_green` for sprint 52: tell the human once ("PR ready"), then the sprint-end note (list below), then `done`.

## Carried to the sprint-end note (beyond sprint 51's list in m337)
- Manager's sprint-52 proposals: a devops story for the worktree report path and hook access in acceptance steps; a brief note on `/bin/cp` and split bash commands; real-git tests for the git-heavy s179 and s180; a runner gate that checks the files PRESENTATION.md names (and Tooling paths) exist in the workspace; a DevOps pre-check for id collisions.
- Two "tester" hand-backs (s178, s179): the code-reviewer's role file should name unit-tester or integration-tester; `run_role` should accept a tests-owning role on a story sent back for tests.
- story_ci_red fires at implement r0 and names no job or step (s172 fixes this).
- Round-cap hand-over lacks gate reasons and a rounds history. Ops-review hold hand-over gives no reason. crash.log has the oldest entries first. The quarantine hand-over does not list the files in the sha.
- Parallel stories collided on REQ ids (s178 fixed them) and then on ADR numbers (not covered). The architect step should check other open sprint stories' branches for the next free REQ and ADR ids. The pure-rebase story check rejects the renumber edits a collision needs.
- A Manager land-conflict ruling with now_at=implement sends the story back through implement; a land step would be cheaper.
- The story_status output (~400k chars) is too large for a PO step; a compact open-stories summary would cut cost.
- Product Backlog, unscheduled: s169, s170, s171 (onboarding), m284, the follow-up stories above.

## Friction answers to the Manager
- Per step I read only the hand-over and any story_status JSON in the prompt; no event log and no story files unless a ruling needs them. A compact open-stories summary in the brief would replace the large story_status block. The $10.20/step figure was the pre-s25 overcount.
- Routing: follow the review's next_role; test-only findings go to unit-tester/integration-tester, never to implement.
