# ADR-0081: House-rules runs in the team's toolchain, and its baseline only shrinks

**Date:** 2026-10-15
**Status:** Accepted
**Story:** s157

## Context

House-rules (`house-rules/runner`) checked this repo only in CI. No team step
ran it, so sprint 45 reached its sprint-end CI with 59 new findings. The runner
already runs `[toolchain] lint` and `static` at gates, the quality step and the
boundaries, and routes their `path:line:` findings to the file's owner. It also
runs `[toolchain.files] fix` and `lint_files` on a step's changed files at a
`done` stop. House-rules prints failures and warnings in the same
`path:line: <level> <rule>: …` shape and walks the whole repo root, which in
the team checkout includes untracked runner copies under `.team/run/`.

## Decision

1. **Configuration, not runner code.** House-rules joins `static` (whole repo,
   from the root), `lint_files` (the step's files) and `fix` (the baseline
   shrink) in this repo's `.agile-team.toml`. The runner gains no
   house-rules-specific code; a repo without these lines runs none of it.
2. **Reaching the project from a root.** File templates run under `sh -c` from
   the repo root, so `--project "$PWD/house-rules/runner"` reaches the project
   from any `{root}`. A `{repo}` placeholder was rejected: DevOps writes the
   config at ops-review, before the implement step, so a template using a
   placeholder the runner does not fill yet would refuse every stop in between.
3. **Warnings are advice everywhere.** A lint line whose message starts with
   `warn` or `warning` is never a routed item (`owners.FINDINGS`). This holds
   for every toolchain.
4. **The baseline only shrinks.** `fix` restores `.house-rules-baseline.json`
   from HEAD, then runs `house-rules baseline` without `--accept-new`, which
   refuses growth. Every role that changes Python has the file in its write
   scope, so the shrink lands in that step's commit. DevOps also owns
   `.house-rules.toml`.
5. **The scan skips the checkout's copies.** `.house-rules.toml` excludes
   `.team/run/**` and `.claude/worktrees/**`.

## Consequences

- A stop that adds a house-rules failure is refused; a gate routes one in
  another role's file as a gate fix; the quality step and both boundary checks
  fail on one, and an end failure goes to DevOps's team-fix step.
- The fix runs a whole-repo `baseline` at each `done` stop that changed Python
  (seconds). If the tree holds a new finding anywhere, the shrink waits for a
  later step; stale entries only warn.
- Known limit: a step that edits only the baseline and no Python skips the
  stop's lint check, so a hand-added entry there is caught by the code review,
  not by code. Closing it needs house-rules to compare the baseline with a git
  ref (a house-rules story).
- The config is POSIX-`sh` specific (`$PWD`), like the rest of this repo's
  toolchain; the human runs the team on macOS.
- The runner reads the config at start, so the new commands and scopes apply
  from its next start.

## Amended by s168 (2026-10-20)

**Context.** The s157 e2e test built its scratch repo by symlinking the whole
`house-rules/` directory. In a checkout with no `house-rules/runner/.venv` (every
new story worktree), the first `uv run --project house-rules/runner` made that
venv *in the checkout*, with console scripts naming the pytest temp path. Once
pytest pruned the temp dir, every later `test` and `coverage` gate in that
worktree failed.

**Decision.** 6. **A scratch repo never shares a tool's state directory with
the checkout.** A test that needs the checkout's house-rules project gives its
scratch repo a real `house-rules/runner/` directory and links only the
project's inputs into it (`house_rules/`, `pyproject.toml`, `uv.lock`); its
`.gitignore` is copied, because git doesn't follow a symlinked one. uv then
builds the venv in the scratch repo, and the editable install still runs the
checkout's source. `UV_PROJECT_ENVIRONMENT` (keeps the whole-dir link, so other
state can still leak) and a full copy (loses edits) were rejected.

**Consequences.** Each such test builds its own venv from uv's cache (about a
second). The rule is in `guidelines.md` under "Quality bar" and holds for any
future e2e test that links a project from the checkout.
