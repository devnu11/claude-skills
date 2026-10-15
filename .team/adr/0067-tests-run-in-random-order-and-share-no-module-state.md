# ADR-0067: The runner's tests run in random order and share no module-level state

**Date:** 2026-10-14 · **Story:** s130 · **Design:** `agile-team/docs/design/s130.md`

## Context

`tests/test_presentation.py` and `tests/test_service_presentation.py` keep the
current config in a module-level list, `CURRENT`. The `config` fixture fills it,
and `story_of()` reads `CURRENT[0]`. Whether `story_of()` sees the right config
depends on which test last ran that fixture in the same process. With `-n auto`,
that depends on how xdist splits the tests among workers.
`test_complete_files_then_the_liveness_outcome_decides` failed this way (the
human's t96, item 13). Nothing in the suite looks for this kind of shared
state, and the suite always runs in file order. So any other such dependency
stays hidden until a split happens to expose it.

## Decision

- Test helpers take the config as a parameter. The `CURRENT` lists go.
- `tests/state_scan.py` holds an AST scan. It fails when code inside any
  function in a test file writes to a module-level mutable value, or declares
  `global`. Writes are item and slice assignment, `del`, augmented
  assignment, a mutating method call, or an attribute store reached from the
  name. The scan has no exemption list. `tests/test_s130_module_state.py` runs
  it on the unit tree, and `tests/e2e/test_s130_module_state_e2e.py` runs it on
  the e2e tree. The tree split is `clock_scan.Tree` (ADR-0066).
- `pytest-randomly` joins the agile-team runner's **dev** dependency group. It
  is on by default, so every gate run, every CI run and every named-test run
  uses a random order and prints its seed. `-p no:randomly` turns it off.
  `--randomly-seed=N` replays an order.

## Consequences

- An order dependence shows up as a failing gate or CI run that names its seed.
  It doesn't wait for an unlucky xdist split. The failure routes to the test's
  owner like any red test.
- pytest-randomly also reseeds `random` before each test. No runner test relies
  on unseeded randomness.
- This is a dev-only dependency. No runtime dependency, snapshot key or runner
  behaviour changes.
- The scan can't see a module constant passed into code that mutates it. Review
  still catches that.
- The unattended runner's suite (`unattended/runner`) is out of scope. It keeps
  file order until a story extends this rule to it.
