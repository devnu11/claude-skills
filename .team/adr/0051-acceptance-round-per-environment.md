# ADR-0051: Acceptance is a round of one Proxy step per environment

**Date:** 2026-10-13
**Status:** Accepted
**Story:** s95 (A14c). Design: `agile-team/docs/design/s95.md`.

## Context

Since s94 every AC names its acceptance environment in the story file, but the runner still
presented and tried a story in its first environment only (s94 SF9). The human's rules
(2026-10-13): each environment is tried by a Proxy that sees only that environment's ACs;
every environment runs even after one fails; one verdict; after rework all run again; no
parallel runs yet (A15).

The pipeline is a step machine: one step, one gate, one move. A round of N Proxy steps
needed a place to keep the verdicts so far and a gate result that neither moves nor counts.

## Decision

- **The round lives on the story**: `StoryState.tried`, one `acceptance.Tried` per environment
  this round. It is written only by the acceptance verdict and cleared by
  `Pipeline._forward` into `acceptance`, so every entry into acceptance runs every
  environment.
- **The due environment is computed, not stored**: `acceptance.Round(names, tried).due()`,
  the same pure function in dispatch (which environment to prepare) and in the gate (which
  environment the verdict is for). No "environment in flight" field.
- **A new verdict, `NEXT`**: stays at the step, counts no round, hands nothing over. The
  router runs the next Proxy step as for any active story. After the last environment the
  gate gives `PASS` or one `BOUNCE` listing every failed environment and its AC ids, to the
  earliest step the failures name.
- **The Proxy reports failed AC ids in its handoff** (`failed_acs`) and writes one
  `## Environment: <name>` section of one report. The gate checks the section (process in
  code, charter).
- **One presentation per environment**: `.team/run/presentation/<id>/<environment>/` (ADR-0008
  amended).

## Consequences

- Rounds and the repeat rule are unchanged: a round of N steps is at most one setback.
- A hold mid-round keeps the verdicts so far, and the same environment runs after
  `continue_story`. A return to e2e restarts the round.
- The PO is not woken between environments, and the next Proxy's brief does not say how the
  previous environment went.
- Parallel environments (A15) can reuse `Round`; only the scheduling changes.
- Stories with a pre-s95 flat presentation go back to e2e once, without a round.
