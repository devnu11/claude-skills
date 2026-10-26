# PO handoff (sprint 54, in progress)

## State
- Sprint 54 goal: fix runner bugs found in sprints 52 and 53.
- Scope: s182, s183, s184, s186. s180 stays PO-HELD in sprint 54 (liaison t246/t247 choice b): it can't be reverted (no commits); the liaison will stop the run, move it out by hand and remove the leftover local team/story-s180 branch. Do NOT call start_sprint or revert s180. s177 was reverted to the Product Backlog (waits for the human, m284).
- s183, s184, s186: done (landed).
- s182: at land, round 2. Landing hit a merge conflict in agile-team/docs/architecture.md (land_bounced). I called continue_story with a note: developer-cli rebases team/story-s182 onto the sprint head (3e27f67), keeps both sides' architecture.md lines, no squash or reorder. Land then runs again. Earlier it was at e2e r3; its review is .team/run/worktrees/s182/.team/reviews/s182.md.
- A "Sprint Backlog stuck" hand-over (1 of 3) came before my continue_story. If it comes again with s182 still held, act on s182 (release_story/continue_story, or run_role developer-cli) rather than ignoring it. After 3 stuck hand-overs with no action the run is set blocked.
- Budget at session start about $292 of $1500 left. Raise only in small steps.

## Open decisions / pending questions
- None waiting on the human. No pending ask_user ids.

## Next
- Handle runner hand-overs. Limits from t246: about $60 for the sprint, $75 hard stop. A story not at `land` by 07:30 on 10-26 goes to the Product Backlog. Job deadline 09:00. Stop conditions (t237): quarantined twice, a pin change, a GitHub rate limit, a rebase step bouncing twice (a second s182 land bounce is a stop condition: tell the liaison).
- When s182 has landed (s183, s184, s186 already have): notify_user kind `done` once, then tell the liaison. Do not start sprint 55 even if the hand-over asks for one. Do not call a PR ready except on `ci_green`.
- Routing rules: a review needing real git goes to the integration-tester (s152); findings naming only test files go to the unit-tester or integration-tester, not implement (s179). When a reviewer names a non-role owner, the runner puts the story at implement and run_role is refused: ask the manager for a ruling, make sure its ruling and fault agree on one next step, then continue_story with a note listing the findings.
- Do not call story_status: its output is over 650,000 characters. Rely on the hand-over lines.

## Artifacts
- Stories: .team/stories/ (s182, s183, s184, s186, s180, s177).
- Designs: agile-team/docs/design/. Reviews of sprint stories: .team/run/worktrees/<id>/.team/reviews/. Acceptance: .team/acceptance/.
- Liaison messages: .team/run/liaison/messages/t246.md, t247.md.
