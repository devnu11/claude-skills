# PO handoff (sprint 54, in progress)

## State
- Sprint 54 goal: fix runner bugs found in sprints 52 and 53.
- Scope: s182, s183, s184, s186. s180 stays HELD in sprint 54 (liaison t246/t247 choice b): it can't be reverted (no commits); the liaison will stop the run, move it out by hand and remove the leftover local team/story-s180 branch. Do NOT call start_sprint or revert s180. s177 was reverted to the Product Backlog (waits for the human, m284).
- s183: done (landed).
- s186: at land (r2, CI green earlier; was at e2e r2 last seen).
- s184: released at design (manager ruling was revise_design: architect fixes non-blocking F6 design drift, NEXT_SPRINT_ADVICE block), then the unit-tester must fix F4 and F5 in agile-team/runner/tests/test_s184_held_done.py (assert status is RunStatus.DONE; replace boolean `resume` in start_of with cli.StartMode, add a StartMode.WORK case). Production code is approved. Review: .team/run/worktrees/s184/.team/reviews/s184.md.
- s182: at e2e r3, released with a note: integration-tester writes ALL open test gaps in one pass (F1a False branch of is_tip_replayed, F1c two tests asserting impossible "made by the runner" states, F2 real-git AC1/AC2, F3 renumber, F4 dispatch-level advance refusal). Review: .team/run/worktrees/s182/.team/reviews/s182.md. If the tester again leaves F2-F4 unwritten, request_cancel (manager says feasible by 07:30 only if written this pass).
- Budget at session start about $292 of $1500 left. Raise only in small steps.

## Open decisions / pending questions
- None waiting on the human. No pending ask_user ids.

## Next
- Handle runner hand-overs. Limits from t246: about $60 for the sprint, $75 hard stop. A story not at `land` by 07:30 on 10-26 goes to the Product Backlog. Job deadline 09:00. Stop conditions (t237): quarantined twice, a pin change, a GitHub rate limit, a rebase step bouncing twice.
- When s182, s183, s184 and s186 have all landed: notify_user kind `done` once, then tell the liaison. Do not start sprint 55 even if the hand-over asks for one. Do not call a PR ready except on `ci_green`.
- Routing rules: a review needing real git goes to the integration-tester (s152); findings naming only test files go to the unit-tester or integration-tester, not implement (s179). When a reviewer names a non-role owner (e.g. "tester"), the runner puts the story at implement and run_role is refused: ask the manager for a ruling, make sure its ruling and fault agree on one next step, then continue_story with a note listing the findings.
- Do not call story_status: its output is over 650,000 characters. Rely on the hand-over lines.

## Artifacts
- Stories: .team/stories/ (s182, s183, s184, s186, s180, s177).
- Designs: agile-team/docs/design/. Reviews of sprint stories: .team/run/worktrees/<id>/.team/reviews/. Acceptance: .team/acceptance/.
- Liaison messages: .team/run/liaison/messages/t246.md, t247.md.
