# claude-skills

Personal [Claude Code](https://claude.com/claude-code) skills. Standalone and
self-contained — nothing here depends on the rest of my dotfiles, so it can be
cloned on its own.

## Layout

One directory per skill, each containing a `SKILL.md` with YAML frontmatter:

```
<skill-name>/
	SKILL.md          # name + description frontmatter, then the instructions
	reference.md      # optional supporting files the skill can point Claude at
	scripts/          # optional helper scripts
```

The `name` in the frontmatter should match the directory name, and the
`description` is what Claude matches against to decide whether a skill is
relevant — write it as "use this when…", listing concrete trigger phrases.

## Skills

| Skill | What it does |
|---|---|
| [`agile-team`](agile-team/SKILL.md) | Hands a large task to a headless team of specialized Claude roles (Product Owner, Architect, Developers, Testers, Reviewer, DevOps, Customer Proxy, Scribe…) billed to the repo's own API key. Individual roles can run on a local or other Anthropic-compatible model. The interactive session only relays the Product Owner's questions. Runner: [`agile-team/runner`](agile-team/runner) (Python Agent SDK, `uv`); protocol: [`reference/protocol.md`](agile-team/reference/protocol.md). |
| [`unattended`](unattended/SKILL.md) | Runs a long or expensive prompt or command as a background job. When the job hits a Claude usage limit, it saves its session, waits for the reset and resumes itself. A deadline, a maximum number of resumes and a cost cap stop it. Prompt jobs inherit your Claude Code settings and run on your login or an API key. A command signals a limit by exiting 75, which is what `agile-team start` already does. `unattended wait` blocks until the job ends, so a Claude session can be notified. Runner: [`unattended/runner`](unattended/runner) (Python Agent SDK, `uv`); protocol: [`reference/protocol.md`](unattended/reference/protocol.md). |
| [`example-skill`](example-skill/SKILL.md) | Template showing the file format. |

`agile-team` needs [uv](https://docs.astral.sh/uv/) and an Anthropic API key
(per repo in `.team/run/api-key`, or `~/secrets/anthropic-api-key`, mode 600).
The runner installs its own dependencies on first use. Its tests:

```sh
cd agile-team/runner && uv run pytest --cov
```

`unattended` needs [uv](https://docs.astral.sh/uv/), plus an API key only for
`--auth api-key`. Its tests:

```sh
cd unattended/runner && uv run pytest --cov
```

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
sh tests/install_test.sh
```

Covers linking, idempotency (a second run changes nothing), `--dry-run`,
relinking, pruning, and leaving `synced/` and foreign links alone. Each test
works in a scratch directory, never the real `~/.claude/skills`. CI runs it on
Linux (dash) and macOS (bash 3.2 as `/bin/sh`), plus shellcheck.

## Writing a skill

See Anthropic's [skills documentation](https://docs.claude.com/en/docs/claude-code/skills).
Keep `SKILL.md` short — it is loaded into context when the skill triggers — and
push detail into supporting files the skill references by path.

## License

MIT — see [LICENSE](LICENSE).
