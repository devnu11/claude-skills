# ADR-0073: Roles read the repo's `.claude/CLAUDE.md` as text, never as settings

**Date:** 2026-10-15 · **Story:** s142 · **Design:** `agile-team/docs/design/s142.md`

## Context

Every role session runs with `setting_sources=[]` (ADR-003, lean context), so
Claude Code loads no `CLAUDE.md`, settings, hooks or permissions for it. The
human writes the repo's rules once, in `.claude/CLAUDE.md`. The team never
sees them, so `.team/CLAUDE.md` (the charter) repeats several of them, and
the copies drift. The human wants the checked-in rules to reach every role
the way they reach the human. The human does not want the machine's home
`~/.claude/CLAUDE.md` loaded (t104). Turning on the `project` setting source
would load the file. It would also load `.claude/settings.json`, its hooks
and its permissions, which would fight the runner's own guard and Stop hook.

## Decision

- The runner reads `<repo>/.claude/CLAUDE.md` itself
  (`agile_team/instructions.py`, `repo_instructions`). `RoleBook.system_prompt`
  puts it in a `## Repo instructions` section between the role body and the
  `## Repo charter`. The protocol's order "nothing else is added" gains this
  one section.
- `@path` imports are inlined only when they resolve inside the repo, relative
  to the importing file. Each file is inlined at most once per prompt, which
  also ends cycles. A `~` path, or a path that resolves outside the repo, is
  replaced by a one-line `(left out: … points outside the repo)` note. `~` is
  never expanded. A token that is not a file is left as text. Imports inside
  backtick code are ignored.
- Only the text is loaded. `setting_sources` stays `[]`. No home file is read.
- The charter keeps only what is about the team and drops what
  `.claude/CLAUDE.md` now says for it. The liaison edits it, because no role's
  file scope holds it.

## Consequences

- A rule written once in `.claude/CLAUDE.md` reaches every role, including the
  PO. Every role pays for its tokens on every call, so that file should stay
  short.
- A rule the human keeps in the home `~/.claude/CLAUDE.md` does not reach the
  team. To share one, the human copies it into the repo file or into a file the
  repo file imports.
- Changing `.claude/CLAUDE.md` changes the next step's prompt with no runner
  change. It remains the human's file. The team never writes it.
- Only `.claude/CLAUDE.md` is read. A root `CLAUDE.md`, `CLAUDE.local.md` and
  `.claude/rules/` would each need a story.
