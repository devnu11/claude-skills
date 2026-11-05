# PO handoff (sprint 56, running)

## State
- Sprint 55 (s180, s185) is done and landed. CI was green on PR #89. The human has been told it is ready to merge by fast-forward only.
- Sprint 56 is running: s188, s190, s189, s187, s173, s177, in that order. Goal: runner fixes. All six are at design.
- s177 crashed at design ("branch team/story-s177 already exists", left over from its sprint 54 revert). The liaison deleted the branch (t256) and I released it with continue_story. s190 fixes that bug.
- s173 and s177 build on s180, which has landed. If either goes back to the Product Backlog, tell the liaison.
- Budget at the last check: $237.66 remaining of $1500 (84.2% used). Raise only in small steps. Limits per sprint: about $60, $75 hard stop.

## Open decisions / pending questions
- No ask_user ids are open.
- Known failure at the sprint 56 start: tests/test_s164_idle_tick.py::test_own_lines_land_before_the_wait_w2. I asked the liaison for a story (request_story m406). The liaison (t256) says it will write a story only if the test keeps failing, and the sprint is not held for it. If the runner announces a story id for it, schedule it with add_to_sprint.
- Liaison story requests m400 and m401 are still pending; the runner will announce the story ids. Do not plan around them until then.
  - m400: docs-only fixes to the s180 design (add CARRY_NO_BASE as a refusal in C2; rename adopt_carry to apply_carry).
  - m401: the gate command timeout (300 s is too short for the three chained suites; a timed-out gate should name the slowest test).
- Liaison t255: a follow-up story checking done stories s159 and s163 against the REQ-164/169/171 and REQ-234..237 changes will go to the Product Backlog after sprint 56 ends.
- Stop condition "quarantined twice" (t237): a manager commit 9a325e9 was quarantined once and ignored. If it happens again, tell the liaison.
- Decision made by me, not the human: for "checked by hand" ACs in a live landing, the customer-proxy's judgement from the captured real-git e2e is the accepted evidence (as for s185).

## Next (liaison plan t254)
1. Let sprint 56 run. Handle the hand-overs the runner raises.
2. When sprint 56 is done and its boundary has closed (call a PR ready only on ci_green): start Sprint 57, onboarding: s169, s170, s171, in that order.
3. Stop conditions: quarantined twice, a pin change, GitHub rate limit, a rebase step bouncing twice.
4. Time: job deadline 2026-11-05 08:00 CDT; the 07:00 cut applies to the running sprint. Start no new sprint after 05:00: notify `done` instead.
5. More stories will arrive in the Product Backlog (amended s36, onboarding part D, two small ones, the m398 follow-up, m400, m401). Do not plan around them until the runner announces their ids.
6. When sprint 57 ends: notify_user `done` once and start no sprint 58.

## Routing rules
- run_role is refused unless the role is the story's current step role. A developer's request for an architect docs change has no route mid-pipeline; put it in the continue note for the architect's next step, or ask the liaison for a story.
- Follow a review's next_role. A review needing real git goes to the integration-tester. Findings that name only test files go to the unit-tester or integration-tester, never to implement (this cost about 3 steps on s179; s152 F1 needed real-git tests, so integration-tester).
- For a non-role owner or a round cap, run the manager with a brief that names the latest gate event and the review path, make ruling and fault agree on one next step, then continue_story with a note.
- A land conflict is an ordinary rebase for developer-cli; a gate timeout is not a reason to bounce to implement.
- Changing an AC is the human's call: ask_user, then the liaison sends `story amend`.
- The sprint start is refused while the previous end boundary is pending; wait for the hand-over.
- Do not call story_status: its output is over 650,000 characters. Rely on hand-over lines and budget_status.

## Artifacts
- Stories: .team/stories/ (s188, s190, s189, s187, s173, s177 in sprint 56; s169, s170, s171 for sprint 57).
- Designs: agile-team/docs/design/ (s180.md for the carry work). Sprint story reviews: .team/run/worktrees/<id>/.team/reviews/. Acceptance: .team/acceptance/.
- Liaison messages: .team/run/liaison/messages/t254.md (plan), t255.md (s180), t256.md (s177 branch, s164 failure).
