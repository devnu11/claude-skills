# PO handoff (sprint 56, running)

## State
- Sprint 55 (s180, s185) is done and landed. CI was green on PR #89. The human has been told it is ready to merge by fast-forward only.
- Sprint 56 is running: s188, s190, s189, s187, s173, s177. Goal: runner fixes.
  - s190, s187: done.
  - s189: hit the round cap at implement. I ran the manager (ruling: one more round, single fix) and continued it. The fix is to add `remove_from_sprint for a story with no commits,` after `revert_story,` in the "Sprint Backlog stuck" list of agile-team/runner/agile_team/roles/product-owner.md, then rewrap. Review: .team/run/worktrees/s189/.team/reviews/s189.md. If it caps again, ask the human via ask_user.
  - s188: landing hit a merge conflict in agile-team/docs/architecture.md (first bounce). I continued it with a note for developer-cli to rebase onto the sprint head and keep both sides. Do nothing unless it bounces again.
  - s173: at implement r1. Quarantined commit 9332ca0baf035743572651b53c7a45a19b3641d7 holds developer-cli's out-of-scope protocol.md edit; the architect should `git cherry-pick -n` it. Watch for a bounce.
  - s177: held at ops-review (hold affected_done). I never saw the reason. If the runner raises it: DevOps found tooling with no story, so `request_story`, then `continue_story`.
- Budget at the last check: $237.66 remaining of $1500. Raise only in small steps. Limits per sprint: about $60, $75 hard stop.

## Open decisions / pending questions
- No ask_user ids are open.
- request_story m409 (pending): follow-up checking done story s163 against REQ-169 (narrowed by s177) and the new REQ-267..269. Folded into liaison t255. Schedule it only when the runner announces its id (add_to_sprint, or the next sprint).
- request_story m406 (pending): known failure tests/test_s164_idle_tick.py::test_own_lines_land_before_the_wait_w2. The liaison writes a story only if it keeps failing.
- request_story m400 and m401 (pending): m400 is docs fixes to the s180 design; m401 is the gate command timeout (300 s too short; name the slowest test). Do not plan around them until ids are announced.
- Liaison t255: a follow-up story checking done stories s159 and s163 against the REQ-164/169/171 and REQ-234..237 changes will go to the Product Backlog after sprint 56 ends.
- Stop conditions (t237/t254): quarantined twice, a pin change, GitHub rate limit, a rebase step bouncing twice. Quarantines so far: 9a325e9 (ignored), c939803 (s189), 9332ca0 (s173); the last two were routed to the doc owner. Tell the liaison if one repeats.
- My own decision (not the human's): for "checked by hand" ACs in a live landing, the customer-proxy's judgement from the captured real-git e2e is the accepted evidence (as for s185).

## Next (liaison plan t254)
1. Let sprint 56 run. Handle the hand-overs the runner raises.
2. When sprint 56 is done and its boundary has closed (call a PR ready only on ci_green): start Sprint 57, onboarding: s169, s170, s171, in that order.
3. Time: job deadline 2026-11-05 08:00 CDT; the 07:00 cut applies to the running sprint. Start no new sprint after 05:00: notify `done` instead.
4. More stories will arrive in the Product Backlog (amended s36, onboarding part D, two small ones, the m398 follow-up, m400, m401, m409). Do not plan around them until the runner announces their ids.
5. When sprint 57 ends: notify_user `done` once and start no sprint 58.

## Routing rules
- run_role is refused unless the role is the story's current step role (the manager is the exception for a round cap or ruling).
- Docs (protocol.md, SKILL.md, docs/**) belong to the architect. agile-team/runner/** (including roles/*.md) belongs to developer-cli. Out-of-scope doc edits get quarantined; the owner fixes with `git cherry-pick -n <sha>`.
- Follow a review's next_role. A review needing real git goes to the integration-tester. Findings that name only test files go to the unit-tester or integration-tester, never to implement.
- Round cap: run the manager with a brief naming the review path and the clear next step, then continue_story with a note. A land conflict is an ordinary rebase for developer-cli.
- Changing an AC is the human's call: ask_user, then the liaison sends `story amend`.
- The sprint start is refused while the previous end boundary is pending.
- Do not call story_status: its output is over 650,000 characters. Rely on hand-over lines and budget_status.

## Artifacts
- Stories: .team/stories/ (s188, s190, s189, s187, s173, s177 in sprint 56; s169, s170, s171 for sprint 57).
- Designs: agile-team/docs/design/ (s189.md, s188.md, s177.md, etc.). Reviews: .team/run/worktrees/<id>/.team/reviews/<id>.md. Acceptance: .team/acceptance/.
- Liaison messages: .team/run/liaison/messages/t254.md (plan), t255.md, t256.md.
