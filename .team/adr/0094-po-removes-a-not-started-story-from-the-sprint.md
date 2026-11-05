# ADR-0094: The PO takes a not-started story out of the running sprint with `remove_from_sprint`

Story: s189. Design: `agile-team/docs/design/s189.md`.

## Context

A story leaves the running sprint only when it is done, cancelled by the human or
reverted by the PO (ADR-0057). `start_sprint` also moves stories it doesn't list
back to the Product Backlog, but it opens a new sprint number. `revert_story`
refuses a story with no commits. In sprint 54, s180 crashed before its first
commit, so nothing could take it out. The sprint end was refused, and the liaison
edited `state.json` by hand.

## Decision

- **A new PO tool, the pair of `add_to_sprint`.** `remove_from_sprint(story,
  reason)` sets the story's `sprint` to `None`. The sprint keeps its number, goal
  and branch. The story keeps its step and its place in the order. `revert_story`
  is not widened: a revert resets the step, keeps a revert history, asks the human
  the second time and asks for a new design. None of that fits a story that never
  started.
- **Only for a story with no work.** A story with commits, a landing or an open
  landing is refused, and the refusal names `revert_story`. A branch with no
  commits on it is not work. Like `revert_story` and `add_to_sprint`, the tool is
  refused while a boundary is pending.
- **Its holds are cleared and recorded.** The runner's hold and the PO's own
  hold are cleared. The story file gets a `## Left the sprint` line naming the
  reason and the cleared hold, in one runner commit made under the checkout lock.
  One `story-admin` event and one `update` note say the same.
- **It leaves like a `start_sprint` leaver.** Its worktree is removed and its
  branch is kept (REQ-149). One helper does this for both tools.

## Consequences

- One crashed story with no commits no longer blocks the sprint end or needs a hand
  edit of `state.json`.
- The sprint-end refusal and the stuck Sprint Backlog advice name the new tool, so
  the PO finds it where it is stuck.
- The PO can clear a crash hold without running the step again. The cause of the
  crash still needs its own story.
- A story with work still leaves the sprint only by being reverted, cancelled or
  done.
