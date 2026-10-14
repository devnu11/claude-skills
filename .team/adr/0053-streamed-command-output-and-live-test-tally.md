# ADR-0053: Command output is streamed, and a test run reports live counts

**Date:** 2026-10-13 (s118 design)
**Status:** Accepted
**Amends:** ADR-0048 (the open stage row and the stage board)
**Design:** `agile-team/docs/design/s118.md` (R5–R10, FC18)
**Amended:** s118 round 2, see the end

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

## Amended by s118 round 2 (2026-10-13)

**What changed.** The decision above rested on the premise that pytest can't
report warnings while it runs, so Warn had to mean what pytest colours
yellow (`s`, `x`, `X`). That premise was wrong (the human's decision t76,
AC6 amended at 682b68a). pytest-xdist 3.8 relays every test report and
every recorded warning to the controller as they happen, and the total
comes from `worker_collectionfinish`. So the counts now come from a pytest
plugin, and the progress-line parser goes.

**Decision, replacing the `test_tally` and "no plugin" points above:**

- A plugin, `agile_team/pytest_plugin/agile_team_tally.py` (stdlib and
  pytest only, in a directory holding nothing else), counts per test:
  Pass, **Warn = tests that recorded a warning** (`pytest_warning_recorded`),
  **Skip = skipped, xfailed and xpassed**, and Fail. It uses pytest's own
  `pytest_report_teststatus` and counts a test at its teardown report. Its
  total comes from `pytest_collection_finish`, or from
  `pytest_xdist_node_collection_finished` on the xdist controller. It
  writes one JSON record (with a per-process `session` id) to the file
  named by `AGILE_TEAM_TALLY`, atomically, at most every 0.5 s and at
  session end. It removes that variable and itself from `PYTEST_PLUGINS`
  at configure, so xdist workers and pytest runs started by tests stay
  out.
- When a stage is open, `CommandShell` runs the command with the plugin's
  directory appended to `PYTHONPATH`, the plugin appended to
  `PYTEST_PLUGINS`, and `AGILE_TEAM_TALLY` set to a scratch file
  (`tally_watch.watching`). `TallyWatch` reads that file every 0.5 s on a
  thread and hands each new record to the run (`Run.hear`). Outside a
  stage nothing is injected.
- `test_tally.read` folds records, not lines. A record from a new session
  starts a new tally, so a stage that runs `pytest && pytest` shows the
  session that is running and never adds the two together. "% complete" is
  reports received / collected total.
- `Pump` still reads the output on a thread under one deadline, but it no
  longer tells the stage anything.
- If pytest can't import the plugin (a command that sets its own
  `PYTHONPATH`), the command runs once more without it. A tally never
  breaks a gate.

**Consequences, replacing the first and third points above:**

- The repo's commands stay unchanged, and any pytest run inside a stage
  has live counts at any verbosity. A plugin file ships with the runner,
  but there is no new runtime dependency: pytest loads the plugin in the
  repo's test environment, not in the runner's.
- The runner changes the environment of commands run inside a stage. A
  repo whose tests check `PYTEST_PLUGINS` or `PYTHONPATH` would see the
  change.
- A command that sets its own `PYTHONPATH` costs a second run. A command
  that clears the environment shows no counts.
- The total is always known from collection, so it is never estimated.
- The heartbeat's `stages[].tests` gains `skipped`.
