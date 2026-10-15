# ADR-0080: Gate results keep each failing test's first error lines

**Date:** 2026-10-15
**Status:** Accepted
**Story:** s154

## Context

A gate's kept run (`.team/run/results/<story>/<name>.json`, s69) holds the exit
code and the last 60 output lines. When a run fails hundreds of tests, the tail
shows only names and the summary, so the cause (here a bare `AssertionError` at
setup from `assert not self._finalizers`) was found only by digging through the
JUnit report by hand. The runner already reads that report (s125, `junit.py`).

## Decision

- `junit.Case` gains `detail`: the first error lines of its `<failure>` or
  `<error>` (lines marked `E ` by pytest, else the first lines of the text, else
  the `message` attribute; at most 5). `Report.failures()` maps each failing or
  erroring id to them.
- `results.Ran` gains `failures: dict[str, str]` (id → first error lines), filled
  for the `test`, `coverage` and `suite-runs` runs from the run's report, `{}`
  without one. The JSON file carries it; an old file without it loads with `{}`.
- The brief's `## Runner results` block lists the first 10 failing tests with
  their lines and counts the rest.
- A gate event whose verdict is not `pass` carries `failures` (first 10) and
  `failures_more`; the dashboard's gate entry shows them under the reason.

## Consequences

- The cause of a red gate is in the brief, the results file and the dashboard
  without opening the report.
- Results files grow with the number of failures (a few lines each); events
  stay bounded by the cap of 10.
- The boundary's full checks don't write results files and are unchanged.
- Design: `agile-team/docs/design/s154.md` (G4–G7).
