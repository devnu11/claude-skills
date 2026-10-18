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
