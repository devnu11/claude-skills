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
| [`agile-team`](agile-team/SKILL.md) | Hands a large task to a headless team of specialized Claude roles (Product Owner, Architect, Developers, Testers, Reviewer, DevOps, Customer Proxy, Manager, Scribe) while the interactive session acts as liaison. Stories move from a backlog through sprints and a gated pipeline that the runner routes by itself, in an explicit priority order the PO sets (the board shows each story's position, and why a held story is waiting), calling the PO only for judgement (a developer can send a story back to the unit-tester when a test contradicts the design, and a setback that repeats for the same reason, or a story bouncing between the same two steps too often for any reason, goes to the Manager instead of looping), and end with the Integration Tester presenting each story to the Customer Proxy in a ready-made workspace (a web delivery is started and must answer before acceptance begins). Each sprint starts by merging upstream main into the team branch (never rewriting it) and running the full checks, and ends with the sprint's work rebased onto the latest main, checked, and pushed as a stacked PR: the bottom one is open for review and the others are drafts that CI skips. The sprint ends only when the bottom PR's CI is green, which is the only time a PR is called ready to merge, or when a bug story is opened for the failing checks. Only the runner runs the full suite and coverage: roles get the results in their briefs, a full test or coverage run from a role's shell is denied, and developers ask the runner for named tests. Permission to push is asked once. A step cut off by a limit, a crash or a kill keeps its edits in a reverted commit that the next step on the story is offered, and `status` reports `interrupted` rather than `running` when the runner is dead. The budget is a ceiling: when spend reaches it, the run halts (`blocked`, exit 77) until you raise it and resume, and `status`, the dashboard and the team all see the same spend, with the PO's early overcount corrected. If anyone else moves the checkout under the runner (another branch, a detached HEAD, a reset, a foreign commit, a rebase in progress), it halts at once (`checkout-changed`, exit 78) and asks you; `accept-checkout` keeps the new HEAD. It runs on your Claude login or the repo's API key, and roles can use local models. Each session's context is kept small: the PO's session is renewed at every sprint start and finished story, and no role loads your claude.ai connectors. `agile-team dashboard` serves a live view of the run, including turns and context per step, and a live spend pill that turns red (with a desktop notification on localhost) when turns stop, the heartbeat goes stale or the run halts. `agile-team tell` queues a message for the PO from a file (a running team gets it after the current step, a stopped one on resume), and `agile-team watch` waits without spending tokens and prints one JSON line when a new message or a status change needs you. So an unattended job's resume command is plain `agile-team start --resume`, and the runner saves a cut-off step's edits itself. Installed skills run with `uv run --frozen` and CI with `--locked`, so the tested lock is what runs. To let the team work on agile-team itself, run it on a pinned copy of the runner ([`reference/self-hosting.md`](agile-team/reference/self-hosting.md)). Details: [`reference/protocol.md`](agile-team/reference/protocol.md). |
| [`unattended`](unattended/SKILL.md) | Runs a long or expensive prompt or command as a background job that waits out Claude usage limits and resumes itself, within a deadline, a resume count and a cost cap. It runs on your login or an API key, and it can wrap `agile-team start`. It waits out network failures without spending tokens and keeps the machine from idle-sleeping (`--allow-sleep` opts out). Details: [`reference/protocol.md`](unattended/reference/protocol.md). |
| [`six-hats`](six-hats/SKILL.md) | Works through a decision or problem with de Bono's Six Thinking Hats, one hat at a time: Blue frames it and picks a sequence for the job (choose between options, judge one idea, solve a problem, generate ideas, quick check), then White, Red, Black, Yellow and Green, and Blue closes with a recommendation, the risks carried forward and the open questions. Runs solo or with the user adding points at each hat. Details: [`reference/hats.md`](six-hats/reference/hats.md), [`reference/sequences.md`](six-hats/reference/sequences.md). |
| [`example-skill`](example-skill/SKILL.md) | Template showing the file format. |

`agile-team` and `unattended` need [uv](https://docs.astral.sh/uv/); their
runners install their own dependencies on first use. `six-hats` is
instructions only. They run on your Claude Code login, or on an
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
