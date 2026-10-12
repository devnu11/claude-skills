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
- the Manager finds that a repeated setback is the runner's fault, or
  belongs to a role with no pipeline step;
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
  you answer (`agile-team answer <id> "<text>"`), within a few seconds. While
  it waits, `agile-team status` says what it waits on, for example
  `"status_reason": "waiting on answers: s40 waits on m42"`. If the run halts
  meanwhile, its note ends the same way. To end the run instead, use
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
- "Fixed" means the test file's content changed after the dispute was
  raised. Whitespace and comment edits don't count. The developer names
  the test with its path from the repo root. A path the runner can't find
  is sent back to the developer.
- If a story is still stuck at `tests` with a green suite, the PO can move
  it on with `pass_tests`. The runner checks the suite first. Nobody needs
  to edit `state.json`.

The dashboard's timeline shows each one as a **test dispute**, and
`agile-team status` shows the open one under the story's `"dispute"`.

The unit-tester's brief quotes what the test command said about the
disputed test when the dispute was raised, including when the test was not
failing at all.

If the developer already committed the story's code before a dispute (or a
ruling or review sent the story back), the story's tests may already pass.
The unit-tester then says it changed or checked the tests, and the story
moves on. Nobody has to write a test that fails on purpose.

The Manager's rulings (`revise_design`, `rescope`, `upgrade_model`,
`escalate`, `advance`) work at any step, not only at the round cap.
`advance` moves a story one step on when its gate can't be met; the event
log records why. It can't move a story past its last step. A ruling that can't
apply, such as one on a done story, is reported to the PO. It is never
silently dropped. The PO can then clear the done story's hold with
`continue_story`. A done story's hold never stops its Scribe step.

## When a story keeps coming back for the same reason

If a story is sent back or held twice in a row for the same reason, the
runner stops the loop. It does not send the story round again, and the
repeat costs no round. "The same reason" ignores details that change from
run to run: ids, numbers, times, ports and paths. So `nothing is listening
at 127.0.0.1:8799` and `… at 127.0.0.1:8800` count as the same. The number
of repeats is `repeat` under `[gates]` in `.agile-team.toml` (default 2).

The runner then runs the Manager on the story. The Manager gets the
repeated reason, every step and role involved, and the last output. It
decides whose fault the loop is:

- **a role in the pipeline**: the story goes to that role's step;
- **another role, such as DevOps**: the PO briefs that role;
- **the runner itself**, for example a delivery's start command that
  always fails: the story is blocked, and you get a note that starts
  `Runner fault on sN`. The PO plans the fix.

On the dashboard's board such a story shows **⏸ manager**, with the
repeated reason on its `waits on:` line. The timeline shows the escalation and the Manager's verdict.
`agile-team status` shows `"repeated"` (the reason) and `"streak"` (the
setbacks so far) on the story.

Apart from those details, two reasons must match word for word. A role
that describes the same problem in different words gives two reasons; the
round cap catches those.

A **backstop** catches the rest. If a story is sent back between the same
two steps four times in a row, for any reasons, the runner stops the loop
the same way and runs the Manager with every reason. The number is
`backstop` under `[gates]` (default 4). It matters most for stories sent
back without a round (for example when the presentation is missing);
ordinary bounces reach the round cap first. The dashboard timeline shows
**back and forth → needs manager**, and `agile-team status` shows the run
under `"run"`.

## When a test hangs

The runner never waits on a gate command forever. Each command (tests,
coverage, the full checks at sprint boundaries) has a time limit of
`command_timeout_s` under `[gates]` in `.agile-team.toml`, 300 seconds by
default. Raise it if your suite normally takes longer:

```toml
[gates]
command_timeout_s = 600
```

At the limit the runner stops the command and everything it started, and
nothing else. The story goes back to the same step, as with a failed gate,
and the reason names the test that hung:

```
the command did not finish in time:
…
timed out after 300s, so the runner killed its process group: uv run pytest -q
the hanging test: /repo/tests/test_router.py::test_waits_for_an_answer (line 872)
```

The runner finds the test in the stack dump the run printed. For a pytest
suite, set a per-test timeout so there is always a dump. Better still, a
hanging test then fails by itself in seconds, and the rest of the suite runs:

```toml
# pyproject.toml (pytest-timeout in your dev dependencies)
[tool.pytest.ini_options]
timeout = 30
```

Without one, pytest's built-in `faulthandler_timeout = 30` still prints a
dump. With no dump at all, the reason gives the command and the limit.

## Who runs the tests

Only the runner runs your full test suite and coverage. The roles get the
results in their briefs, under `## Runner results`: the developer sees the
failing tests from the tests gate, and the quality czar sees lint, static
analysis and coverage, which the runner runs just before its step. A role
that tries `pytest` with no test named, or any `--cov` run, is told no and
told what to do instead. Running named tests is fine
(`pytest -q tests/test_x.py::test_y`).

A developer can also ask the runner to run named tests, or all of the
story's new tests. Tell the runner how, per test root, in `.agile-team.toml`:

```toml
[[toolchain.targeted]]
root = ""                     # the ids are relative to this directory
command = "uv run pytest -q --no-header {tests}"
```

With several projects in one repo, add one row each, e.g. `root = "api"` with
`command = "uv run --directory api pytest -q --no-header {tests}"`. Each run
is logged in `.team/run/events.jsonl` as a `tests-run` event with how long it
took.

To run your suite in parallel, add pytest-xdist to your dev dependencies and
`-n auto` to your commands, e.g.
`coverage = "uv run pytest -n auto --cov --cov-report=term"` and
`command = "uv run pytest -q --no-header -n auto {tests}"`. pytest-cov merges
the coverage of all workers, so the gate reads one total as before. If a
gate says "Different tests were collected between gw0 and gw1", a test's ID
holds a value that differs per process (a pid, the time). Change that test
so its ID is fixed.

## When a story comes back to tests with its code done

A ruling or a review can send a story back to `tests` after its code is
written. Its tests may then already pass. The unit-tester updates the tests
to the current design and says in its handoff that it changed them or
confirmed them. The story then moves on to the developer, with no manual
step from you. `agile-team status` shows `"implemented"` on each story: how
many times it has passed the implement gate. A story on its first pass
(`"implemented": 0`) still needs a failing test first.
