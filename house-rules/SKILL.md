---
name: house-rules
description: Check Python code against the human's code rules as code - no code in the global scope, short functions, at most 2-3 parameters, no boolean parameters, verb-named functions and noun-named properties - with a baseline that may shrink but never grow. Use when the user says "check the house rules", "check my coding standards", "lint against my rules", "set up house-rules", "add the house-rules hook", "baseline the violations", or asks whether code follows their CLAUDE.md code style.
---

# house-rules

A uv runner that checks Python files against the human's global code rules
(`~/.claude/CLAUDE.md`, "Code style"). Each rule is a row in one table; every
limit and list is repo-configurable. The rules and how they count are in
`reference/rules.md` next to this file. Read it before changing a repo's
settings or arguing with a finding.

```sh
HR="uv run --frozen --quiet --project ~/.claude/skills/house-rules/runner house-rules"
```

`--frozen` runs the skill's tested `uv.lock` as it is; never drop it.

## Commands

| Command | What it does |
|---|---|
| `$HR check [paths…]` | Check the repo (or the paths). Exit 0 clean or warnings only, 1 new failures, 2 config or git error. |
| `$HR check --changed main` | Only files changed against `main`. |
| `$HR check --staged` | The staged content (for a pre-commit hook). |
| `$HR check --format json\|github` | For tools, or GitHub annotations in CI. |
| `$HR baseline` | Shrink the baseline after fixes. Refuses to record anything new. |
| `$HR baseline --accept-new` | Record today's violations when adopting the tool on a repo. Ask the human first. |
| `$HR rules` | The rules with this repo's limits. |

## Steps

1. **Run `check`** from the repo root. Report failures by file. Warnings are advice.
2. **Fix, don't suppress.** A suppression needs a reason a reviewer can disagree with:
   `# house-rules: allow <rule> -- <reason>` on the `def` line (ruff's
   `# noqa: FBT001 -- <reason>` also works for the rules ruff shares).
3. **After fixing baselined code**, run `baseline` so the ratchet tightens.
4. **Adopting it on a repo:** add `.house-rules.toml` (or `[tool.house-rules]`),
   then `baseline --accept-new` with the human's OK, and commit both.

## Hooks

- **Claude Code** (any session): add to `settings.json`. Exit 2 shows Claude
  the findings in the file it just wrote:
  ```json
  {"hooks": {"PostToolUse": [{"matcher": "Edit|Write|MultiEdit",
    "hooks": [{"type": "command",
      "command": "uv run --frozen --quiet --project ~/.claude/skills/house-rules/runner house-rules hook"}]}]}}
  ```
  The human's global `settings.json` is chezmoi-managed: propose the change; don't apply it.
- **pre-commit** (per repo): `.git/hooks/pre-commit` containing
  `exec uv run --frozen --quiet --project ~/.claude/skills/house-rules/runner house-rules check --staged`.
- **CI**: `house-rules check --format github` (see `.github/workflows/house-rules.yml`).

Naming judgement beyond the first word (whole words, no alias variables, a
verb that adds nothing) stays with the reviewer.
