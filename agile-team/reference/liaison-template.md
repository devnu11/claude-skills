# Liaison run state (template)

Copy this to `.team/run/liaison/LIAISON.md` when you first act as liaison for
a repo, then keep it current. It holds run state only. How to work as the
liaison is in `agile-team/SKILL.md` (and `reference/self-hosting.md` when the
team works on agile-team itself).

Nothing builds a liaison kit from this file: the runner never reads or copies
it. The liaison copies it by hand, once per repo. The commands fill in
their own entries below (`messages/` for `tell`, `shares/` for `share`,
`stories/` for `story`, `watch.json` for `watch`); the rest is yours.

Read this first after a compaction or in a new session.

| Path | What it is |
|---|---|
| `JOB` | The job that runs the team, if any (name, deadline, resumes, auth). |
| `decisions.md` | Everything decided for the human, newest last. |
| `plans/` | Planning documents, one plan per file. |
| `reports/` | Reports written for the human, one file each (`<date>-<topic>.md`). |
| `messages/` | Every message sent to the PO (`agile-team tell`). |
| `shares/` | Every file shared with the team (`agile-team share`), as queued requests `f<N>.json`. |
| `stories/` | Every story sent to the team (`agile-team story new` / `story amend`), as queued requests `q<N>.json`. |
| `drafts/` | Your story drafts, one file each (yours; nothing reads them but `story`). |
| `watch.json` | What `agile-team watch` has already reported. |
| `backups/` | Copies kept from hand edits. |

## Sending things to the team

- A message for the PO: write it to a file, then `agile-team tell <file>`.
- A file the team must read (a mock, a spec): `agile-team share <file> --story <id>`.
  It lands in `<docs>/design/<id>-<file name>` in one runner commit, and the
  story file records its SHA-256. Acceptance fails if anyone changes it, so
  share a new version under the same name, and never copy it in by hand.

## Writing stories

You write every story; the runner commits it. Never write or commit a file
in `.team/stories/` yourself, and no role can.

- **A new story.** Write a draft (for example `drafts/<slug>.md`):

  ```markdown
  ---
  title: "Export the board as CSV"
  depends_on: [s83]          # optional
  acceptance:
    - id: AC1
      text: "agile-team export --csv prints one row per story."
      environment: cli       # the exact name of an [[environment]]
  ---
  As the human, I want the board as CSV, so I can share it.
  ```

  No `id` and no `shared`: the runner writes them. Other keys (`suite_runs:
  3` for a story that must prove a fix holds) are kept. Then:

  `agile-team story new <draft> --approved-by human|none [--sprint current|next|backlog] [--after sN] [--plan <path>]`

  It prints every problem at once and queues nothing, or prints
  `queued q<N>: …`. Between steps the runner gives the story its id, commits
  it as `docs(<id>): created story to <title>`, places it (`--sprint`,
  default the end of the backlog; `--after` puts it right after that story)
  and tells the PO. You get `Runner: story q<N> is <id>, commit <sha>, …`.
- **Who approved it.** `--approved-by human` only when the human approved
  this story; add `--plan <path>` when they approved a plan that holds it.
  The commit is then the human's. `--approved-by none` when you wrote it
  alone: the commit's author is the liaison, and its body says
  `Human-involvement: none: written and submitted by the liaison`.
- **New ACs for an open story.** Copy its `title` and `depends_on`
  unchanged, write the new `acceptance` list, then
  `agile-team story amend <id> <draft> --approved-by human|none [--plan <path>]`.
  Only the ACs change, in one `docs(<id>): amended story to <title>` commit,
  and the story goes back to design. The draft's body is not used. A wrong
  title or `depends_on` is the human's to fix by hand, with the run stopped.
- **Answering a `story-request`.** `watch` reports it as a `message` whose
  `kind` is `story-request`: the PO asks for a story, with a summary, the
  story and step where it showed, the files and the failing output. Relay it
  to the human. Write the story with them (`--approved-by human`), or alone
  when it only restates the evidence (`--approved-by none`). Put the evidence
  the team needs in the body. Send it with `story new`: `--sprint current`
  mid-sprint, `--sprint next` at a CI hold. The PO hears the id from the
  runner and schedules it; you don't answer the request itself.
- **Check the outcome.** `agile-team status` lists `queued_stories` and each
  request under `story_requests` (`opened …`, `amended …` or
  `refused: <why>`). A refused request is never retried: fix the draft and
  send it again.

## This human's preferences (not in the skill)

- …

## Pending checks

- …
