# ADR-0085: A scheduler runs stories in parallel, one task writes the run files, and every hand-over has a scope

Story: s159. Design: `agile-team/docs/design/s159.md` (C1 to C10, H1, H2).
Amends ADR-0009 (routing in code) on how steps are started.

## Context

The PO driver alternated PO turns with router passes, and one step ran at a
time. With a worktree per story, steps on different stories no longer share
a tree, so they can run at once. They still share `state.json`, the events,
the ledger and the PO. The runner is asyncio. The agent queries are async,
but every command and git call blocks.

## Decision

1. **A scheduler loop** replaces `PoRun`'s loop and `Router.advance`. It
   starts one task per story (a role step, a land or a story rebase), up to
   `max_open_stories` open stories. It also starts the Manager review
   alongside, keeps a budget reserve for each running step, and serves one
   PO turn at a time from a queue of hand-overs.
2. **One writer.** `RunWriter` is the only code that writes `state.json`,
   `events.jsonl` and `ledger.jsonl`, and it does so on the scheduler task.
   Events and ledger lines get their ids at once and are queued thread-safe.
   State changes from step tasks and PO tool calls run through
   `await writer.apply(fn)`. Blocking work runs in worker threads, which
   return data and never touch `RunState`. Outside a scheduler the writer
   writes directly, so the CLI and tests are unchanged.
3. **Snapshots for the PO.** A PO turn sees a snapshot. A tool call naming a
   story that has moved since is refused with the story's new state, and the
   PO's own changes refresh its snapshot.
4. **Scopes in a table.** Each `Trigger` is `STORY` (queue, and only its
   story waits) or `RUN` (queue, and nothing new starts until the PO's turn
   ends). A trigger missing from the table fails when the CLI starts.
5. **A main lock** serialises everything that changes the main checkout:
   storyless steps, a landing from its merge to its fast-forward, PO settles
   and story-admin commits.

## Consequences

- Code that mutated state from anywhere now has to go through `apply`. A
  misplaced save raises `WrongWriter` in tests.
- Gate evaluation runs on a copy of the story and returns its changes in the
  `Outcome`.
- Boundary stages still run on the scheduler task, so a long boundary CI
  wait pauses PO tool calls. Nothing else runs during a boundary anyway.
  (Changed by s163, below.)

## Amended by s163 (2026-10-19)

The sprint-49 review found that a landing held the main lock through its CI
wait, which stalled tells, answers and storyless steps, while a resumed
landing moved the checkout with no lock at all. It also found that a
boundary stage blocked the event loop, and that the PO's `run_role` started a
storyless step without the lock. Design: `agile-team/docs/design/s163.md`
(K1 to K6, B1 to B8).

- **Decision 5 narrows.** The main lock is held only while git moves the main
  checkout: a landing's on-head check, sprint push, fast-forward and
  checkout record; a boundary's sync and replay; a follow's fast-forward;
  storyless steps; PO settles and story-admin commits. A landing's merge,
  checks and CI wait run without it.
- **One rule for who owns the checkout.** `Runtime.uses_main_checkout` and
  `Runtime.lock_for` decide for the scheduler and for the PO's `run_role`
  alike.
- **Boundary stages are tasks.** A stage runs as a coroutine under
  `BOUNDARY_KEY`. Its checks, CI wait, git and `gh` calls run in worker
  threads, which get values or copies and never touch `RunState`. A
  checkpoint from inside a worker (the replay's progress) goes through
  `RunWriter.call_from_thread`. The request queues wait while a stage runs,
  and PO turns, story CI polls and the writer go on. `step()` stays a sync
  wrapper for the CLI and the tests.

Known limits, ruled on at s163's design review (2026-10-19):

- The REPLAY stage holds the main lock for the whole stage, including a
  rebase fix's check run, so storyless steps and story-admin commits wait
  for it. Nothing else would move the checkout then anyway.
- A stage task can start while an R9 follow task still runs
  (`start_boundary` doesn't check `follow_task`). The window is small:
  the follow runs only on a CI hold, and both take the main lock to move
  the checkout.

## Amended by s166 (2026-10-20)

Decision 1's "a budget reserve for each running step" counted every running
task, including a landing and (since s163) a boundary stage. Both run as the
role `runner`, which has no role file or model, so the budget check raised
`RoleError: unknown role 'runner'` when it started any step beside one
(sprint 51's start). Design: `agile-team/docs/design/s166.md`.

- **Only work with a role and a model holds a reserve.** The kinds in
  `scheduler.COSTLESS` (land and boundary) never start the budget check, as
  before, and now hold no reserve while they run.
- **Consequence.** A landing's or a boundary's `gh` and CI calls cost no
  model budget, so leaving them out loses nothing. A new costless kind joins
  `COSTLESS` and gets both rules at once.

## Amended by s164 (2026-10-20)

An idle run spun at 84% CPU and wrote about 28,000 `checkout.guard` events
an hour: every tick's guard stage emitted an event, its `submit` set
`writer.wake`, and the wake ended the next wait at once. Design:
`agile-team/docs/design/s164.md` (W1 to W5).

- **Decision 2 adds a wake rule.** `RunWriter.bind` keeps the scheduler
  task as the writer's owner. A write submitted by the owner task queues
  without waking the scheduler; a write from any other task or a worker
  thread queues and wakes it. The scheduler drains its own writes before it
  waits, so they reach disk without delay.
- **Consequence.** An idle run ticks once per `POLL_S`. A flow that needs
  another tick at once after the scheduler's own change says so with
  `Scheduler.hurry`, never by waking itself.

