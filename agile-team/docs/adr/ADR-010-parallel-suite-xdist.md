# ADR-010: The runner's suite runs in parallel with pytest-xdist (s70)

Status: accepted (2026-10-12)

## Context

The implement gate runs the runner's whole suite with coverage (s68). On one
core that takes about 233 s. The liaison ran it with pytest-xdist on 10 cores
and it took 51 s
(`.team/run/liaison/reports/2026-10-12-time-spent.md`). Only one test stopped
xdist: it was parametrized with `os.getpid()` and `os.getpgrp()`, so each
worker collected different test IDs and xdist refused to run.

## Decision

1. **pytest-xdist is a dev dependency** of `agile-team/runner`
   (`[dependency-groups] dev`, locked in `uv.lock`). It is not a runtime
   dependency, so the installed runner does not change.
2. **The runner's own commands opt in with `-n auto`:** the gate's `coverage`
   and `test` commands, the `[[toolchain.targeted]]` row for
   `agile-team/runner`, and CI. `addopts` stays without `-n`, so a named test
   run from a role's Bash stays serial.
3. **pytest-cov combines coverage across workers.** It prints one `TOTAL`, so
   the gate's parser and the 95% floor are unchanged.
4. **Test IDs never hold a live value.** The runner's ids are injected into
   `sandbox.stop_stale` (`process_groups.RunnerIds`), so the test can pass
   fixed fakes. A test collects the suite in two processes and compares the
   IDs.

## Options considered

- **Make `-n auto` the default in `addopts`.** Every pytest run would be
  parallel, including a single named test, which then pays for worker start-up.
  Rejected: the opt-in is explicit and is written down in the configured
  commands.
- **Keep the parametrize and resolve the ids by label in the test.** This
  fixes the IDs without touching code, but the story asks for injection. With
  injection, the test proves `stop_stale`'s own check, not only the
  `getpgrp()` wall further down.
- **Stay serial.** Each gate keeps costing about 3 more minutes. Rejected.

## Consequences

- A full gate run drops from about 4 minutes to about 1 on a 10-core machine.
  On one core, `-n auto` runs a single worker, which is no slower than serial
  apart from its start-up.
- Tests must be independent of order and of other processes: they get no
  shared fixed ports, no fixed paths outside `tmp_path`, and no state left
  between tests. xdist's own collection check and the s70 ID test catch live
  IDs.
- The `python` preset is unchanged, because a user's repo may not have
  pytest-xdist. Users can add `-n auto` to their own commands.
- `unattended/runner` stays serial for now.
