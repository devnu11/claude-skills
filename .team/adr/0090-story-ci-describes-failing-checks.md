# 0090: Story CI describes its failing checks, and failing lines are picked by tier

## Context

s172: a red story CI reached the PO as a bare check name, because
`StoryCiPoll` recorded `prs.list_checks` raw and never fetched a failing
job's step or log (only the sprint boundary's `CiWatch` and the landing's
`ShaWatch` call `classify_check`). Even where logs were read,
`ci.failing_lines` knew only pytest and Go lines and fell back to the log's
tail, so a ruff or house-rules failure showed whatever came last. Fetching a
job and its log costs two GitHub API calls per failing check, and the story
poll runs every 60 s.

## Decision

1. Story CI describes each failing check with `ci.describe_check(prs, check)`:
   it fills `step` and `lines` but leaves `kind` unset, so the story CI's
   verdict stays the bucket verdict it was. Re-triaging story CI (infra,
   stale) is not part of this decision.
2. `StoryCiPoll` describes a check at most once per `(sha, link)` and keeps
   the result in memory for the life of the run. It describes nothing while
   any check is still pending. The 60 s poll gate stays.
3. `StoryCi` gains `checks: list[str]` (the rendered check lines). It is
   saved in `state.json`, so a developer brief can show the lines after a
   restart. An old `state.json` without the field loads with `[]`.
4. `ci.failing_lines` picks lines by tier, from the table
   `ci_findings.TIERS`. The first tier with a hit wins: test lines first,
   then lint findings, and the tail only when neither tier hits. The tiers
   keep pytest's traceback `path:line:` lines from crowding out its `FAILED`
   lines. A count line that starts with `Found` is a linter's summary, not a
   test count.

## Consequences

- The PO's `story_ci_red` hand-over and the developer's `## Story CI` brief
  section show the same lines as the `story-ci` event, with no extra fetch.
- At most two extra API calls per new failing job. A transient empty log is
  kept as empty for that job; a failing `gh api` call is "no result" and is
  retried at the next poll.
- The finder table is data: a new tool's finding format is one row.
- The snapshot's `story_ci` object gains `checks`. The dashboard reads only
  `sha`, `verdict` and `source`, and the fixture's `story_ci` values are all
  `null`, so the snapshot contract fixture is unchanged.
