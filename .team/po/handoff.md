# PO handoff (written 2026-10-23, sprint 52 running)

## Mandate and limits
- Sprint 51 is closed. Its PR #48 was fast-forwarded to main by the liaison.
- Sprint 52 is the one extra sprint the liaison allowed (`.team/run/liaison/messages/t225.md`, `t226.md`). It holds exactly s178 (q31), s180 (q33), s179 (q32) and s172 (q25). Pull nothing else in, bug fixes included; ask the liaison first.
- Budget: about $60 for the sprint. Last `budget_status`: $1129.36 of $1500 (before sprint 52 steps). Over $60 of sprint spend: stop starting new steps and tell the liaison.
- Stop and tell the liaison at once if a story is quarantined twice, a runner fault needs a pin change, or GitHub rate-limits us. The sprint then ends with what has landed.
- Liaison plan t214: a story that bounces twice more goes to the Product Backlog.
- When sprint 52 ends: send a `sprint-end` notify, then `notify_user` kind `done`. Start no further sprint.
- Raise the budget only in small steps. Main stays linear (rebase-merge). Never call `story_status` (over 400k characters).
- Tool names are `mcp__team__*`. `run_role` is refused when the story's current step needs another role, so route through `continue_story` notes instead.
- Put the m228 wording in every `continue_story` note: no role edits another story's tests or code, except a test whose behaviour the story's own design retires, with the R-ids in the handoff's `asserts` field. Nobody edits test_s94 or test_s107.

## Story state at the last hand-over
- s178 (REQ ids reserved per story): landing (land r2). Its review: `.team/run/worktrees/s178/.team/reviews/s178.md` (wiring tests, F1, were sent to the unit-tester through a note).
- s180 (runner commits move the sprint head): implement r1.
- s179 (resume keeps worktrees): implement r1, held. I released it with a note (m228 wording included): the developer-cli fixes the `cli._recover_stories` docstring only, then hands off with next_role integration-tester for `agile-team/runner/tests/e2e/test_s179_resume_e2e.py`. Review: `.team/run/worktrees/s179/.team/reviews/s179.md`.
- s172 (red story CI with job, step, lines): implement r0 after a Manager fault on developer-cli (ruling: build the designed `ci_findings.py` tiers, fix AC2/REQ-191; the unit-tester then adds the D5 tests). Story: `.team/stories/s172.md`.

## Pending questions to the liaison (notify_user updates, no ids needed)
- m355/m356: REQ-190 to REQ-192 were added by both s179 and s180 with different content. My standing rule: the second story to land renumbers its own new ids. The liaison may name a different owner. Not answered yet.
- m353 and m354: request_story follow-ups for the Product Backlog. They check s159 against s179's REQ-160 change, and s159 and s163 against s180's REQ-164 and REQ-169 changes. The runner tells me the story ids when it opens them. Not in sprint 52.
- m352: the runner crash "AttributeError 'NoneType' has no attribute 'data'" at the sprint start. No answer seen; the runner resumed by itself.

## What I do on the next hand-overs
- Red story CI (`story_ci_red`) at implement r0 or r1: expected until the code lands; take no action. If it stays red after implement, ask the liaison for the failing job and step with `notify_user` kind `update`.
- Round cap: `run_role` the manager, then `continue_story` with its ruling (if it returns "fault ... applied"). Test-only review findings go to the unit-tester or integration-tester. A review that names "tester" makes `run_role` refuse; route through `continue_story` with a note telling the current-step role to hand off with next_role set to the tester.
- Docs outside the developer's scope: name the doc update in the handoff with next_role scribe (architect if the scribe's scope doesn't cover the path).
- `requirements changed ... affected_done_stories`: `request_story` a follow-up for the Product Backlog.
- On `ci_green` for sprint 52: tell the human once ("PR ready"), then the sprint-end note (carry the list below), then `done`.

## Carried to the sprint-end note (beyond sprint 51's list in m337)
- The Manager's sprint-52 proposals: a devops story for worktree report path and hook access in acceptance steps; a brief note on `/bin/cp` and split bash commands; real-git tests for the git-heavy s179 and s180.
- Two "tester" hand-backs (s178, s179): the code-reviewer's role file should name unit-tester or integration-tester; `run_role` should accept a tests-owning role on a story sent back for tests.
- The story_ci_red hand-over fires at implement r0 and names no job or step (s172 fixes the job and step part).
- The round-cap hand-over lacks gate reasons and a rounds history. The ops-review hold hand-over gives no reason. crash.log has the oldest entries first.
- The architect step should check the other open sprint stories' branches for the next free REQ id (the s179 and s180 collision, until s178 lands).
- Product Backlog and unscheduled: s169, s170, s171 (onboarding), m284, the follow-up stories above.
