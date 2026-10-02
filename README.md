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

## Writing a skill

See Anthropic's [skills documentation](https://docs.claude.com/en/docs/claude-code/skills).
Keep `SKILL.md` short — it is loaded into context when the skill triggers — and
push detail into supporting files the skill references by path.

## License

MIT — see [LICENSE](LICENSE).
