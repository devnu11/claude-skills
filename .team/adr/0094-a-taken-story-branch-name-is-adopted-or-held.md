# ADR-0094: A story's taken branch name is adopted at the sprint head, else the story holds

Story: s190. Design: `agile-team/docs/design/s190.md` (T1 to T7).
Adds to the s159 story-branch rules (ADR-0084 and its amendments); overrides none.

## Context

A story with no `branch` record forks `<story_prefix><id>[-r<replays>]` from the sprint
head with `git branch`. `revert_story` on an unlanded story clears the record but leaves
the local branch, and the runner never deletes a story branch. When the story is planned
again, its first step runs `git branch` on a name that is taken and crashes (s180,
sprint 54). The story held as an error, and `continue_story` only led to the same crash.

There were four choices for the leftover: adopt it, rename it, set it aside, or hold the
story. The leftover of a revert holds work the PO chose to take out, and the liaison may
keep it on purpose (s180's was kept, with a copy on origin).

## Decision

1. **Look before forking.** Before a fork, the runner reads the local branch that has the
   fork's name (`git rev-parse --verify --quiet refs/heads/<name>`).
2. **Adopt only what a fork would make.** If that branch's tip is the sprint head, it is
   exactly what `git branch` would make. The runner takes it as the story's branch with
   no new commit or ref, and logs `story-branch` `adopted` with a `why`.
3. **Otherwise hold, changing nothing.** If the tip is anything else, the step is refused
   before any git write. The runner logs `story-branch` `taken` (branch, tip, base,
   suggested aside name), and the story holds `refused`. The PO's hand-over carries the
   reason, and the reason gives the way out: rename the branch by hand to
   `<name>-kept-<tip[:12]>`, then `continue_story`.
4. **The runner never moves, renames or deletes the leftover.** Whether those commits
   matter is the human's call, and the rename keeps them on a named branch.

## Consequences

- A revert followed by re-planning stalls the story until the human or the liaison runs
  one `git branch -m`. The PO has no shell, so it relays the reason. This is rare (one case
  so far), and a silent fork under another name would have left the old work unseen.
- A leftover that is an ancestor of the sprint head, but not the head itself, holds too.
  Equality is the only case where adoption is certainly what a fork would do.
- Only the fork's name is checked. Replay names (`-r<k>`) only grow, because `replays`
  never goes down, so they don't collide. A remote branch with the same name is not
  checked: its push is refused by the lease, as before (no crash).
- A refusal from `prepare_story` now carries the step's `role`, so the hand-over line
  names who was refused (the drift refusal gains it too).
