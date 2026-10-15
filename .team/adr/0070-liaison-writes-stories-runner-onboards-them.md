# ADR-0070: The liaison writes stories; the runner onboards and commits them

**Date:** 2026-10-14 · **Story:** s135 · **Design:** `agile-team/docs/design/s135.md`

## Context

Until s135 the PO wrote `.team/stories/<id>.md` with `Write`, and `open_story`
registered it. The story file reached git as part of the PO's
`chore(team): product-owner step` commit, which no story records. The liaison
holds the most context on what the human asked for, but it may not commit in
the team's chain: the runner moves history (sprint-start rebase, story
reverts, review-stack rebuilds, salvage), and a commit made outside the runner
is in no story's record and can race a step. The human wants the liaison to
write each story and its ACs, the runner to check and commit them, and the PO
only to schedule (t99).

## Decision

1. **A validated queue, then a runner commit.** `agile-team story new` and
   `story amend` check a draft with `story_spec` (a `Kind.DRAFT` source: no
   `id`, no `shared`) and the run's state, then queue
   `.team/run/liaison/stories/q<N>.json` through the s134 `NumberedQueue`.
   They never write `.team/stories/` and never call git. The router's new
   `story_intake.Intake` settles the queue at each tick, after the share
   applier. It never runs while a boundary is open, except at the CI holds
   where the PO needs a bug story (`ci_failed`, `ci_infra`, `main_broken`).
2. **Story-file commits are a story's own record.** `StoryState.file_commits`
   lists the runner's commits of the story file: its creation and each amend.
   The sprint-start rebase remaps them, a story revert keeps them, and the
   snapshot lists them with the story's commits. They are **not** the story's
   first commit (`story.commit`), so `priority.started` is unchanged (a newly
   written story is not "in progress"), and `revert_story` leaves them alone
   (R4(b) matches `story.commit`'s subject). A reverted story goes back to the
   backlog with its story file.
3. **Authorship is data.** A request carries `approved_by` (`human` or
   `none`). `human` commits as the repo's git user (no `--author`); `none`
   commits as `LIAISON_AUTHOR` (`Claude (agile-team liaison)
   <noreply@anthropic.com>`). The subject is `docs(sN): created story to
   <title>` (an amend: `docs(sN): amended story to <title>`), and the body has
   `Human-involvement:` and `Liaison-request:` lines. `Git.commit_by(paths,
   Authored)` is the one place git gets an `--author`.
4. **Only the runner writes story files.** `.team/stories/**` joins
   `guard.RUNNER_FILES`: every role's `Write`/`Edit` there is refused, and a
   step's changes there are quarantined, whatever a role layer's `write:`
   globs say. The PO loses `open_story` and gains `request_story(summary,
   evidence)`, which posts a `story-request` message to the liaison's outbox.
5. **Placement reuses the PO's code.** The add-to-sprint checks and their
   effect move from `po_tools.Tools` to `sprint_add.SprintAdd`, which the
   PO's `add_to_sprint` and the intake both call. Order changes go through
   `Runtime.reorder` with a new `Source.LIAISON`.

## Consequences

- The story file in git is exactly the draft the liaison sent, with the
  runner's `id:` line added, in one commit whose author says who approved it.
- A team-found bug reaches a story only through the liaison: the PO calls
  `request_story`, the liaison writes it, the runner opens it and tells the
  PO its id. The CI hold flows (`record_ci_bug`) wait for that onboarding,
  which is why the intake runs at those holds.
- The many tests that used `open_story` to set up a story move to a test
  helper. Tests that pinned `open_story`'s own refusals retire with it. Their
  checks live on in the draft checks (`story new`) and the intake.
- `dependencies.Proposal` and `mismatch_refusal` go: the draft's own
  `depends_on` is the only list now, so there is nothing to compare it with.
- A role layer can no longer give any role write access to story files. A
  repo that wants the PO to write stories would need a new ADR.

## Amended by s136 (2026-10-14)

s136 writes the docs and role prose for this decision, and it settles three
points this ADR left open. None of them changes code.

- **Fixing a story file.** An AC's text or environment is fixed only by a
  `story amend` from the liaison (back to design). A story held because the
  config lost an environment is fixed in `.agile-team.toml`, then
  `continue_story`. A wrong `title` or `depends_on` (which `story amend`
  refuses to change) is the human's own edit and commit with the run
  stopped, as any hand edit to the repo is. The runner's texts
  `story_spec.STORY_FILE_HOLD` ("Edit the file; no state change is needed") and
  `cli.START_REFUSED` ("fix depends_on in .team/stories") still read as if
  a role edits the file. The docs say who acts. Rewording them is left to a
  follow-up story.
- **Stories the PO needs that are not bugs.** `request_story` requires
  failing output, so it is for bugs (a red CI run, a broken main, a runner
  fault, a check `ops-review` reports missing, where the ops-review row is
  the output). For any other story the PO needs, it asks the human with
  `ask_user`, and the liaison writes it.
- **Bug stories at a CI hold.** The boundary is open there, so a
  `--sprint current` add is refused and the story lands in the backlog. The
  docs tell the liaison to send these with `--sprint next`.
