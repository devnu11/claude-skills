# Who moves the work: the runner, and the Product Owner for judgement

Every story goes through the same pipeline: design → tests → implement →
quality → review → design review → e2e → acceptance. The **runner** moves
each story along that pipeline by itself. It starts the right role for each
step and gives it a standard brief: the story file, the design, the review
file, what the previous step reported, and why the story came back, if it
did. The runner also runs the Manager when a review is due and the Scribe
after each story is done.

The **Product Owner** (PO) is called in only when a judgement is needed:

- a role asks a question, or reports that it is blocked or has failed;
- a step crashed, or changed files outside its scope;
- a story keeps bouncing and reaches the round cap;
- a reviewer sends work to a role that has no pipeline step (for example
  DevOps);
- the Manager made a ruling that could not apply (for example on a done
  story);
- you answered a question;
- the sprint is complete, or nothing can move.

The PO runs on Sonnet by default. Routing no longer goes through it, so the
run spends far less on the PO than before.

## What you notice

- **Fewer messages.** The PO writes to you at milestones and when it needs
  you, not after every step. For step-by-step progress, use the dashboard
  (`agile-team dashboard`).
- **The runner waits for your answers.** When the PO has asked you something
  and nothing else can move, the runner keeps running and picks up the moment
  you answer (`agile-team answer <id> "<text>"`). To end the run instead, use
  `agile-team stop`.
- **Held stories.** `agile-team status` shows `"hold"` on a story that the
  runner has handed to the PO, for example `"hold": "questions"`. The story
  moves again once the PO has dealt with it.
- **Who builds it.** `"developer"` on a story is the developer specialisation
  the Architect chose (for example `developer-cli`). The PO can override it,
  and the override shows as `"po_developer"`.

## Example

```json
"s19": {"id": "s19", "step": "implement", "rounds": 1, "status": "active",
        "sprint": 4, "developer": "developer-cli", "po_developer": null,
        "hold": null, "note": "",
        "previous": {"role": "code-reviewer", "status": "changes_requested",
                     "summary": "two functions exceed 8 lines",
                     "verdict": "bounce", "reason": "two functions exceed 8 lines",
                     "next_role": "developer-cli"},
        "...": "..."}
```

The code reviewer sent s19 back to `developer-cli`. The runner starts
`developer-cli` again with the review file and the reason, without waiting
for the PO.

## When a test contradicts the design

Developers may not edit tests. If a test expects something the design rules
out, the developer names the test and the design rule in its handoff, and
the runner sends the story back to the unit-tester. You don't need to fix
the test yourself.

- The unit-tester fixes the test, and the story goes back to the developer.
  This costs no round.
- If the unit-tester thinks the test is right, the architect decides. That
  costs a round, the same as a failed gate.
- A story gets at most `round_cap` free disputes. Later ones count a round,
  so a story can't loop between developer and tester forever.

The dashboard's timeline shows each one as a **test dispute**, and
`agile-team status` shows the open one under the story's `"dispute"`.

The Manager's rulings (`revise_design`, `rescope`, `upgrade_model`,
`escalate`) work at any step, not only at the round cap. A ruling that can't
apply, such as one on a done story, is reported to the PO. It is never
silently dropped.
