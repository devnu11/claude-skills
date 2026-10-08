# Team charter

Every role reads this file. Keep it short and specific to this repo.

## What this repo is

`claude-skills` holds Claude Code skills. You are working on the
`agile-team` skill: its runner (`agile-team/runner/`, Python, uv) is the
program that runs *you*. Read `agile-team/reference/protocol.md` for how it
works today.

## House rules

- Run every tool from the repo root through the configured commands
  (`uv run --directory agile-team/runner …`); never `cd`.
- Process the skill relies on (gates, formats, state transitions) is enforced
  in code, not only described in prompts. Prompts state the rule; code checks it.
- Prefer tables and data over branching (see `cli.COMMANDS`,
  `gates.STEP_ROLES`, `po_tools.SCHEMAS`).
- Functions: one job, ideally under 8 lines, at most 2 parameters
  (constructors excepted). No boolean parameters or flags; use an enum.
- Docstrings on public functions, brief. Comments inside functions only for
  non-obvious pitfalls.
- Coverage stays at 95%+ (currently 100%); ruff check and ruff format clean.
- No new runtime dependencies without an ADR. The dashboard uses the stdlib
  only (http.server, SSE).
- Docs move with behaviour: `agile-team/SKILL.md`,
  `agile-team/reference/protocol.md` and the README row change in the same
  story as the code.
- Never touch the real home directory in tests; the test suite points
  `AGILE_TEAM_HOME` at a scratch dir.

## Domain vocabulary

- story: a unit of work in `.team/stories/<id>.md`; AC = acceptance criterion.
- requirement: `agile-team/docs/requirements/REQ-NNN.md` (being introduced).
- liaison: the interactive Claude session relaying to the human.
- snapshot: the JSON the dashboard renders; its contract is
  `agile-team/runner/agile_team/dashboard/fixtures/snapshot.json`.

## Do not touch

- `install.sh`, `tests/install_test.sh`, `example-skill/`.
- `.claude/` (the human's repo instructions).
