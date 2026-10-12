# ADR-0033: Implement gate runs coverage once, not test then coverage

**Date:** 2026-10-12  
**Status:** Accepted  
**Story:** s68

## Context

The implement → quality gate ran two commands in sequence:
1. `commands["test"]` via `green()` (4 min)
2. `commands["coverage"]` via `tests_green_and_covered()` (4 min)

Total gate time: 7–9 minutes. The coverage run itself runs the full test suite (`pytest --cov`) and provides both test results (exit code) and coverage %; the first test-only run is redundant.

## Decision

The gate now calls `run(commands["coverage"])` exactly once. The coverage command's exit code and output alone prove:
- Tests passed (exit 0 → healthy)
- Test failure (detected via regex patterns in output)
- Coverage shortfall (low % but no test failure detected)
- Other failure (unknown cause, report output tail)

### Test failure detection (C6)

Instead of running the test command first, the gate detects test failures via regex patterns in the coverage command's output:

```python
TEST_FAILURES = (
    re.compile(r"\b[1-9]\d* (?:failed|errors?)\b"),  # pytest/cargo/jest summaries
    re.compile(r"^--- FAIL:", re.MULTILINE),          # go test
)
```

`tests_failed(output)` returns True if any pattern matches. Note `[1-9]`: `"0 failed"` must not count as a failure.

### Exit code branching (C1–C5)

- **Exit 0:** `_coverage_outcome(parse_coverage(out))` → pass or bounce with coverage figure (C3)
- **Non-zero exit:**
  - If output shows a test failure (C6) and/or tests_failed() is True → bounce `tests fail:\n{tail(out)}` (C5)
  - Else if coverage is below requirement and tests_failed() is False → bounce `coverage {pct}% is below {req}%` (C4: shortfall without visible test failure, e.g., pytest-cov's fail_under stopped the run)
  - Else (unknown cause) → bounce `tests fail:\n{tail(out)}` (C5: safe side, preserving output)
- **Timeout:** bounce with timeout text (C2), unchanged

### Shared bounce text (C7)

Both `green()` and the new `_failed_run()` use the constant `TESTS_FAIL = "tests fail:\n{tail}"` to keep test failure messages DRY. This replaces inline construction in `green()`.

### Interface unchanged (C8)

- Gate name, bounce_to, round counting, and event shape stay the same
- Cycle time drops to ~4 minutes (one full test suite run instead of two)

## Consequences

### Accepted

A repo with:
- `.team/baseline.json` coverage debt (e.g., baseline 80%)
- A coverage command with `fail_under: 95` (above the baseline)

will now bounce `tests fail` when the coverage run exits nonzero due to `fail_under` stopping the suite. Before, the coverage exit code was ignored and the gate passed (because the test command passed).

**Reason:** The gate now trusts the coverage command's exit code, which is correct. The repo's config is wrong: it should use the gate's `required_coverage` threshold (95%) and not set its own `fail_under`, or set `fail_under` to the baseline (80%).

**This repo is not affected:** It has no baseline file and `fail_under == required_coverage (95%)`.

### Non-blocking follow-up

The boundary checks (`fullcheck.py`) still run `test` and `coverage` as separate checks. A future story can merge them the same way.

## References

- Design: `agile-team/docs/design/s68.md`
- Protocol: `agile-team/reference/protocol.md` § "Pipeline and gates"
- Tests: `tests/test_s68.py`, `tests/test_gates.py` (coverage path), `tests/test_s43.py`
