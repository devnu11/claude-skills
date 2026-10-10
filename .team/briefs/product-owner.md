# Product Owner: Current context and conventions

**Last updated:** 2026-10-10 (s19 done)

## Routing in code — PO judges only (s19)

The runner now drives sprint stories through the fixed pipeline. You are called only for judgement. Key shift:
- **Router passes:** Code picks the next work (Manager, Scribe, or a movable story), runs the step with a standard brief (story, design, review, previous handoff), and stops only when a hand-over trigger matches.
- **Your hand-overs:** Open questions (answer with `ask_user`), held stories (release with `continue_story(story, note)`), blocked/failed (decide fix), quarantines (approve or ignore), round caps (escalate or upgrade model), unroutable bounces (run that role yourself), human messages, sprint end/stall.
- **New tools:** `continue_story(story, note)` releases a held story and passes your note to its next step. `set_developer(story, role)` overrides the architect's specialisation pick. `wait_for_answers` is unchanged. `run_role` is now for non-standard steps only.
- **Model:** Changed to Sonnet (from Opus). Judgement calls at a fifth the cost.
- **Built-in brief:** `roles/product-owner.md` replaces its Mission and How You Work; describes your new workflow.

## Backlog and sprint management

Every story starts in the backlog (`sprint: null`). To move a story into active work, use `start_sprint(goal, stories)` to open a new sprint with named stories. Unknown story IDs are refused with guidance. Only sprint stories can proceed past opener; backlog stories are refused with "add it to a sprint". Legacy files load stories into the backlog. On resume after a story is done, check whether to start a new sprint with remaining work.

## Design and enforcement decisions documented in ADRs

- **ADR-0009:** Routing in code (s19); runner drives pipeline, PO judges.
- **ADR-0008:** Team presents product in ready-made environment (s13); presentation copy, gate check, Proxy precondition.
- **ADR-0007:** Clean halt on limits, crashes, SIGTERM (s8); HALTS and LIMIT_PATTERNS tables.
- **ADR-0002 through 0006:** Dashboard live UI (s5); Vanilla JS, EventSource, Mermaid, CSS tokens, escaping.

## What the human needs to know

No roles edit `.team/adr/` or `.team/briefs/` except the PO's end-of-step handoff. Backstop critical roles (Unit Tester, Integration Tester, Customer Proxy) by reviewing their self-checks in their final handoffs.
