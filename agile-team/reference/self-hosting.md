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

## The runner re-pins itself at each sprint end

You rarely re-pin by hand. When a sprint's end-of-sprint full check passes,
the pinned runner re-pins itself to the head it just checked. It releases
`runner.pid`, runs `pin-runner.sh <head>`, runs `config check` under the new
pin, then replaces its own process (`os.execv`, same pid) with the new pin's
`start --resume`. The unattended job never sees an exit. The old pin stays in
`.team/run/runner-pin.prev`. If the pin, the check or the new runner's first
start fails, the runner rolls back to the old pin, carries on, and posts an
`update` saying why. Each re-pin is a `runner-repin` event, and the
dashboard header shows `pin <sha7>`. Details: "Self re-pin" in `protocol.md`.

The exec runs `.team/run/runner-pin/.venv/bin/agile-team`, uv's default
project venv. Don't set `UV_PROJECT_ENVIRONMENT` for the job, or every re-pin
rolls back.

## Re-pinning by hand

- **Only accepted code.** Pin a commit whose stories the Customer Proxy
  accepted and whose checks pass, never a commit in the middle of a story.
- **Only with the team stopped.** Run `$AT stop` (or `stop --now`), wait for
  the runner to exit (`$AT status` shows `"running": false`), re-pin, then
  `$AT start --resume`. The script refuses while `runner.pid` is alive.
- **Roll back** with `sh agile-team/runner/scripts/pin-runner.sh --rollback`
  (team stopped). It swaps `runner-pin.prev` back in and keeps the replaced
  pin as `runner-pin.failed`.
- **Restart the dashboard** after a re-pin if it runs from the pin. It is
  read-only and never needs the team stopped.

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
- Sprint-end re-pins happen inside the job and need nothing from you. A
  re-pin by hand doesn't change the job either: stop the job
  (`$UN stop <job>`), stop the team, re-pin, then `$UN resume <job>`.
- `start --resume` keeps the run's cadence, so `until-blocker` survives
  every resume and re-pin.
- When the run does stop, the job's `reason` says why:
  `agile-team blocked: <reason>`, `agile-team done: …`, `agile-team idle: …`,
  or `exit code N; agile-team halted: <reason>`.

## What stays off limits

`.claude/` is the human's (their repo instructions and jobs). The team never
writes it. The liaison may suggest that the human add one line to
`.claude/CLAUDE.md` pointing here, for example: "The agile team runs on the
pin in `.team/run/runner-pin`; see `agile-team/reference/self-hosting.md`."
