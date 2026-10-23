# PO handoff (written 2026-10-23, sprint 52 running)

## Mandate and limits
- Sprint 51 closed (PR #48 fast-forwarded by the liaison). Sprint 52 is the one extra sprint the liaison allowed (`.team/run/liaison/messages/t225.md`, `t226.md`). It holds exactly s178, s180, s179, s172. Pull nothing else in, bug fixes included; ask the liaison first.
- Budget: about $60 for the sprint. Last `budget_status`: $1129.36 of $1500 (before sprint 52 steps). Over $60 of sprint spend: stop starting new steps and tell the liaison. Check `budget_status` once soon.
- Stop and tell the liaison at once if a story is quarantined twice, a runner fault needs a pin change, or GitHub rate-limits us. The sprint then ends with what has landed.
- Liaison plan t214: a story that bounces twice more goes to the Product Backlog.
- When sprint 52 ends: `notify_user` kind `sprint-end`, then kind `done`. Start no further sprint.
- Raise the budget only in small steps. Main stays linear (rebase-merge). NEVER call `story_status` (over 400k chars); the prompt's hand-over already lists stories.
- Tool names are `mcp__team__*`. `run_role` is refused when the story's current step needs another role, so route through `continue_story` notes.
- Put the m228 wording in every `continue_story` note: no role edits another story's tests or code, except a test whose behaviour the story's own design retires, with the R-ids in the handoff's `asserts` field. Nobody edits test_s94 or test_s107.

## Story state at the last hand-over
- s178 (REQ ids reserved per story): DONE, landed (merge b3afc69, PR 69). Review `.team/reviews/s178.md`.
- s179 (resume keeps worktrees): at `land` r1, held. The landing hit a merge conflict (architecture.md, REQ-190..192 collide with landed s178). I released it with a note: developer-cli keeps s178's files, renumbers s179's new REQs above 192, updates all references, rebases only, and names the new ids in its handoff so s180 avoids them. Earlier: round cap at e2e was ruled by the Manager as an integration-tester fault (presentation missing the e2e test/unit tests/design.md); fixed. Files: `.team/stories/s179.md`, `.team/reviews/s179.md`, `.team/acceptance/s179.md`, design `agile-team/docs/design/s179.md`.
- s180 (runner commits move the sprint head): e2e r2 (integration-tester writing `agile-team/runner/tests/e2e/test_s180_carry_e2e.py`, review F2; the design's drop_moved helper also not implemented, minor). It also added REQ-190..192, so it WILL conflict on landing after s178/s179: it must renumber its own new ids (above s179's new ids). Files: `.team/stories/s180.md`, `.team/reviews/s180.md`, design `agile-team/docs/design/s180.md`.
- s172 (red story CI with job, step, lines): at design-review/review r1 (code-reviewer on D1-D5 fixes; tester added `test_ci_findings.py`). Story `.team/stories/s172.md`, review `.team/reviews/s172.md`, design `agile-team/docs/design/s172.md`. It also lists REQ-190..192 in its files, so it may need the same renumbering at landing.

## Pending questions to the liaison (notify_user updates, no ids)
- m355/m356: REQ-190..192 were added by s179 and s180 with different content (and s172 lists them). My standing rule: the story that lands after s178 renumbers its own new ids; applied to s179 now. The liaison may name a different owner. Not answered.
- m353, m354: request_story follow-ups for the Product Backlog (check s159 against s179's REQ-160 change; s159 and s163 against s180's REQ-164 and REQ-169 changes). The runner tells me the story ids when opened. Not in sprint 52.
- m352: runner crash "AttributeError 'NoneType' has no attribute 'data'" at sprint start; no answer seen; the runner resumed by itself.

## What I do on the next hand-overs
- `land_bounced` (merge conflict): developer-cli rebases. If it repeats on the same story, check whether it's the REQ id collision; if so, `continue_story` with the renumber note (as for s179). Do the same for s180 and s172 when they conflict.
- `story_ci_red` at implement r0/r1: expected; no action. If it stays red after implement, ask the liaison for the failing job/step via `notify_user` kind `update`.
- Round cap: `run_role` manager, then `continue_story` with its ruling if "fault ... applied". Test-only review findings go to the unit-tester or integration-tester (follow the review's next_role); a review that names "tester" makes `run_role` refuse, so route via `continue_story` telling the current-step role to hand off with next_role set to the tester. Never route test-only findings to implement.
- Docs outside the developer's scope: name the doc update in the handoff with next_role scribe (architect if the scribe's scope doesn't cover the path).
- `requirements changed ... affected_done_stories`: `request_story` a follow-up for the Product Backlog.
- On `ci_green` for sprint 52: tell the human once ("PR ready"), then the sprint-end note (carry the list below), then `done`.

## Carried to the sprint-end note (beyond sprint 51's list in m337)
- Manager's sprint-52 proposals: a devops story for worktree report path and hook access in acceptance steps; a brief note on `/bin/cp` and split bash commands; real-git tests for the git-heavy s179 and s180; a runner gate that checks the files PRESENTATION.md names (and Tooling paths) exist in the workspace.
- Two "tester" hand-backs (s178, s179): the code-reviewer's role file should name unit-tester or integration-tester; `run_role` should accept a tests-owning role on a story sent back for tests.
- story_ci_red fires at implement r0 and names no job or step (s172 fixes this).
- Round-cap hand-over lacks gate reasons and a rounds history. Ops-review hold hand-over gives no reason. crash.log has the oldest entries first.
- The architect step should check the other open sprint stories' branches for the next free REQ id (the s179/s180/s172 collision with s178).
- The story_status tool output (~400k chars) is far too large for a PO step; a compact open-stories summary would cut cost.
- Product Backlog, unscheduled: s169, s170, s171 (onboarding), m284, the follow-up stories above.

## Friction answers to the Manager (also give in the next handoff if asked again)
- Per step I read only the hand-over and any story_status JSON in the prompt; no event log, no story files unless a ruling needs them. A compact open-stories summary in the brief would replace the large story_status block. The $10.20/step figure was the pre-s25 overcount.
- Routing: follow the review's next_role; test-only findings go to unit-tester/integration-tester, never to implement.
