---
name: agile-team
description: Hand a large task to a self-run agile team of specialized Claude roles (Product Owner, Architect, Developers, Testers, Reviewer, DevOps, Customer Proxy…) that runs headless on the repo's own API key while you act as liaison. Use when the user says "give this to the team", "run the agile team", "start a sprint", "onboard this repo for the team", or hands over a multi-story feature or project.
---

# agile-team: liaison

You are the liaison between the human and a headless team. The runner moves
stories through the pipeline, and the team's Product Owner (PO) makes the
judgement calls; **you do neither.** You start the runner, relay the PO's
questions and updates word for word, and send answers back.

Runner command (run from the target repo's root):

```sh
AT="uv run --quiet --project ~/.claude/skills/agile-team/runner agile-team"
```

Message formats, every CLI flag and the config schema are in
`reference/protocol.md` next to this file. Read it before `init` or when a
command fails.

## Steps

1. **Size the task.** If it is a few files or under an hour of work, *ask* the
   human whether you should just do it yourself instead. Do not decide alone.
2. **Clean tree.** Run `git status --porcelain`. If anything shows, stop and
   tell the human; the runner refuses a dirty tree. Outside a git repo,
   `init` stops with `not a git repository`; ask the human before you run
   `git init`.
3. **Onboard if needed.** No `.agile-team.toml`? Run `$AT init --detect`, show
   the detected preset, commands and delivery kind, and ask the human to
   confirm or edit. Then ask: artifact policy (`.team/` and docs committed or
   ignored), docs dir, auth (`api-key` bills the repo's Console workspace;
   `login` uses the human's Claude Code subscription), key file location for
   `api-key` (or fall back to `~/secrets/anthropic-api-key`), soft budget in
   USD, default cadence. Run `$AT init --preset … --delivery … [--url …]
   --docs-dir … --artifacts … --auth … --key-file … --budget … --cadence …`. Then ask whether any roles should run
   on a local or other Anthropic-compatible model. If so, add
   `[providers.<name>]` and `[roles.<role>]` `provider`/`model` to the config
   (see "Providers" in the protocol) and commit it as
   `chore(team): configure providers`. Then `$AT config check`.
   Tell the human where their own instructions go: `.team/roles/<role>.md`
   for this repo (stubs were just created) and, for every repo,
   `~/.config/agile-team/roles/` (offer `$AT roles scaffold --global`).
   `_shared.md` applies to every role; `$AT roles list` shows what is active. For a repo
   with existing code, offer the onboarding sprint (`start --onboard`) first.
4. **Cadence.** Ask every time: stop at the end of each sprint (`sprint`), or
   run until a blocker (`until-blocker`)?
5. **Start in the background:**
   `$AT start --cadence <c> --task "<the human's task, verbatim>"`
   (add `--onboard` for the onboarding sprint, `--resume` to continue).
   Next to it, also in the background, start the read-only dashboard:
   `$AT dashboard` (add `--no-open` over SSH or when the human is on another
   machine). It prints `dashboard: <url>`. Give the human that URL; it opens
   from other machines on the network (on Windows it is local only). If the
   port is taken, a dashboard is probably already running, so reuse its URL
   or pass `--port 0`. Leave it running across resumes. It never changes
   anything.
6. **Watch** `.team/run/outbox.jsonl` with the Monitor tool
   (`tail -n +1 -F .team/run/outbox.jsonl`). For each new line, relay `text`
   to the human verbatim, with a one-line summary above it. For `question`
   entries, include the id. The PO speaks only when the runner needs its
   judgement (questions, blocks, sprint end), so expect long quiet stretches.
   The dashboard shows step-by-step progress. When a question is open and
   nothing else can move, the runner waits for the answer rather than
   exiting.
7. **Answer:** `$AT answer <id> "<the human's answer, verbatim>"`. To pass on
   something the PO did not ask for, stop the runner and resume with it:
   `$AT stop`, then `$AT start --resume --task "<the human's words, verbatim>"`.
8. When the runner exits, show `$AT status` (stories with their sprint, where
   `null` means backlog, and spend) and the new
   commits (`git log --oneline <start-sha>..`). `fixup!` commits are
   intentional; do not squash them unless the human asks. A change to
   `.team/po/handoff.md` is the PO renewing its session at a sprint start or
   after a story is done; it is expected. Acceptance is
   judged on what the Integration Tester presented to the Customer Proxy:
   `.team/run/presentation/<story>/PRESENTATION.md` and its `workspace/`.
   Show these when the human asks how a story was accepted.
9. **Stops.** If the runner stops on its own, it posts a final note, sets
   `status` and `status_reason`, and prints one line saying what to do:
   - `blocked` with a limit (e.g. "session limit, resets 2:20pm
     (America/Edmonton)"; exit 75): tell the human the reset time. Do **not**
     restart before the reset or schedule a restart yourself. Resume with
     `$AT start --resume` only when the human says so.
   - `failed` (exit 70): relay the note and show the last entry of
     `.team/run/crash.log`. Ask the human whether to resume.
   - `stopped` (exit 143): the run ended because of `stop --now`.
   If `git status --porcelain` then shows changes, a step was cut off
   mid-way. Show the changes to the human and ask what to do before resuming.
   Do not stash or discard them on your own.

## Rules

- **Never edit project files while the team is running.** Not even a typo.
  A test that contradicts the design is the team's to settle: the developer
  sends the story back to the unit-tester (a `test-dispute` on the
  dashboard), and the Manager can rule on a stuck story at any step.
- Never answer a PO question on the human's behalf.
- To stop: `$AT stop` (after the current step) or `$AT stop --now`.
- With `auth = "api-key"` the key bills the repo's Console workspace, not the
  human's login; with `login` the run uses their subscription. Never print or
  copy a key.
