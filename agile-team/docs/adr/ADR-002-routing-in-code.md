# ADR-002: The runner routes the pipeline; the PO is called for judgement

Status: accepted (s19). Date: 2026-10-09. Design: [`../design/s19.md`](../design/s19.md).

## Context

According to the ledger, the PO is the most expensive role ($24.6). Most of
that spend goes on routing stories through a fixed pipeline. The PO is one
long `query()`, and every role step is a `run_role` tool call it makes. Each
report costs it a turn that re-reads its whole session. A step usually takes
longer than the prompt cache lives, so most of those reads are cold. Yet the
next role, the brief's content and the bounce target are almost always fixed
by the pipeline and the gate. The human wants the routing done in code, and
then the PO moved to Sonnet.

## Decision

1. `po_tools.run_po` becomes a driver. It alternates **PO turns** (a
   `query()` that resumes the PO's session) with **router passes**
   (`router.Router.advance`), which run steps with no PO involved.
2. When to hand control to the PO is data: the `handover.HANDOVERS` table
   over step reports. Three more triggers are raised at run level: new
   human answers, sprint complete, and nothing can move. Every matching
   reason goes to the PO in one hand-over prompt.
3. The router briefs each role with a standard brief. It points at the
   story, the design, the review file and the previous handoff, and on a
   bounce it adds the gate's reason. The brief points at artifacts and does
   not restate them.
4. A story handed to the PO is **held** until the PO releases it
   (`continue_story`) or runs a step on it itself. Without holds the router
   would rerun a step the PO had not yet dealt with.
5. The architect names the developer specialisation in a handoff field
   (`developer`). The PO can override it (`set_developer`).
6. The Manager (whenever `manager_due` is set) and the Scribe (after each
   story is done) are run by the router.
7. The PO role defaults to Sonnet.

## Alternatives rejected

- **Loop inside `run_role`.** The PO would keep one tool call open while the
  runner drives the story to a trigger. That is fewer moving parts, but one
  MCP tool call could then last for hours, which risks the tool-call
  timeout. It also could not stop between steps when the human answers, and
  the PO would still sit in one ever-growing turn.
- **A fresh PO session per hand-over.** This is cheaper per turn, but the PO
  would lose the kickoff interview and earlier rulings that exist only in its
  session. Resuming keeps that continuity. The hand-overs themselves are
  short.
- **Letting the PO keep routing, on Sonnet only.** This still pays one PO
  turn per step. It also leaves the process rules (who runs next, what the
  brief holds) in a prompt rather than in code, which the charter rules out.

## Consequences

- The PO speaks less often. The human sees progress on the dashboard and
  through the PO's `notify_user` at hand-overs, not after every step.
- While a question is open and nothing else can move, the runner waits for
  the answer instead of exiting. `stop` ends the wait.
- A non-limit error in a router step reaches the PO as an `error` hand-over,
  where ADR-001 had a tool error. The traceback still goes to `crash.log`.
- A new reason to involve the PO is a new row in `HANDOVERS`.
