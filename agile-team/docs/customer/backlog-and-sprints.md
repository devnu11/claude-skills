# Backlog and sprints

The team keeps every story it has written in a **backlog**. A story only
moves through the pipeline (design → ops review → tests → implement → … → acceptance) once
the Product Owner commits it to a **sprint**. The runner enforces this, so
the board always shows what is planned and what is in progress.

## What you see

`agile-team status` prints each story with its `sprint`:

```json
{
  "status": "running",
  "sprint": 2,
  "stories": {
    "s1": {"id": "s1", "title": "Export a report as CSV", "step": "acceptance",
           "status": "done", "sprint": 1, "...": "..."},
    "s2": {"id": "s2", "title": "Choose which columns to export", "step": "review",
           "status": "active", "sprint": 2, "...": "..."},
    "s5": {"id": "s5", "title": "Export through the HTTP API", "step": "design",
           "status": "active", "sprint": null, "...": "..."}
  }
}
```

- `"sprint": 2` at the top is the current sprint.
- A story with `"sprint": null` is in the backlog. It waits until a sprint
  takes it.
- A done story keeps the number of the sprint it finished in.

## How a sprint is formed

The Product Owner starts each sprint with a goal and the list of stories it
commits to. The team's Manager then reviews that scope against the budget.
Unfinished stories that the new sprint does not list go back to the backlog.
To add a story halfway through, the PO adds it to the running sprint with
`add_to_sprint` and a reason. The sprint keeps its number, goal and review
branch, no Manager turn runs, and the story lines up first among the
stories not yet started. It joins the sprint's review PR like the others.
The PO starts a new sprint only when the sprint's stories are done or you
ask for one. Restarting with unfinished stories needs a reason.

## When a sprint ends

