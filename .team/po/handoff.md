# PO handoff (sprint 54, in progress)

## State
- Sprint 54 goal: fix runner bugs found in sprints 52 and 53.
- Scope after the liaison's trim (messages t246, t247): s182, s183, s184, s186. s180 stays HELD in sprint 54 by the liaison's choice (b): it can't be reverted (no commits); the liaison will stop the run, move it out by hand and remove the leftover local team/story-s180 branch. Do NOT call start_sprint or revert s180.
- s177 was reverted to the Product Backlog (waits for the human, m284).
- Last seen: s183 land, s186 land, s184 implement r2 (CI red on cli.py `_prepared` 13 statements > 12, briefed to split it), s182 implement r1 (released with a note: F1 to the developer, F4 to the unit-tester, F2/F3 to the integration-tester; review at .team/run/worktrees/s182/.team/reviews/s182.md).
- Budget at the start of this session: about $292 left of $1500. Raise only in small steps.

## Open decisions
- None waiting on the human. No pending ask_user ids. notify_user m386 (about s180) is answered by t247.

## Next
- Handle runner hand-overs. For red story CI: continue_story(story, note) with the failing lines. For a review that names a non-role (e.g. "tester"): read the review, split findings by owner and continue_story.
- Limits from t246: about $60 for the sprint, $75 hard stop. A story not at `land` by 07:30 on 10-26 goes to the Product Backlog. Job deadline 09:00. Stop conditions are t237's: quarantined twice, a pin change, a GitHub rate limit, a rebase step bouncing twice.
- When s182, s183, s184 and s186 have all landed: notify_user kind `done` once, then tell the liaison. Do not start sprint 55 even if the hand-over asks for one. Do not call a PR ready except on `ci_green`.
- Routing rules from the Manager: a review needing real git goes to the integration-tester (s152); a review whose findings name only test files goes to the unit-tester or integration-tester, not implement (s179).

## Artifacts
- Stories: .team/stories/ (s182, s183, s184, s186, s180, s177).
- Designs: agile-team/docs/design/. Reviews: .team/reviews/ (sprint stories' reviews are in their worktrees under .team/run/worktrees/<id>/). Acceptance: .team/acceptance/.
- Liaison messages: .team/run/liaison/messages/t246.md, t247.md.
