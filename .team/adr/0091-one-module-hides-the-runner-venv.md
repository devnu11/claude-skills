# ADR-0091: one module hides the runner's venv from roles and commands

Story: s174.

## Context

The runner runs inside its own venv (`uv run --project agile-team/runner`), so its
process has `VIRTUAL_ENV` and the venv's `bin` first on `PATH`. #55.7 hid them from role
steps with `dispatch.hide_runner_venv`, but the commands the runner runs itself
(`commands.CommandShell`, `tally_watch.watching`) copied `system.environ()` whole. Gates
then ran the runner's `pytest`/`ruff` and `uv run` warned "VIRTUAL_ENV does not match".
`commands` can't import `dispatch` (which imports `commands`).

## Decision

A new module `agile_team/runner_venv.py` owns the rule: `strip_venv_bin` (drop every PATH
directory whose parent is the runner's venv), `hide_runner_venv` (moved from `dispatch`;
roles: `VIRTUAL_ENV` blanked, since the SDK only adds to the inherited environment) and
`get_command_environ` (runner commands: the runner's environment with `VIRTUAL_ENV`
removed and the same PATH filter). `dispatch`, `commands` and `tally_watch` import it.

## Consequences

- Roles and gates see the same tools, so a command that passes in a role's shell passes
  at the gate.
- A command gets no `VIRTUAL_ENV` at all; a role gets `VIRTUAL_ENV=""`. The difference is
  the SDK's merge, not a second rule.
- Any later place that starts a configured command builds its environment with
  `get_command_environ`, never from `system.environ()` directly. `system.run` calls for
  git, gh, ps and the re-pin are not configured commands and keep the full environment.
- Known exception, left for a follow-up story: the acceptance environments'
  `prepare`/`start` commands (`sandbox.sandbox_env`) still build from `system.environ()`
  and inherit the runner's `VIRTUAL_ENV`.

## Amended by s186 (2026-10-25)

The known exception is closed. `sandbox.sandbox_env` now starts from
`get_command_environ()` and then puts the environment's `bin` dirs in front of the
filtered `PATH`. Filtering comes first, so an environment's own venv `bin` is never
dropped. The prepare and start commands therefore get no `VIRTUAL_ENV` and no runner
venv `bin`. The Customer Proxy's launch still goes through `hide_runner_venv`, which
blanks `VIRTUAL_ENV` for the SDK's merge. Why: an acceptance check must not pass or fail
because of the runner's own Python (REQ-232, REQ-233).
