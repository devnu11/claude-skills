# PO handoff (sprint 54)

## State
- Sprint 53 is complete: s174, s175, s176 and s181 landed. Its PR #76 passed CI ("ready to merge by fast-forward only"). The human was told (messages m381, m383). #76 replaces the earlier #74 note.
- Sprint 54 just started. Stories, in order: s180, s182, s183, s184, s177, s186. The runner runs the manager first.
- Goal: fix the runner bugs found in sprints 52 and 53.
- Budget at last check: $1207.98 of $1500 spent, $292.02 remaining (80.5%). Raise it in small steps only (leadership rule).

## Open decisions
- None waiting on the human. No pending ask_user ids and no stories blocked on a question.

## Next
- Handle whatever the runner hands over. Do not call a PR ready except on `ci_green`.
- At sprint complete, notify_user with kind sprint-end and the Review: line. With Product Backlog stories ready, start the next sprint. Candidates still in the Product Backlog: s173, s185, s141, s57 and its follow-ups s145-s149, plus the older design-stage stories.
- Routing rules from the Manager:
  - s152: F1 needs real-git tests, so it goes to the integration-tester. Not developer-cli or quality-czar.
  - s179: a review whose findings name only test files goes to the unit-tester or integration-tester, not to implement.

## Artifacts
- Stories: `.team/stories/` (s180, s182, s183, s184, s177, s186 and others).
- Designs: `agile-team/docs/design/`. Reviews: `.team/reviews/`.
- Acceptance reports: `.team/acceptance/`.
