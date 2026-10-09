# claude-skills

Personal [Claude Code](https://claude.com/claude-code) skills. Standalone and
self-contained — nothing here depends on the rest of my dotfiles, so it can be
cloned on its own.

## Layout

One directory per skill, each containing a `SKILL.md` with YAML frontmatter:

```
<skill-name>/
	SKILL.md          # name + description frontmatter, then the instructions
	reference/        # optional detail SKILL.md points Claude at
	runner/           # optional Python helper (a uv project with its own tests)
```

The `name` in the frontmatter should match the directory name, and the
`description` is what Claude matches against to decide whether a skill is
relevant — write it as "use this when…", listing concrete trigger phrases.
The rules for developing skills here are in
[`.claude/CLAUDE.md`](.claude/CLAUDE.md).

## Skills

| Skill | What it does |
|---|---|
| [`agile-team`](agile-team/SKILL.md) | Hands a large task to a headless team of specialized Claude roles (Product Owner, Architect, Developers, Testers, Reviewer, DevOps, Customer Proxy, Manager, Scribe) while the interactive session acts as liaison. Stories move from a backlog through sprints and a gated pipeline that the runner routes by itself, calling the PO only for judgement (a developer can send a story back to the unit-tester when a test contradicts the design), and end with the Integration Tester presenting each story to the Customer Proxy in a ready-made workspace. It runs on your Claude login or the repo's API key, and roles can use local models. `agile-team dashboard` serves a live view of the run. Details: [`reference/protocol.md`](agile-team/reference/protocol.md). |
| [`unattended`](unattended/SKILL.md) | Runs a long or expensive prompt or command as a background job that waits out Claude usage limits and resumes itself, within a deadline, a resume count and a cost cap. It runs on your login or an API key, and it can wrap `agile-team start`. Details: [`reference/protocol.md`](unattended/reference/protocol.md). |
| [`example-skill`](example-skill/SKILL.md) | Template showing the file format. |

Both skills need [uv](https://docs.astral.sh/uv/); their runners install their
own dependencies on first use. They run on your Claude Code login, or on an
API key from a key file (agile-team: `.team/run/api-key`; both:
`~/secrets/anthropic-api-key`, mode 600).

## Install

Claude Code reads personal skills from `~/.claude/skills/<skill-name>/`. The
install script symlinks every skill in this repo into place, so edits here take
effect immediately:

```sh
./install.sh            # symlink all skills into ~/.claude/skills
./install.sh --dry-run  # show what it would do
```

It only ever touches symlinks that point back into this repo, so it leaves
`~/.claude/skills/synced/` (skills synced from your Anthropic account) and any
hand-made skill directories alone.

On Windows, run it from Git Bash, or use directory junctions:

```powershell
New-Item -ItemType Junction -Path "$HOME\.claude\skills\<name>" -Target "<repo>\<name>"
```

### With chezmoi

If you manage dotfiles with chezmoi, declare this repo as an external and let a
`run_after_` script do the linking instead of running `install.sh` by hand. See
the `.chezmoiexternal.toml.tmpl` and `run_after_link-claude-skills.sh.tmpl` in
[devnu11/home](https://github.com/devnu11/home).

## Tests

```sh
sh tests/install_test.sh                         # install.sh
(cd agile-team/runner && uv run pytest --cov)    # agile-team runner
(cd unattended/runner && uv run pytest --cov)    # unattended runner
```

The install tests cover linking, idempotency (a second run changes nothing),
`--dry-run`, relinking, pruning, and leaving `synced/` and foreign links alone.
Each works in a scratch directory, never the real `~/.claude/skills`. CI runs
them on Linux (dash) and macOS (bash 3.2 as `/bin/sh`), plus shellcheck. Each
runner has its own CI workflow (ruff, and pytest with coverage of 95% or more).

## Writing a skill

See Anthropic's [skills documentation](https://docs.claude.com/en/docs/claude-code/skills).
Keep `SKILL.md` short — it is loaded into context when the skill triggers — and
push detail into supporting files the skill references by path.

## License

MIT — see [LICENSE](LICENSE).
