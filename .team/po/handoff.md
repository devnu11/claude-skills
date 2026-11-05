# PO handoff (sprint 56, running)

## State
- Sprint 55 (s180, s185) is done and landed. CI was green on PR #89. The human has been told it is ready to merge by fast-forward only.
- Sprint 56 is running: s188, s190, s189, s187, s173, s177. Goal: runner fixes.
  - s190 is done.
  - s187 is at land.
  - s189 is at review, round 2.
  - s188 is at implement after a manager fault. The unit-tester fixes the `at_tail` fixture first, then developer-cli removes the dead `if not results:` branch in `_finish_green` and rewraps SKILL.md.
  - s173 is held at quality. Quarantined commit 9332ca0baf035743572651b53c7a45a19b3641d7 holds developer-cli's out-of-scope `protocol.md` rebase resolution. I continued it with a note telling the doc owner (architect) to reuse it. Watch for a bounce.
  - s177 is held at ops-review. I never found the reason (the hold text was not visible to me). If the runner raises it, act on it. A likely cause is DevOps finding tooling with no story yet: then `request_story`, `continue_story`.
- Budget at the last check: $237.66 remaining of $1500. Raise only in small steps. Limits per sprint: about $60, $75 hard stop.

## Open decisions / pending questions
- No ask_user ids are open.
- request_story m409 (pending): follow-up checking done story s163 against REQ-169 (narrowed by s177) and the new REQ-267..269. I asked the liaison to fold it into the pending s159/s163 follow-up (liaison t255). Schedule it with add_to_sprint or the next sprint only when the runner announces its id.
- request_story m406 (pending): known failure at the sprint 56 start, tests/test_s164_idle_tick.py::test_own_lines_land_before_the_wait_w2. The liaison writes a story only if it keeps failing. If an id is announced, add_to_sprint.
- request_story m400 and m401 (pending): m400 is docs fixes to the s180 design; m401 is the gate command timeout (300 s too short; a timed-out gate should name the slowest test). Do not plan around them until ids are announced.
- Liaison t255: a follow-up story checking done stories s159 and s163 against the REQ-164/169/171 and REQ-234..237 changes will go to the Product Backlog after sprint 56 ends.
- Stop condition "quarantined twice" (t237): a manager commit 9a325e9 was quarantined once and ignored. Quarantines have since hit s189 (c939803) and s173 (9332ca0); both were routed to the doc owner. If a rebase or quarantine problem repeats, tell the liaison.
- Decision made by me, not the human: for "checked by hand" ACs in a live landing, the customer-proxy's judgement from the captured real-git e2e is the accepted evidence (as for s185).

## Next (liaison plan t254)
1. Let sprint 56 run. Handle the hand-overs the runner raises.
2. When sprint 56 is done and its boundary has closed (call a PR ready only on ci_green): start Sprint 57, onboarding: s169, s170, s171, in that order.
3. Stop conditions: quarantined twice, a pin change, GitHub rate limit, a rebase step bouncing twice.
4. Time: job deadline 2026-11-05 08:00 CDT; the 07:00 cut applies to the running sprint. Start no new sprint after 05:00: notify `done` instead.
5. More stories will arrive in the Product Backlog (amended s36, onboarding part D, two small ones, the m398 follow-up, m400, m401, m409). Do not plan around them until the runner announces their ids.
6. When sprint 57 ends: notify_user `done` once and start no sprint 58.

## Routing rules
- run_role is refused unless the role is the story's current step role (the manager is the exception for a round cap or ruling). A role's request for a change outside its write scope has no route mid-pipeline. Put it in the continue note for the role that owns the file.
- Docs (protocol.md, SKILL.md, docs/**) belong to the architect. agile-team/runner/** (including roles/*.md) belongs to developer-cli. A developer's out-of-scope doc edits get quarantined; the fix is `git cherry-pick -n <sha>` by the owner.
- Follow a review's next_role. A review needing real git goes to the integration-tester. Findings that name only test files go to the unit-tester or integration-tester, never to implement.
- For a round cap, run the manager with a brief that names the review path and the clear next step, then continue_story with a note. A land conflict is an ordinary rebase for developer-cli; the manager's fault may still put it at implement.
- Changing an AC is the human's call: ask_user, then the liaison sends `story amend`.
- The sprint start is refused while the previous end boundary is pending; wait for the hand-over.
- Do not call story_status: its output is over 650,000 characters. Rely on hand-over lines and budget_status. events.jsonl is too big to search cheaply; I cannot read worktrees through Glob.

## Artifacts
- Stories: .team/stories/ (s188, s190, s189, s187, s173, s177 in sprint 56; s169, s170, s171 for sprint 57).
- Designs: agile-team/docs/design/ (s180.md, s188.md, s189.md, s177.md, etc.). Sprint story reviews: .team/run/worktrees/<id>/.team/reviews/<id>.md. Acceptance: .team/acceptance/.
- Liaison messages: .team/run/liaison/messages/t254.md (plan), t255.md (s180), t256.md (s177 branch, s164 failure).
