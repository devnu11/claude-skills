# Team charter

Every role reads this file, right after the repo instructions
(`.claude/CLAUDE.md`, shown above it as "Repo instructions"). Those rules
apply to the team as written and are not repeated here. This file holds only
what is about the team. Keep it short.

## What this repo is

`claude-skills` holds Claude Code skills. You are working on the
`agile-team` skill: its runner (`agile-team/runner/`, Python, uv) is the
program that runs *you*. Read `agile-team/reference/protocol.md` for how it
works today.

## House rules

- Run every tool from the repo root through the configured commands
  (`uv run --directory agile-team/runner …`); never `cd`.
- Functions: one job, ideally under 8 lines, at most 2 parameters
  (constructors excepted). No boolean parameters or flags; use an enum.
- Docstrings on public functions, brief. Comments inside functions only for
  non-obvious pitfalls.
- Coverage is currently 100%; keep it there.
- No new runtime dependencies without an ADR. The dashboard uses the stdlib
  only (http.server, SSE).
- Docs move in the same story as the code.
- The test suite points `AGILE_TEAM_HOME` at a scratch dir.

## Domain vocabulary

- story: a unit of work in `.team/stories/<id>.md`; AC = acceptance criterion.
- requirement: `agile-team/docs/requirements/REQ-NNN.md`.
- liaison: the interactive Claude session relaying to the human.
- snapshot: the JSON the dashboard renders; its contract is
  `agile-team/runner/agile_team/dashboard/fixtures/snapshot.json`.

## Do not touch

- `install.sh`, `tests/install_test.sh`, `example-skill/`.
- `.claude/` (the human's repo instructions; you read them, never write them).
