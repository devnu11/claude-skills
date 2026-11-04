# PO handoff (sprint 55, in progress)

## State
- Sprint 55 scope: s180 (design/ops-review, released) and s185 (acceptance, released). Nothing joins it. Do not call start_sprint until both are done and landed.
- s180: manager changed REQ-164/169/171, added REQ-234..237. I asked the liaison (m398) for a follow-up story checking done stories s159 and s163 against those. Liaison t255: it will file it to the Product Backlog AFTER sprint 55 ends (a story commit now would move the sprint head). Don't wait for it. The refused push was an old origin/team/story-s180, now removed.
- s185: the human answered m399: AC3 has no clash, no amend, no code change. A commit main lacks in any form refuses; a patch-equivalent copy on main is no obstacle. The e2e test pins that. Released at acceptance with a note.
- A manager commit 9a325e9 was quarantined (out-of-scope changes). I ignored it. Stop condition "quarantined twice" (t237): if it happens again, tell the liaison.

## Open decisions / pending questions
- None waiting on the human. No open ask_user ids (m399 answered).

## Next (from liaison t254, replaces earlier "start no sprint 56")
1. When s180 and s185 are done and landed, and the sprint boundary has closed: start Sprint 56, the runner sprint: s188, s190, s189, s187, s173, s177, in that order. s173 and s177 build on s180: if s180 goes back to the Product Backlog, leave those two out and tell the liaison.
2. Then Sprint 57, onboarding: s169, s170, s171, in that order.
3. Limits per sprint: about $60, $75 hard stop. Stop conditions unchanged (quarantined twice, a pin change, GitHub rate limit, a rebase step bouncing twice).
4. Time: job deadline 2026-11-05 08:00 CDT; the 07:00 cut applies to the running sprint. Start no new sprint after 05:00: notify `done` instead.
5. More stories will arrive in the Product Backlog after sprint 55 (amended s36, onboarding part D, two small ones, the m398 follow-up). Don't plan around them until the runner announces their ids.
6. When sprint 57 ends: notify_user `done` once, start no sprint 58.
- Call a PR ready only on `ci_green`. Sprint is done only with green CI present.
- Budget: raise only in small steps. Check budget_status at sprint start.

## Routing rules
- A review needing real git goes to the integration-tester. Findings naming only test files go to the unit-tester or integration-tester, not implement. For a non-role owner, ask the manager for a ruling, make ruling and fault agree on one next step, then continue_story with a note listing the findings.
- Changing an AC is the human's call: ask_user, then the liaison sends `story amend`.
- Do not call story_status: its output is over 650,000 characters. Rely on hand-over lines.

## Artifacts
- Stories: .team/stories/ (s180, s185, s187-s190, s173, s177, s169-s171).
- Designs: agile-team/docs/design/. Sprint story reviews: .team/run/worktrees/<id>/.team/reviews/. Acceptance: .team/acceptance/.
- Liaison messages: .team/run/liaison/messages/t254.md (plan), t255.md (s180).

## Manager's questions (answered in friction)
- At each step I read story_status and the liaison message notes. story_status is the cost; a compact brief summary of the current sprint's stories, open questions, boundary state and budget would replace it. $10.20/step is the pre-s25 overcount.
- Routing rules for s152 and s179 are noted above.
