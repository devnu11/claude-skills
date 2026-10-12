# ADR-0034: Only the runner runs the full test suite and coverage

**Status:** Accepted  
**Date:** 2026-10-12  
**Story:** s69

## Context

Agents spend ~62% of their step time in tools, mostly running full pytest suites and coverage checks (multiple roles re-running the same suite per story pass, 7–9 minutes per implement → quality gate). The human rule: **agents never run the full suite or coverage.** The runner runs them and hands results to the roles in briefs.

## Decision

### 1. Bash denial rules (suite_check.py, guard.py)

A Bash segment is analyzed for test command patterns. Rules S1–S9 deny:
- **Run.FULL** (any test run without specific targets) to every role except devops
- **Run.COVERAGE** to every role except devops
- **Run.TARGETED** (named test files/node ids) to code-reviewer and quality-czar only

Detection treats the first test tool word after environment assignments, launchers, and shell expansions. Positional words (filenames, node ids) are identified by S5 rules (no `-` prefix, path ends in `.py`, no glob chars, no `::`-to-glob split). Over-deny is preferred: redirect targets with spaces count as positionals (making the run FULL), redirects without spaces do not.

Denial reasons are exact and pinned: developers are told to ask the runner with `run_tests` or `run_new_tests` tools, or run named tests in Bash.

### 2. Runner results in briefs (results.py, gates.py, dispatch.py)

The test and coverage gates return their run in `Outcome.ran: Ran(name, code, result_tail(out))`. The result is kept in `.team/run/results/<story>/<name>.json` (gitignored) using the story id and command name (test, coverage, lint, static). Before a quality-czar step, the runner pre-runs any uncached lint and static checks.

`Ran` persists: `at` (HEAD sha at run), `where` (which gate/stage ran it), `code` (exit code), and `tail` (last 60 lines of output). A `results.section(found)` call builds the brief's `## Runner results` section, listing each run with exact format.

Role briefs show results based on their step: implement shows test and coverage; quality shows coverage, lint, static; review shows coverage.

### 3. Developer runner tools (runner_tools.py, config.py)

Every developer step gets an MCP server `runner` with two tools:
- `run_tests({"tests": [...]})`: Run named test files or pytest node ids. Refuses empty lists, non-targets, untracked files, missing toolchain.targeted rows.
- `run_new_tests({})`: Run the story's recorded test files (those committed by unit-tester in this story). Refuses if no story or no recorded tests.

Each tool identifies paths via `toolchain.targeted` rows (longest matching `root` wins; `""` root holds all paths). Ids are relative to the root, quoted, space-joined into the row's `command` with `{tests}` replacement. Results are kept the same way as gate runs and streamed as `tests-run` events.

`[[toolchain.targeted]]` config rows have `root` (directory, default `""`) and `command` (must hold `{tests}`).

### 4. Role changes

Role files updated:
- **developer:** Tells developers to ask the runner or run named tests in Bash.
- **unit-tester:** Confirms only recorded tests for their story, by name.
- **quality-czar:** Has no Bash (only Read, Grep, Glob); judges results in brief.
- **code-reviewer:** Reads tests, does not run them; sees coverage in brief.
- **integration-tester:** Can run e2e tests by file name only; no directory or full suite.
- **_shared:** Full and coverage runs denied; only named tests allowed.

## Consequences

### Benefits
- **Gate speed:** Implement → quality drops from 7–9 min to ~4 min (one coverage run instead of test + coverage).
- **Consistency:** Every role sees the same test results in their brief.
- **Auditability:** All suite runs are run by the runner and logged in results.
- **Developer control:** Developers can still run named tests quickly without waiting for gates.

### Costs
- **Config required:** Repos must add `[[toolchain.targeted]]` rows to use runner tools; `run_tests` refuses without them.
- **Guard enforcement:** Over-deny on redirect targets with spaces; agent must write `>/path` not `> /path`.
- **Quality czar isolation:** No Bash access; must judge results from brief (safer, but limits ad-hoc checks).

### Scope
- Applies to every story with implement, tests, quality, and review steps.
- devops keeps full-suite and coverage rights for onboarding baseline recording.
- Open question: if the human wants devops denied too, the runner must record the baseline.

## Reference

- **Design:** `agile-team/docs/design/s69.md` (rules S1–S10, B1–B6, Q1–Q4, R1–R10, T1–T2)
- **Test checklist:** 24 test areas covering suite_check, results, gates, dispatch, runner_tools, guard, role files, and config
- **Related:** s68 (gate cycle time), s43 (timeout), s41 (signal safety)
