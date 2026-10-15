# ADR-0065: The runner re-pins itself at a sprint end, and until-blocker never stops at one

**Date:** 2026-10-14 · **Story:** s128 · **Design:** `agile-team/docs/design/s128.md`

## Context

Self-hosting (ADR-0029) runs the team on a pinned copy of the runner. Before
this story, new runner code went live only when someone stopped the team,
re-pinned and resumed, so an unattended run kept running old code for days.
With cadence `until-blocker`, a PO turn that ended at a sprint end without
starting a sprint also ended the run. The pass was "quiet", the runner exited 0,
and the unattended job recorded a bare `done`. A plain `start --resume` also
dropped `until-blocker` for the config's cadence. The human (t94) wants sprint
ends never to stop the team, and new code to go live at each sprint end without
anyone stopping the runner.

## Decision

1. **The trigger is the end check.** When the end boundary's full check passes
   on a pinned runner (its package lives under `.team/run/runner-pin`) and the
   head differs from the pin, the runner records `state.repin = head`. This
   happens before the boundary's rebase, so the checked commit is still on the
   branch. Installed skills and working-copy runs never re-pin.
2. **Re-pin between processes, not inside the loop.** The request ends the
   router loop like a stop. `cmd_start` leaves `pid_file` (releasing
   `runner.pid`) and runs `pin-runner.sh <head>`, then `config check` under the
   new pin. It then calls `os.execv` into the new pin's venv console script with
   `start --resume`. The pid stays the same, so the unattended job never sees an
   exit, and no extra `uv` process piles up per sprint.
3. **A marker carries the outcome across the exec.** `.team/run/repin.json`
   (`trial` or `rolled_back`) is written just before each exec. The process
   that starts after it logs one `runner-repin` event (`pinned` or
   `rolled_back`, old and new commit) and removes the marker.
4. **Rollback is a directory swap in the pin script.** `pin-runner.sh` keeps
   the old pin as `runner-pin.prev` (and `.prev.commit`). `--rollback` swaps it
   back and keeps the failed pin as `runner-pin.failed`. Rebuilding the old sha
   would not work: after a sprint-end rebase it may no longer be on the branch.
   The runner rolls back only when the commit file shows the swap happened. It
   rolls back after a failed pin, check or exec (in the old process), or a
   failed first start (in the new process, while the marker says `trial`).
   Then it execs the restored pin and tells the human.
5. **until-blocker keeps going in code.** A sprint end with ready backlog hands
   over `next_sprint`, which is never quiet, and a stuck sprint re-offers
   `ready_backlog` on every idle pass. A cap of 3 unanswered asks ends the run
   `blocked` with a note to the human. `done` and `blocked` from the PO are
   refused while stories are ready. A resume keeps the stored cadence.
6. **Stop reasons are data.** The PO's status notes and a quiet end store
   `status_reason`. The unattended command job reads `state.json` (exit 0) or
   the halt line (halt exits) into its outcome's reason.

## Consequences

- Runner fixes go live one sprint after they are accepted, with no human step.
  The rest of the boundary (review, push, rebase, CI) runs on the new code.
- A sprint end costs one `config check` (a venv build on the first run of a
  new lock) and one exec.
- The old process must not import lazily after the swap, because its editable
  install then points at the new code. `repin.py` imports everything at module
  top.
- A pin so broken that its own rollback code fails is not caught. `config check`
  has already imported the CLI, and the human can run `pin-runner.sh --rollback`.
- The exec target assumes uv's default project venv (`<pin>/.venv`). With
  `UV_PROJECT_ENVIRONMENT` set, the exec fails and rolls back.
- Amends ADR-0029 (the pin script keeps `.prev` and has `--rollback`, and the
  runner re-pins itself) and ADR-0027 (`run.runner_pin`).

## Amended by s156 (2026-10-15)

Rule 5 changes for a stuck sprint. The `ready_backlog` re-offer is gone. A stuck
Sprint Backlog hands over `sprint_backlog_stuck` with each story's stall reason,
under both cadences. Its own cap (`stuck_asks`, 3) sets `blocked` with "the
Sprint Backlog is stuck" and posts it. Steps and the PO's story actions reset the
count. `done` and `blocked` are refused only while a Sprint Backlog story can
move, never because Product Backlog stories are ready. The `next_sprint`
hand-over and its `keep_going_asks` cap stay; the cap text now names only
`start_sprint`. See ADR-0082.
