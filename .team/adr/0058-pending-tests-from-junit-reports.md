# ADR-0058: A story's new red tests are pending, read from JUnit reports

Story: s125. Design: `agile-team/docs/design/s125.md`.

## Context

The pipeline is test-first. The unit-tester's new tests are red from the tests
gate until the developer's implement gate passes. Until s125, anything else that
ran the suite in that window (another story's gates, the quality run, the sprint
boundary's full checks, GitHub CI on the review PR) saw those red tests as
failures. A sprint with a story mid-pipeline could not have a green boundary or
a green PR.

The human asked (t83, revised by t84) for the runner to keep a registry of
pending test ids, taken from a structured report, not from the text output.

## Decision

- **Structured results.** Every gate and full-check run of the `test` or
  `coverage` command writes JUnit XML. The option comes from data: a new
  `[toolchain.report]` table (`option`, `deselect`, `ignore`), filled from the
  preset and overridable in `.agile-team.toml`. The python preset's values are
  `--junitxml={file} -o junit_family=xunit1`, `--deselect={id}` and
  `--ignore={id}`. `xunit1` is needed because only that family writes each
  test's `file` and `line`, which is how a node id is rebuilt and how a test is
  matched against the step's diff. Stacks with no `option` keep the old
  exit-code gates, and nothing becomes pending for them.
- **Where the option goes.** A test or coverage command may hold
  `{report}` or `{report:<root>}` placeholders, one for each pytest
  invocation in a `&&` chain. `<root>` is the repo-relative directory pytest
  runs in. Each placeholder becomes the option with its own report file,
  followed by the skip options for the pending ids under that root. A command
  with no placeholder gets one `{report}` appended at the end.
- **Ids are repo-relative node ids.** An id is `<root>/<file>::<Class>::<name>`,
  or a bare file (`<root>/<file>`) when the file failed to collect. A file id is
  skipped with `ignore`, because `--deselect` cannot stop an import error.
- **The registry.** `.team/pending-tests.json` is `{story: [ids]}`, sorted,
  and written only by the runner. The guard refuses an agent's write to it, and
  quarantine reverts a Bash edit to it. The tests gate sets the story's entry
  from the red run's report: the failed ids that are new or changed in the
  step's diff, plus failed ids that were already the story's. A failed id
  outside both is a real failure, and the gate fails. The implement gate
  removes the entry when every one of the story's ids passed. A cancel or a
  revert drops it.
- **Who runs what.** A run made for a story skips every other story's pending
  ids and runs its own. A run made for no story (the boundary's full checks)
  skips them all. Named runs (`run_tests`) never skip.
- **Its own commit.** The registry change is committed by the runner right
  after the gate, as `chore(<story>): pending tests`. It does not amend the
  step's commit. That sha is already recorded in the `step-end` event, in
  `story.commit` or `code_commits`, and in the Stop hook's proof, and a gate
  can pass with no step commit to amend. The subject is not a story commit, so
  `revert_story` never reverts it. The revert drops the entry itself.
- **CI.** `agile-team pending-tests [--root R]` prints the skip options in
  `PYTEST_ADDOPTS` form, so DevOps's workflow skips the same ids.

## Consequences

- AC2 and AC3 say "in the step's commit" and "in the gate's commit". Here the
  registry change is a separate runner commit that comes right after it, with
  no role step in between. If the human wants a literal amend, this ADR is
  amended.
- Routing gate failures to their owners (s92) reads failing test ids and files
  from the report when there is one. Lint findings still come from the text.
- A repo that chains test runs with `&&` must put a `{report:<root>}` in each
  link, or the runner sees only the last link's report. In this repo, DevOps
  makes that edit in `.agile-team.toml`.
- In a `&&` chain, a red first link stops the later links. Their real failures
  are seen at the next run, not at the tests gate.
- "Changed" is measured per test: the lines from the test's own line up to the
  next test's line in the same file must meet a hunk of the step's diff. A
  changed helper above the first test changes no test, so an old test it breaks
  is a real failure.
- `.gitignore` for `artifacts = "ignored"` gains `!.team/pending-tests.json`,
  so the registry is always committed and is part of the review PR.
