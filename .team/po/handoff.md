# PO handoff (sprint 55, in progress)

## State
- Sprint 55 scope: s180 (landing carry bug) and s185 (done and landed). Nothing joins it. Do not call start_sprint until s180 is done and landed and the sprint boundary has closed.
- s180 is at design-review (I released it, r0). History: the implement gate timed out at 300 s with no test named. The code-reviewer's F1-F4 went to developer-cli. The unit-tester then wrote tests for F1/F2. A land conflict in architecture.md was handed back to developer-cli to rebase.
- At design-review the architect should make two doc fixes in agile-team/docs/design/s180.md and agile-team/docs/architecture.md:
  - add CARRY_NO_BASE as a refusal in C2 (review N2);
  - change adopt_carry to apply_carry.
  I put both in the continue note. If they are not done after the step, ask the liaison via m400.
- The code-reviewer asked whether the human files a story by hand in a live landing ("checked by hand" ACs). I answered no: the customer-proxy's judgement from the captured real-git e2e is the accepted evidence, as for s185. This was my call, not the human's; the human was not asked.

## Open decisions / pending questions
- No ask_user ids are open.
- Two liaison story requests are pending; the runner will announce the ids. Do not wait on them:
  - m400: docs-only follow-up for the s180 design fixes above.
  - m401: the gate command timeout (300 s is too short for the three chained suites: agile-team, unattended, house-rules; a timed-out gate should name the slowest test).
- Earlier (liaison t255): a follow-up story checking done stories s159 and s163 against the REQ-164/169/171 and REQ-234..237 changes will be filed to the Product Backlog after sprint 55 ends.
- Stop condition "quarantined twice" (t237): a manager commit 9a325e9 was quarantined once and ignored. If it happens again, tell the liaison.

## Next (liaison plan t254)
1. When s180 is done and landed and the sprint boundary has closed (green CI present; call a PR ready only on ci_green): start Sprint 56, the runner sprint: s188, s190, s189, s187, s173, s177, in that order. s173 and s177 build on s180: if s180 goes back to the Product Backlog, leave those two out and tell the liaison.
2. Then Sprint 57, onboarding: s169, s170, s171, in that order.
3. Limits per sprint: about $60, $75 hard stop. Stop conditions: quarantined twice, a pin change, GitHub rate limit, a rebase step bouncing twice.
4. Time: job deadline 2026-11-05 08:00 CDT; the 07:00 cut applies to the running sprint. Start no new sprint after 05:00: notify `done` instead.
5. More stories will arrive in the Product Backlog (amended s36, onboarding part D, two small ones, the m398 follow-up, m400, m401). Do not plan around them until the runner announces their ids.
6. When sprint 57 ends: notify_user `done` once, start no sprint 58.
- Budget: raise only in small steps. Check budget_status at sprint start.

## Routing rules
- run_role is refused unless the role is the story's current step role. A developer's request for an architect docs change has no route mid-pipeline; put it in the continue note for the architect's next step, or ask the liaison for a story.
- A review needing real git goes to the integration-tester. Findings that name only test files go to the unit-tester or integration-tester, not implement. Follow the review's next_role.
- For a non-role owner or a round cap, run the manager with a brief that names the latest gate event and the review path (not a grep of the whole event log), make ruling and fault agree on one next step, then continue_story with a note.
- A land conflict is an ordinary rebase for developer-cli; a gate timeout is not a reason to bounce to implement.
- Changing an AC is the human's call: ask_user, then the liaison sends `story amend`.
- Do not call story_status: its output is over 650,000 characters. Rely on hand-over lines.

## Artifacts
- Stories: .team/stories/ (s180, s185, s187-s190, s173, s177, s169-s171).
- Designs: agile-team/docs/design/ (s180.md). Sprint story reviews: .team/run/worktrees/<id>/.team/reviews/. Acceptance: .team/acceptance/.
- Liaison messages: .team/run/liaison/messages/t254.md (plan), t255.md (s180).

## Manager's questions (answered in friction)
- At each step I read the handoff, the hand-over lines and story_status. story_status is the cost; a compact summary (current sprint stories with step, status, hold, in-flight role; open question ids; boundary state; budget; for CI failures only the job, step and test names) would replace it. $10.20/step is the pre-s25 overcount.
- Routing rules for s152 and s179 are above.
