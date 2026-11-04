# PO handoff (sprint 55, just started)

## State
- Sprint 55 goal: fix s180 (runner's own commits move the sprint head and drop pushed landings; fresh design from main, architect allocates new REQ/ADR ids; branch liaison/s180-r1-kept is reference only) and s185 (s159 follow-up per REQ-160 with the resume rules of REQ-193/194).
- Scope: s180 and s185 ONLY. Pull nothing else in. q40-q43 and s187-s190 are Product Backlog stories and do not join. The last sprint of this run: when it ends, notify_user kind `done` once and start no sprint 56.
- Sprint 54 is closed (PR #82 on main at 14c30be9; the liaison closed its end boundary by hand on 10-26). Don't replay it or call continue_boundary for it. Sprint 55's start boundary should bring in main's one newer commit (render-markdown test fix).
- Runner pin: 76eacf9.
- start_sprint(55) succeeded; the runner runs the manager next.

## Limits (liaison t249, today 2026-11-04)
- About $60 for the sprint, $75 hard stop, counted from the sprint start (budget at start: $1239.25 spent of $1500). Raise the budget only in small steps if ever needed.
- Job deadline 2026-11-05 08:00 CDT. Any story not at `land` by 07:00 that day goes back to the Product Backlog.
- Stop conditions (t237): quarantined twice, a pin change, a GitHub rate limit, a rebase step bouncing twice; plus (t248) a second action against a liaison tell. When one hits, tell the liaison.

## Open decisions / pending questions
- None waiting on the human. No pending ask_user ids. m391 (sprint 54 boundary loop) was resolved by the liaison.

## Next
- Handle runner hand-overs for s180 and s185.
- Routing rules: real-git reviews go to the integration-tester (s152); findings naming only test files go to the unit-tester or integration-tester, not implement (s179). When a reviewer names a non-role owner, ask the manager for a ruling and then continue_story with a note listing the findings.
- A "Sprint Backlog stuck" hand-over: act on the named story (release_story/continue_story, run_role); 3 with no action sets the run blocked.
- Only call a PR ready on `ci_green`. A CI failure becomes a request_story bug, not a retry.
- Don't call story_status: its output is over 650,000 characters.

## Artifacts
- Liaison messages: .team/run/liaison/messages/t248.md, t249.md.
- Stories: .team/stories/ (s180, s185). Designs: agile-team/docs/design/. Reviews: .team/run/worktrees/<id>/.team/reviews/. Acceptance: .team/acceptance/.
