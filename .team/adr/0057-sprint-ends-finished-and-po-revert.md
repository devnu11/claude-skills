# ADR-0057: A sprint ends only when finished; the PO reverts a story, the runner keeps the books

Story: s124. Design: `agile-team/docs/design/s124.md`.

## Context

The end boundary already opened only when every sprint story was `DONE`, but the
PO could still end a sprint by hand (`notify_user` with kind `sprint-end`, which in
sprint cadence stops the run) while stories were half-built. The Cadence text told
it to do so when stories were "done or blocked". A stuck sprint also ended the run
early, or waited for the human with work in the backlog that could have run. The
human (t83, t84) set the rule: a sprint ends only when each of its stories is done,
cancelled (the human's call, s53) or reverted (the PO's call). The PO keeps the
team working by adding ready stories (s122's `add_to_sprint`).

## Decision

- **One predicate.** `RunState.sprint_complete()` means the sprint has stories and
  none of them is unfinished. Both the end boundary and the `sprint_end`
  hand-over use it. `notify_user(kind="sprint-end")` is refused while any sprint
  story is unfinished, and the refusal names each one and its step.
- **Revert is a PO tool.** `revert_story(story, reason)` reverts the story's commits
  in one commit, `revert(sN): <title>`. The commits are the first recorded commit
  and its `fixup!` followers, found by subject from that commit to HEAD. The story
  goes back to the backlog at the step before `tests`, as a fresh `StoryState` that
  keeps its id, title, dependencies, developer choices and revert history.
- **The runner keeps the books.** It adds a `## Reverted` entry to the story file
  (a second commit, because a file can't name its own commit), a `story-reverted`
  event, `reverts` in the snapshot (the pill `reverted (n×)`) and a `Reverted:` block
  in the sprint's review PR. It adds a note in the next brief of each role that
  worked on the story (from `step-end` events) and an `update` to the human. A
  design gate requires `## After revert N` in the story's design file.
- **A second revert asks the human,** like a cancel request. A `revert requested`
  PO hold carries the question, and the answer is settled where cancel answers
  are settled.
- **Ready backlog hand-over.** When nothing in an open sprint can move, the router
  hands the PO the ready backlog stories once for each distinct set of stuck and
  ready stories (`RunState.offered`), even while a question is open. The new trigger
  `ready_backlog` is not "quiet", so the run does not end on it.

## Consequences

- Process moves from the prompt into code: the PO can't end a sprint with
  unfinished work, and the Cadence text changes to match.
- A revert can fail on a conflict with later commits. Git is aborted and nothing
  changes, and the PO gets the reason. A story that started stories depend on can't
  be reverted until they are.
- Revert history shas are not remapped by the sprint-end rebase (s59), unlike
  `commit` and `code_commits`. They name the commits as they were on the team
  branch when reverted.
- A story with no commits can't be reverted. The PO finishes it, or asks the human
  to cancel it.
- `start_sprint` with unfinished stories still works with a reason (ADR-0055). Like
  s124, it never runs the end boundary for the old sprint.
