# Product Owner: Current context and conventions

**Last updated:** 2026-10-10 (s23 done)

## Session renewal at sprint and story boundaries (s23)

At sprint start and when a story reaches `DONE`, the runner renews your session to keep context small. You'll experience one of three paths:

- **Compact path (preferred):** The runner sends `/compact` with instructions. If the SDK detects it, history is dropped and you carry on in the same session with a brief carry-over (open questions only).
- **Handoff fallback:** If `/compact` doesn't work, the runner asks you to write `.team/po/handoff.md` with open decisions, pending questions, what's next, and artifact links. Write nothing else, then end your turn. The runner deletes the file, starts you fresh with that handoff as context, and saves the new session id.
- **Kept:** If handoff is blank or missing, the old session continues and you try again at the next boundary.

**Never drop:** Open questions are always carried over from the inbox; they are re-handed over by the router if you don't answer. Renewal never affects `delivered` or pending human messages.

See ADR-0010 for details.

## Backlog and sprint management

Every story starts in the backlog (`sprint: null`). Use `start_sprint(goal, stories)` to move stories into active work. Only sprint stories can proceed past opener; backlog stories are refused with "add it to a sprint". On resume, check whether to start a new sprint with remaining work.

## Design and enforcement decisions documented in ADRs

- **ADR-0010:** PO session renewal at sprint and story boundaries (s23); `/compact` vs. handoff fallback.
- **ADR-0009:** Routing in code (s19); runner drives pipeline, PO judges.
- **ADR-0008:** Team presents product in ready-made environment (s13).
- **ADR-0007:** Clean halt on limits, crashes, SIGTERM (s8).
- **ADR-0002–0006:** Dashboard live UI (s5).
