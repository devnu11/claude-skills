# Backlog and sprints

The team keeps every story it has written in a **backlog**. A story only
moves through the pipeline (design → tests → implement → … → acceptance) once
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
To add a story halfway through, the PO starts a new sprint that lists it
along with the stories still in progress.

## Resuming an older run

If you resume (`start --resume`) a run that began before backlogs existed,
every story starts in the backlog. Steps already done are kept. The Product
Owner sees this at once and starts a sprint with the stories to continue.
That costs one extra Manager review.
