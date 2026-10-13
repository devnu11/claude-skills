# ADR-0049: CI rule for sprint readiness

**Date:** 2026-10-13 (s110 done)  
**Scope:** product-owner.md, SKILL.md, protocol.md  
**Relates to:** s81 (CI stage, ci_green/ci_failed/ci_pending), s106 (cancel records, job evidence)  

## Context

Story s81 added CI checks to the sprint boundary: a green CI run is required before a PR can be merged. The runner now waits for GitHub Actions checks and refuses a boundary with `ci_failed` or `ci_pending` holds.

However, the prompt guidance for the PO and the team documentation did not yet articulate what "done with respect to CI" means. There was risk that a flaky failure could be waved through if it looks hard to debug, or that a cancelled job with no evidence could be re-run without clarity on when a re-run is acceptable.

Decision s53/t53 asked: document a standing CI rule—one that the PO reads with every boundary hand-over and that SKILL.md and protocol.md carry as part of the team's CI boundary description.

## Decision

**CI rule.** A sprint is done only when a green CI run is actually present on GitHub. A re-run counts only when it is green, and only when the failed job never ran our code (it was cancelled with no steps run, or no runner was available). If a failure could be flakiness in our code, it is a bug story, and the sprint is not done.

**Role file placement:** The rule appears in `agile-team/runner/agile_team/roles/product-owner.md` as a bullet, right after "Never call a PR ready from a `Review:` line ..." and before the `**refused**` section (design CR2).

**Documentation placement:** 
- **SKILL.md:** The rule text appears in step 8's boundary paragraph, after "never relay those as ready." (CR3).
- **protocol.md:** The full rule appears in its own paragraph right after the **Ready.** paragraph of the sprint-boundary section. The `ci_green`, `ci_failed`, and `ci_pending` hand-over rows each point to it with "see the CI rule under **Ready.**" (CR3).

**PO action on ci_failed:** The role file's `ci_failed` bullet now reads: read the failing lines first. Only when they show the failed job never ran our code (`no runner was assigned`, or a cancel whose steps never started) may the PO ask the human to re-run it and `continue_boundary`. Otherwise, at once, `open_story` a bug story and `record_ci_bug(story)`, and tell the human the PR is NOT ready (CR4).

**CI absence:** With no CI result (`none`, a local boundary) or `ci_pending`, the PO never tells the human the sprint is done (CR5).

## Consequences

- The PO has standing guidance on CI readiness that updates with every sprint boundary.
- Flaky failures are explicitly not waved through; they become bug stories.
- Re-runs are only accepted when the original failure shows the job didn't run our code (e.g., runner timeout, cancelled before steps).
- The rule is prompt-only: the runner does not refuse a PO `continue_boundary` at `ci_failed` if lines show our code ran. A future story may enforce this in code (raised as an open question in s110's design).

All three documents (role file, SKILL.md, protocol.md) carry the rule word-for-word so the PO reads it consistently across all references to CI boundaries.

## Test coverage

Five tests in `tests/test_s110_ci_rule.py` verify:
1. The CI rule text (exact, whitespace-collapsed) appears in the role file, SKILL.md, and protocol.md.
2. In the role file, the rule comes after "Never call a PR ready" and before "**refused**" (index order).
3. The role file's `ci_failed` bullet holds the required phrases: "read the failing lines first", "no runner was assigned", "Never `continue_boundary` hoping a re-run turns green".
4. The role file holds the CR5 sentence: "never tell the human the sprint is done" (with no CI result or ci_pending).
5. The `protocol.md` rows (`ci_green`, `ci_failed`, `ci_pending`) each contain "see the CI rule under **Ready.**"

## No new ADR requirement

The rule is prompt-only (no code enforcement); it extends s81's CI boundary pattern and s106's evidence lines. No new dependency, no new hand-over, no new tool. All text is data-driven: one canonical rule text in the design, copied word-for-word into three places.
