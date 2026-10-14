# ADR-0053: Command output is streamed, and a test run reports live counts

**Date:** 2026-10-13 (s118 design)
**Status:** Accepted
**Amends:** ADR-0048 (the open stage row and the stage board)
**Design:** `agile-team/docs/design/s118.md` (R5–R8, FC18)

## Context

The Flow chart must show a running test command's Pass, Warn and Fail counts
out of the suite's total while it runs (s118 AC6). `CommandShell.run` read a
command's output with `communicate()`, so nothing was known until the
command ended, and the open stage row in the heartbeat had no counts.

## Decision

- `CommandShell` reads the output on a thread (`commands.Pump`), line by
  line, under the same single deadline as before. The returned code and text
  are unchanged. The thread hands each line to the stage open on the
  caller's thread (`stages.current()`, captured before the thread starts:
  context variables do not cross threads) through `Run.hear` and its
  `listeners`. `stages.py` stays pure.
- A pure fold, `test_tally.read(tally, line)`, recognises pytest's progress
  lines and total lines (`collected N items`, `N workers [N items]`). Pass is
  `.`, Fail is `F`/`E`, Warn is what pytest colours yellow: `s`, `x`, `X`.
  Anything else leaves the tally as it was, so any command can be streamed.
- `stage_log.Tallier` writes the tally into the open row's `tests` key (a
  key every row has from the start, `null` until counts arrive) and asks the
  board to rewrite the heartbeat at most every 2 s (`StageBoard.refresh`).
- A listener's error never reaches the gate: the pump swallows it.

## Consequences

- Live counts for any stage that runs pytest through `CommandShell`, with no
  change to the repo's commands and no plugin.
- Other test runners (jest, `pytest -v`) show elapsed time only until a row
  is added for them.
- Without a total line the total is estimated from the percentage.
- One extra thread per command; it ends with the pipe, and a pipe still open
  past the deadline counts as a timeout, as `communicate()` did.
- The closing `runner-stage` event is unchanged; the heartbeat version stays
  2 (an added key).
