# ADR-0009: Routing in code — the runner drives the fixed pipeline; PO judges only

**Date:** 2026-10-10  
**Status:** Accepted  
**Deciders:** developer-cli, architect, code-reviewer, unit-tester, integration-tester, customer-proxy

## Context

The Product Owner was the single long `query()` that routed every sprint story through the pipeline. Each role step was a `run_role` tool call the PO made, and each report cost another turn re-reading its entire session. With most PO budget ($24.6 on Opus) spent on mechanical routing, this became the team's highest-cost bottleneck.

The pipeline, however, is **fixed**: story steps follow a defined order (design → implement → review → acceptance), gates control movement, and bounces are automatic. The PO's true job is **judgement**: deciding when human input is needed (open questions, blocked stories, round caps) or when the mechanical steps can run unattended.

## Decision

Separate mechanical routing from judgement with a two-layer architecture:

1. **Router passes (code-driven, no PO)**
   - New module `router.py`: `Router.advance()` loop picks the next work (Manager, Scribe, or a movable story), briefs it with paths and previous handoff, runs the step, and stops only at a hand-over trigger.
   - Work is picked in order: Manager first (when `state.manager_due` is set), Scribe (for stories reaching `DONE`), then the first movable story (active, not held, in sprint).
   - Each step gets a **standard brief**: story file, design or architecture file, review file, previous handoff reason, and bounce reason if returning.
   - A step runs and the report is checked against the `HANDOVERS` table: when any row matches, the pass stops and the router hands control to the PO with every matching trigger.

2. **PO turns (judgemental, token-light)**
   - New `PoRun` driver: alternates PO turns with router passes.
   - PO turn resumes with a **hand-over prompt** listing why the PO is needed: open questions to answer, held stories to release, quarantines to approve, round caps to rule on, bounced stories that cannot be auto-routed, human messages to act on, or end-of-sprint states.
   - New tools `continue_story(story, note)` and `set_developer(story, role)` give the PO lightweight levers: release a held story with a note for the next step, or override the developer specialisation.
   - The PO makes judgement calls, then ends its turn. The router carries on.

3. **Hand-over triggers (data-driven, not branching)**
   - New module `handover.py`: the `HANDOVERS` table lists conditions (report status, open questions, quarantine, round cap, or unroutable bounce) that halt the pass and hand control to the PO.
   - No code outside the table branches on when to hand over; the table is the source of truth.
   - Rules R1–R18 in the design define hold semantics, role selection, previous-step recording, and flow control.

4. **Developer field (from architect)**
   - The architect's handoff carries a `"developer"` field naming the specialisation for implement steps: `"developer-gui"`, `"developer-cli"`, etc.
   - The runner parses this into `story.developer`. The PO can override per story with `set_developer`.
   - Role selection (R3) checks candidates in order: PO override, bounce's suggested role, previous retry role, architect's pick, fallback `developer`.

5. **Automatic Scribe and Manager (story-bound and story-less)**
   - When a story reaches `DONE`, its id queues into `state.scribe_due`.
   - Router's Scribe picker runs the scribe on each due story with a story-bound step and scribe-specific brief ("Story s19 is done. Record its decisions as ADRs…").
   - A held done story still gets scribed (holds only block movable stories); a done story blocked by an open question waits.
   - The Manager still runs story-less at sprint start, model overrides, and budget checkpoints, before any story steps.

6. **PO on Sonnet (token efficiency)**
   - Built-in `roles/product-owner.md` sets `model: sonnet`, down from `opus`.
   - Judgement calls need reasoning, not reasoning-for-hours. PO's brief is concise (which stories are held, why), and its response is short (approve, release, fix).
   - Sonnet handles this at a fifth the cost.

## Consequences

**Positive:**
- **Cost drop:** PO shifts from Opus to Sonnet and from continuous routing to episodic judgement. Saves roughly $20–$24 per run (80–90% of PO budget).
- **Speed:** Router makes routing decisions in milliseconds; no token cost per step. Stories move continuously until a hand-over.
- **Clarity:** When and why the PO is called is a table, not scattered branching. Briefs are standard and auditable.
- **Consistency:** Every step gets the same brief structure. Bounces carry the gate reason. Developer role comes from architect, not implicit.
- **Predictability:** A failed gate bounces immediately with test output; no PO turn between retries unless round-capped.

**Negative and mitigations:**
- **Larger PO turn surface:** One PO turn now lists many hand-over reasons (questions, holds, quarantines, round cap, human messages, stall/end). PO must read the prompt carefully. Mitigation: prompt is structured (`Stories:` board shows each story's state at a glance).
- **Scribe always runs:** Scribe is called automatically on every done story, not filtered by PO. A bad scribe handoff will hand over to PO and block the story indefinitely. Mitigation: scribe is a simple, well-tested role; D1 fix ensures even held done stories get scribed.
- **No inline brief edits:** The PO cannot write a custom brief for a mechanical step; it can only use `run_role` if the standard brief is incomplete. This is intentional (forces discipline: if a step needs a custom brief, the step is wrongly scoped or the standard paths are wrong). Mitigation: developer and code-reviewer follow the standard paths strictly; architectural questions go to the architect.

**Impact on related work:**
- s20+ (Sprint gating, backlog prioritization): Backlog stories are not movable, so they never enter the router; the PO explicitly moves them with `start_sprint`.
- s21+ (Parallel stories): Router runs one story at a time, finishing all steps before the next story. No parallel concurrency; gating stays simple.
- Future cost review: After s19 lands, re-run sample sprints and measure PO token spend. If Sonnet's cost is acceptable, commit to it; if not, revert to Opus with the same routing architecture.

## Design reference

- Story: `.team/stories/s19.md`
- Design: `agile-team/docs/design/s19.md` (rules R1–R18, HANDOVERS and BRIEF_PATHS tables, standard brief, developer field semantics)
- Implementation: `agile-team/runner/agile_team/` modules `router.py` (new), `handover.py` (new), `po_tools.py` (driver loop), `dispatch.py` (note_step, effects), `gates.py` (PreviousStep dataclass), `state.py` (scribe_due, delivered), `roles.py` (developer field); built-in roles `roles/product-owner.md` (Sonnet, judgement only), `roles/architect.md` (developer field docs)
- Tests: `tests/unit/test_router.py`, `tests/unit/test_handover.py`, `tests/unit/test_po_tools.py`, `tests/unit/test_dispatch.py`, `tests/unit/test_gates.py` (PreviousStep, scribe_due), `tests/unit/test_state.py` (delivered, scribe_due, previous)
- Review: `.team/reviews/s19.md` (D1 blocking defect: done stories with holds were not scribed; fixed; no defects in round 2)
