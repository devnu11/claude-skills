# ADR-0087: A run that waits on the human stays running, and a usage limit has its own status

Story: s159. Design: `agile-team/docs/design/s159.md` (I4 to I7). Amends
ADR-0007 (data-driven halts) and ADR-0020 (unattended wake sources).

## Context

A run that needed the human (the stuck and keep-going caps, the PO's
`notify_user(kind=blocked)`) exited with status `blocked`. Unattended then
had to resume it, and a usage limit used the same status, so the two could
not be told apart. With parallel steps, a limit hits each running step on
its own, and cancelling the others would waste their work.

## Decision

1. **Waiting is not exiting.** The caps and `notify_user(blocked)` post their
   note and leave the run `running` with the reason in `status_reason`, as an
   open question already did. The run polls and carries on within seconds of
   an answer or a tell. `blocked` remains only for the budget halt.
2. **The heartbeat says so.** When `UNATTENDED_HEARTBEAT` is set, the live
   meter writes `{at, progress}` there (progress is the size of the events
   file) and adds `waiting` while the run waits. Unattended posts one
   `waiting` notice and posts it again only after progress. A waiting run is
   never idle-stopped.
3. **`limit` is a status.** `RunStatus.LIMIT` halts with exit 75. A step that
   hits the limit fails alone and is kept as interrupted. Nothing new starts,
   a landing CI wait finishes, and the run halts once nothing is running.
   Unattended reads the reset time from `limit`, and still from `blocked`
   for older runners.

## Consequences

- An unattended job's idle stop no longer ends a run that is only waiting
  for an answer. The deadline still does.
- Tools and docs that keyed on `blocked` for a limit must read `limit`.
