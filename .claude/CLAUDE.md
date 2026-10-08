# claude-skills: how skills here are developed

Repo-specific rules. The global `~/.claude/CLAUDE.md` style rules still apply;
they are not repeated here.

## Layout

- One directory per skill. `SKILL.md` frontmatter `name` matches the directory.
- `description` says when to use the skill and lists concrete trigger phrases.
- Keep `SKILL.md` short: it is loaded whenever the skill triggers. Put detail
  in `reference/` files that `SKILL.md` points to by path.
- Add every skill to the table in `README.md`.

## Process lives in code

If a skill depends on a process (gates, file formats, state transitions,
approvals), code enforces it. A prompt states the rule and the code checks it.
A rule that exists only in a prompt is a wish.

- Treat frontmatter and TOML as data, validated on load.
- Prefer tables over branching. See `cli.COMMANDS`, `gates.STEP_ROLES` and
  `po_tools.SCHEMAS` in `agile-team/runner`.

## Python runners

- Use `uv` and Python ≥ 3.12. Dependencies install on first use through
  `uv run --project <runner>`, so add few of them.
- Lint with ruff (line length 100, rules in `pyproject.toml`).
- Use pytest with coverage `fail_under = 95`.
- Before committing, run the same checks as CI:
  `uv run ruff check . && uv run ruff format --check . && uv run pytest --cov`.
- Each module gets a matching `tests/test_<module>.py`.

## Shell

- Use POSIX `sh` that passes shellcheck. It must run under dash and under bash
  3.2 as `/bin/sh` (macOS). CI tests both.
- `tests/install_test.sh` covers `install.sh`. Every test works in a scratch
  directory.

## Never touch the real home directory

- Tests and manual checks use a scratch `HOME` (`HOME=$(mktemp -d)`) or
  `CLAUDE_SKILLS_DIR`. Never use the real `~/.claude` or `~/.config`.
- chezmoi pins `~/code/claude-skills` to a commit. A change ships as a commit
  here, then a pin bump in the dotfiles repo, which is a separate step the
  human runs.

## Cross-platform

Behaviour that differs on Windows must be a deliberate branch that is tested
and documented, for example the agile-team dashboard binding to localhost
only on Windows.

## Docs move with behaviour

A change in behaviour updates, in the same commit series, the skill's
`SKILL.md`, its `reference/` docs and its row in `README.md`.
