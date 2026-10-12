# Self-hosting: the team working on agile-team itself

Development only. This applies when the repo the team works on is the one
that holds the agile-team runner (`claude-skills`). Every other repo runs the
installed skill (`~/.claude/skills/agile-team/runner`) and can skip this page.

## Why the team never runs on the working copy

The team edits `agile-team/runner/`. If the runner it runs on were that same
working copy, a developer's half-finished edit could change the running
program between two steps. The next `uv run` would also pick up an untested
change. The team then works on itself mid-step and breaks in ways no gate
sees. So the team always runs on a **pinned copy** of the runner, built from
a commit that was already accepted. That copy lives under `.team/run/`,
which is gitignored, and no role writes there.

## Pin

From anywhere in the repo, with the team stopped:

```sh
sh agile-team/runner/scripts/pin-runner.sh <commit>
```

It checks that `<commit>` is on the checked-out branch, that it has
`agile-team/runner`, and that no runner is alive. Then it builds
`.team/run/runner-pin/` from that commit (`git archive`) and writes the full
sha to `.team/run/runner-pin.commit`. It prints the command to run the pin:

```sh
AT="uv run --frozen --quiet --project .team/run/runner-pin agile-team"
```

`--frozen` installs exactly the pinned `uv.lock` and never rewrites it. The
first `uv run` builds the pin's venv.

## When to re-pin

- **Only accepted code.** Pin a commit whose stories the Customer Proxy
  accepted and whose checks pass, never a commit in the middle of a story.
  To pick up a runner fix the team just shipped, wait until its story is
  done.
- **Only with the team stopped.** Run `$AT stop` (or `stop --now`), wait for
  the runner to exit (`$AT status` shows `"running": false`), re-pin, then
  `$AT start --resume`. The script refuses while `runner.pid` is alive.
- **Restart the dashboard** after a re-pin if it runs from the pin. It is
  read-only and never needs the team stopped.
- Keep the old sha (from `runner-pin.commit`) in the liaison's decision log.
  Rolling back is a re-pin at that sha.

## Running under unattended

The job runs in the repo root (`--cwd`). Both commands go through the pin,
and the resume command is plain `start --resume`:

```sh
UN="uv run --frozen --quiet --project ~/.claude/skills/unattended/runner unattended"
$UN start agile-team-run --cwd "$PWD" \
  --command "uv run --frozen --quiet --project .team/run/runner-pin agile-team start --cadence until-blocker --task '<the task>'" \
  --resume-command "uv run --frozen --quiet --project .team/run/runner-pin agile-team start --resume"
```

- With `auth = "login"`, prefix both commands with `env -u ANTHROPIC_API_KEY`
  if the job's environment has a key. Preflight refuses login auth with a key
  set.
- Messages for the PO go through `$AT tell <file>`, never through the resume
  command. A running team gets them at the PO's next turn. A stopped one gets
  them on the next `start --resume`. So the resume command never changes.
- A step cut off by a kill or a checkout halt keeps its edits. The runner
  saves them on `start --resume` (see "Interrupted steps" in
  `protocol.md`). No wrapper should stash or clean the tree.
- Re-pinning does not change the job. Stop the job (`$UN stop <job>`), stop
  the team, re-pin, then `$UN resume <job>`.

## What stays off limits

`.claude/` is the human's (their repo instructions and jobs). The team never
writes it. The liaison may suggest that the human add one line to
`.claude/CLAUDE.md` pointing here, for example: "The agile team runs on the
pin in `.team/run/runner-pin`; see `agile-team/reference/self-hosting.md`."
