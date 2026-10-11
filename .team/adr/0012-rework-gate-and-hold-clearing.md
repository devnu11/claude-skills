# ADR-0012: Rework gate and hold clearing on done stories

**Date:** 2026-10-10 (s24 done)  
**Status:** Accepted  
**Relates to:** ADR-0009 (routing in code), s11 (design review), s19 (automatic pipeline)

## Context

After s19's automatic pipeline, stories can return to earlier steps (tests, design) via three routes:

1. A manager ruling (`revise_design` or `rescope`) after review
2. A reviewer's `changes_requested` with a named next role (architect or unit-tester)
3. A dispute resolved after code is already in place

When a story comes back to `tests` with implementation commits from an earlier pass, the old `tests_red` gate still demands a failing suite and bounces on green—even though the tests may now be correct for the new design. This stranded s19 at `tests` after a ruling, and the liaison had to move it by hand.

Also, s11's review found that a hold placed on a done story (e.g., `ruling_not_applied` by the manager) cannot be cleared: `continue_story` refuses done stories, so the PO has no way to acknowledge the hand-over.

## Decision

### 1. Track story implementation with a counter (G1, G2)

Add `StoryState.implemented: int = 0`, incremented once each time the story passes the `implement` gate, never reset by rulings, bounces, or disputes. A story saved before s24 without this field loads with `1` if its step is past implement (`quality`, `e2e`, etc.), else `0`.

**Consequence:** The pipeline can distinguish first-pass stories (no code yet) from reworked ones (code in place but design may have changed).

### 2. Test claim in handoff (G3)

Extend `Handoff` with optional field `tests: "changed" | "confirmed" | None`. The unit-tester claims either:
- `"changed"`: updated tests for this story's new design on this pass
- `"confirmed"`: verified existing tests already cover the current design

Any other value (empty string, integer, etc.) is a malformed handoff. The claim is not included in `handoff_report` (the contract for external observers), and the `step-end` event is unchanged.

**Consequence:** The rework gate has a signal from the tester about whether the suite's green result is trustworthy.

### 3. Rework gate at tests (G4, G5, G6, G7)

At `tests`, with `story.implemented > 0`, no open dispute, and a `done` handoff, run the test command once:
- **Red suite:** Pass to `implement` (same as first-pass `tests_red`)
- **Green suite with claim:** Pass to `implement`, with reason `tests pass on code from an earlier pass; tests {claim}`
- **Green suite without claim:** Bounce back to `tests`, reason `tests pass on code from an earlier pass; write a failing test, or hand off "tests": "changed" or "tests": "confirmed"`

At `tests` with `story.implemented == 0` (first pass), the old `tests_red` gate runs regardless of handoff status or claim, as today.

An open dispute (s11's T6 rule) takes precedence over the rework gate. A non-`done` handoff on a reworked story goes to `_handoff_outcome`, as with a dispute.

**Consequence:** Reworked stories move forward without manual intervention, while first-pass tests still must fail. The brief tells the unit-tester about code already being in, and the bounces are rare and self-explaining.

### 4. Clear holds on done stories (G8, G9)

`continue_story` no longer refuses done stories. For any known story it sets `hold = None`, saves, and returns `continued`. The unknown-id refusal is unchanged.

The Scribe picker (s19 R4) already ignores done-story holds, so clearing one gives the PO a way to acknowledge the hand-over without changing what the Scribe does. Done stories still never move (s11 T10 and s19 R12 are unchanged).

**Consequence:** The PO can clear stale holds from the inbox after ruling-related notes, and the full hand-over cycle is acknowledged.

## Consistency rules

- **Precedence (G6):** An open dispute wins over the rework gate; a non-`done` handoff wins over both.
- **Legacy load (G2):** Stories at quality, e2e, acceptance load `implemented: 1`; earlier steps load `0`. Explicit values round-trip.
- **Brief (G7):** When at `tests` with `implemented > 0` and no dispute, the prompt includes `REWORK_BRIEF` to guide the tester.
- **No reset:** Rulings, bounces, returns, and disputes leave `implemented` alone (the code stays in history).

## Tradeoffs

- **Unclaimed bounces may repeat.** If the tester forgets the claim twice, the story bounces twice at `tests` before the round cap. This is acceptable: the error is the tester's, and the message is clear.
- **Trust the claim.** The runner does not verify that `"changed"` reflects actual test changes. The code reviewer sees the diff; a false claim shows up as missing coverage at review.
- **Holds still exist.** Rather than not setting holds on done stories at all (which would hide the reason from `status`), we keep them and let the PO clear them. This is consistent with s11's design.

## References

- Story: `.team/stories/s24.md`
- Design: `agile-team/docs/design/s24.md` (rules G1–G9, exact test checklist)
- Review: `.team/reviews/s24.md` (round 0 and round 1, all test defects fixed)
- Related: ADR-0009 (pipeline), ADR-0011 (context reduction for the runner)
