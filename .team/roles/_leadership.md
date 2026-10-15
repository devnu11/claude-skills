## The human's decisions for the leadership team (this repo)

- **Budget: small steps only.** Raise the run budget one small step at a
  time. The human is dogfooding the budget gate, so ask for the next small
  step, never a large raise.
- **Git: main stays linear.** Code reaches main only by rebase-merge.
  Within a sprint, never rewrite the team branch's hashes. At the sprint
  end the runner pushes the team branch as it is to the sprint's PR,
  waits for green CI, then rebases it onto main (never a merge) and
  pushes it again to the same PR. At the sprint start it rebases the team
  branch onto main once more (a branch already on main is left alone) and
  runs the full checks. A failing start check holds nothing: its failing
  tests are the sprint's known failures, and the PO asks the liaison for a
  story for them, which the liaison places at the top of the sprint or
  later.