A sprint ends only when every story in it is **done**, **cancelled** (only
you can cancel) or **reverted** (the PO's call). The runner refuses the PO's
"sprint end" note before then. The refusal names each unfinished story and
its step, so no review PR carries half-built work.

If everything left in the sprint is stuck, for example waiting on your
answer, the runner shows the PO the backlog stories that are ready to run.
The PO adds them to the sprint, so the team keeps working instead of
stopping.

### Reverting a story

When a story's work has to come out, the PO reverts it. The runner then:

- undoes the story's commits on the team branch in one commit,
  `revert(s7): <title>`, and puts the story back in the backlog before its
  tests step;
- adds a "Reverted" entry to the story file: the date, the sprint, the
  reason, the commits undone and the revert commit;
- shows `reverted (1×)` on the story's Board card and Backlog row, adds a
  row to the timeline, and lists the story under "Reverted" in the sprint's
  review PR;
- tells every role that worked on the story, in its next brief, that it was
  reverted and why. The next design must say what changes this time;
- sends you an update naming the story, the reason and the commits.

The PO can't revert a story twice on its own. The second time, it asks you:
`Revert story s7 ("…") again? … Answer "revert" to revert it or "keep" to
keep it.` Until you answer, the card shows `⏸ revert requested: <reason>`.

## The order of work

The team works in an explicit order, not in the order stories were written.
Tell the Product Owner the order you want ("gate fixes first: s24, s30, s26;
then s37"). The PO records it, and the runner follows it:

- Work already committed is finished first. Stories with commits go before
  stories not started, and your order ranks the stories within each group.
- A started story that is waiting (on your answer, the Manager or the round
  cap) moves behind the started stories that can run, but still before the
  stories not started. It is skipped until it is released, then it goes
  back to its place.
- A story that is not in the order yet comes after the ones that are, in
  its group.
- To start a new story before the started ones finish, tell the Product
  Owner why. The PO pulls it ahead with that reason, and the timeline shows
  it. Without a reason the runner refuses.

On the dashboard's **Board**, every column lists stories in that order, and
each card shows its position (`#1` is next). A waiting story shows
`⏸ PO hold: …`, `⏸ cancel requested: …`, `⏸ questions`, `⏸ manager`,
`⏸ round cap`, `⏸ needs the human` or `⏸ held`,
with a `waits on:` line naming the question (for example `m38: …`) or the
reason. Each change to the order appears in the timeline as a **priority**
row: who moved what (the Product Owner, or `human (dashboard)`), from which
position to which, and why.

You can also reorder the backlog yourself on the dashboard's **Backlog**
tab: move a story up, down or to the top, or drag it. Only stories outside
the current sprint move. The runner applies your move between steps and
tells the Product Owner at its next turn. From then on your backlog order
binds the PO: a change to it without a reason is refused, and the reason
appears in the timeline.

### Holding and cancelling a story

The Product Owner can set a story aside without asking you anything:

- **Hold.** The PO holds a story with a reason. The card shows `⏸ PO hold:
  <reason>` (for example `⏸ PO hold: waits on s38`). The team skips the
  story, but it keeps its place in the order and its `#position`.
- **Release.** The PO releases a held story, or a blocked one with no open
  question, and the reason goes to the next step's brief. If a question of
  yours is open on that story, the PO is told to pass on your answer
  instead.
- **Cancel request.** Only you can cancel a story. When the PO thinks a
  story should go, it asks you one question: `Cancel story s7 ("…")? The
  PO asks because: … Answer "cancel" to cancel it or "keep" to keep it.`
  Until you answer, the card shows `⏸ cancel requested: <reason>`. For a
  story that already has code, the reason says what happens to that code.

Answer `cancel` and the story is cancelled: it leaves the order and its
sprint, and the team never runs it again, even after a restart. Its story
file and commits stay. Answer `keep` and the story carries on. Any other
answer leaves the story held for the PO, which can release it or ask
again. Each hold, release, request and answer shows in the timeline as a
**story-admin** row with the reason.

The **Backlog** tab lists cancelled stories in a **Cancelled** group after
Backlog. They have a `cancelled` pill and can't be moved. A story that
depends on a cancelled one keeps waiting until the PO edits its
dependencies.

### What a story file holds

Each story is a file, `.team/stories/<id>.md`. Its frontmatter lists the
acceptance criteria, and each one says where the customer tries it: the name
of one of your `[[environment]]` rows in `.agile-team.toml`.

Only the runner writes story files. The liaison writes a draft and submits
it; the Product Owner schedules stories but can't write them:

```
agile-team story new draft.md --approved-by human --sprint current
agile-team story amend s120 draft.md --approved-by none
```

A draft has a `title`, the `acceptance` list and an optional `depends_on`,
with the user story as the body. It has no `id`: the runner gives it one.
The command checks the draft and lists every problem, or queues it and
prints its queue id (`q3`). Between steps, the runner gives a new story the
next id and writes its file. It commits the file as
`docs(s121): created story to <title>`, and places the story: in the running
sprint (`current`), first in the backlog (`next`), or last in the backlog
(`backlog`, the default). `--after s119` puts it right after s119. Then it
tells the Product Owner. With `--approved-by none`, the commit's author is
the liaison. With `human`, it is your git user. Its `Human-involvement:`
line says which (`--plan <path>` names the plan you approved).

`story amend` replaces a story's acceptance criteria in one commit, then
sends the story back to design. When the team finds a bug it couldn't fix,
the Product Owner asks the liaison for a story (`request_story`). The story
commits belong to the story: a revert of the story keeps its file.

```yaml
---
id: s120
title: "Export the board as CSV"
acceptance:
  - id: AC1
    text: "agile-team export --csv prints one row per story."
    environment: cli
  - id: AC2
    text: "The Backlog tab has an Export button that downloads the same CSV."
    environment: dashboard
---
```

A story whose criteria name two environments touches both, and the Customer
Proxy tries it in both, one after the other in the order of your config.
Each try sees only that environment's criteria. Every environment runs even
when an earlier one fails; the story passes only when all pass, and
otherwise goes back once, naming every failed environment and criterion.
After the fix, every environment is tried again.
`story new` refuses a draft with a missing or unknown environment, a
missing or repeated criterion id, or YAML it can't read. The refusal names
the file, the criterion and the problem. To move a criterion to another
environment, use `story amend`. The runner reads the story file again
before the Customer Proxy's turn, and holds the story until a bad file is
fixed.

### Stories that depend on others

When a story needs other stories done first, the liaison's draft lists them
in `depends_on`, which the story file keeps:

```yaml
---
depends_on:
  - s31  # hooks
---
```

The runner won't run any step of that story until every story it lists is
done. If the sprint can't go on, the Product Owner is told why, for
example `s32 at design: waiting on s31`. The fix is to add s31 to the sprint
or change the file. The runner checks the lists each time a run or a sprint
starts. A list that names an unknown story, the story itself or a loop
(`s1 -> s2 -> s1`) stops the start and names the stories. Moving a story
above one it depends on is allowed, but the Backlog tab and the timeline
warn about it.

`agile-team status` shows the stories in the order they were created. The
Product Owner's `story_status` and the dashboard show the priority order.

## Resuming an older run

If you resume (`start --resume`) a run that began before backlogs existed,
every story starts in the backlog. Steps already done are kept. The Product
Owner sees this at once and starts a sprint with the stories to continue.
That costs one extra Manager review.
