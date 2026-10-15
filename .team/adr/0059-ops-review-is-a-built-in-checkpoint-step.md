# 0059: ops-review is a built-in checkpoint step

Story: s115.

## Context

Missing test harnesses, CI jobs and environments were found at acceptance,
after a story had been designed, tested and built. The human wants DevOps to
look at every design before tests are written and say how each AC will be
checked automatically. Until now every pipeline step could be dropped from
`[gates] steps`, and every step a role owns was also a place a bounce or a
Manager fault could send a story back to.

## Decision

1. A new step, `ops-review`, owned by `devops`, sits right after `design`.
   `config.ALWAYS_STEPS` lists it with its anchor; `config.pipeline_steps`
   puts it after `design` (or first) whatever `[gates] steps` says, so it
   cannot be configured away. `Gates.steps` keeps the configured list;
   `Gates.pipeline` is what the run uses. Stories already past `design` are
   never moved.
2. `ops-review` is a **checkpoint** (`gates.CHECKPOINT_STEPS`): a story
   reaches it only by passing the step before (or the ops gate's own retry).
   No bounce, fault, acceptance failure or revert targets it, so a bounce or
   fault naming devops stays off-pipeline as before and does not replay the
   pipeline from `ops-review`.
3. DevOps's verdicts are data: a `tooling` handoff list, one row per AC
   (`automatic`, `added`, `missing` with a story). The runner's ops gate
   checks the list against the story file's ACs, holds the story for the PO
   when a missing need has no story yet, sends `changes_requested` to the
   design step, and on a pass writes the list into the story file under
   `## Tooling` in its own `chore(<id>)` commit.

## Consequences

- Every story costs one more DevOps step, plus one more when the PO has to
  open a tooling story.
- DevOps's write globs now take part in gate-fix ownership (s92), since
  `owners` reads the pipeline roles: a lint failure in a CI file routes to
  devops as a gate fix.
- A future always-on step is one `ALWAYS_STEPS` row; a future checkpoint is
  one `CHECKPOINT_STEPS` entry.
- The story file gains a runner-written section, like `## Reverted`
  (ADR-0057); the Customer Proxy reads it there (it may read
  `.team/stories/**`).

## Amended by s131 (2026-10-14)

The `## Tooling` record used to be written after the story advanced. If its
commit failed, the story was already at `tests` and the record was gone. The
record is now written and committed **before** the story advances, as the
pending registry already was (P13). A commit that fails puts the story file
back to its old text, unstages it, and turns the pass into a gate hold
(`Verdict.HOLD`) whose reason names the git error. The story stays at
`ops-review`, no round is counted, and the PO gets a `gate_hold` hand-over.
The rule covers every `PASS_RECORDS` row, so a future pass record gets the
same order and the same failure handling for free.
