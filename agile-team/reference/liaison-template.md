# Liaison run state (template)

Copy this to `.team/run/liaison/LIAISON.md` when you first act as liaison for
a repo, then keep it current. It holds run state only. How to work as the
liaison is in `agile-team/SKILL.md` (and `reference/self-hosting.md` when the
team works on agile-team itself).

Read this first after a compaction or in a new session.

| Path | What it is |
|---|---|
| `JOB` | The job that runs the team, if any (name, deadline, resumes, auth). |
| `decisions.md` | Everything decided for the human, newest last. |
| `plans/` | Planning documents, one plan per file. |
| `reports/` | Reports written for the human, one file each (`<date>-<topic>.md`). |
| `messages/` | Every message sent to the PO (`agile-team tell`). |
| `shares/` | Every file shared with the team (`agile-team share`), as queued requests `f<N>.json`. |
| `watch.json` | What `agile-team watch` has already reported. |
| `backups/` | Copies kept from hand edits. |

## Sending things to the team

- A message for the PO: write it to a file, then `agile-team tell <file>`.
- A file the team must read (a mock, a spec): `agile-team share <file> --story <id>`.
  It lands in `<docs>/design/<id>-<file name>` in one runner commit, and the
  story file records its SHA-256. Acceptance fails if anyone changes it, so
  share a new version under the same name, and never copy it in by hand.

## This human's preferences (not in the skill)

- …

## Pending checks

- …
