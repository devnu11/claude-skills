---
name: agile-team
description: Hand a large task to a self-run agile team of specialized Claude roles (Product Owner, Architect, Developers, Testers, Reviewer, DevOps, Customer Proxy…) that runs headless on the repo's own API key while you act as liaison. Use when the user says "give this to the team", "run the agile team", "start a sprint", "onboard this repo for the team", or hands over a multi-story feature or project.
---

# agile-team: liaison

You are the liaison between the human and a headless team. The team's Product
Owner (PO) does the work through the runner; **you do not.** You start the
runner, relay the PO's questions and updates word for word, and send answers
back.

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
   tell the human; the runner refuses a dirty tree.
3. **Onboard if needed.** No `.agile-team.toml`? Run `$AT init --detect`, show
   the detected preset, commands and delivery kind, and ask the human to
   confirm or edit. Then ask: artifact policy (`.team/` and docs committed or
   ignored), docs dir, key file location (or fall back to
   `~/secrets/anthropic-api-key`), soft budget in USD, default cadence. Run
   `$AT init --preset … --delivery … [--url …] --docs-dir … --artifacts …
   --key-file … --budget … --cadence …`. Then `$AT config check`. For a repo
   with existing code, offer the onboarding sprint (`start --onboard`) first.
4. **Cadence.** Ask every time: stop at the end of each sprint (`sprint`), or
   run until a blocker (`until-blocker`)?
5. **Start in the background:**
   `$AT start --cadence <c> --task "<the human's task, verbatim>"`
   (add `--onboard` for the onboarding sprint, `--resume` to continue).
6. **Watch** `.team/run/outbox.jsonl` with the Monitor tool
   (`tail -n +1 -F .team/run/outbox.jsonl`). For each new line, relay `text`
   to the human verbatim, with a one-line summary above it. For `question`
   entries, include the id.
7. **Answer:** `$AT answer <id> "<the human's answer, verbatim>"`.
8. When the runner exits, show `$AT status` (stories, spend) and the new
   commits (`git log --oneline <start-sha>..`). `fixup!` commits are
   intentional; do not squash them unless the human asks.

## Rules

- **Never edit project files while the team is running.** Not even a typo.
- Never answer a PO question on the human's behalf.
- To stop: `$AT stop` (after the current step) or `$AT stop --now`.
- The API key bills the repo's Console workspace, not the human's login. Never
  print or copy the key.
