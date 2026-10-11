# ADR-008: The runner records the checkout it expects and halts when anyone else moves it

Status: accepted (s61). Date: 2026-10-11. Design: [`../design/s61.md`](../design/s61.md).
Follows [ADR-001](ADR-001-clean-halt.md) (data-driven halts).

## Context

- On 2026-10-11 at 16:14:54 a dotfiles script ran `git checkout --detach 92a38ea`
  in the team's checkout. HEAD pointed at an old main, without about 230 of
  the team's commits. The runner did not notice. For an hour every step ran on
  that tree: a story was rebuilt on old code and accepted, another was
  re-reviewed as unchanged. All of it had to be voided by hand.
- The runner already knew the branch only at the sprint boundary
  (`Upstream.team_branch`) and never compared HEAD with anything.
- Roles cannot move HEAD: role Bash allows read-only git only. So every HEAD
  move is either the runner's own write or foreign.

## Decision

1. `state.json` holds `checkout = {branch, head}`. Only the runner's own git
   writes (step and PO commits, quarantine, salvage, the sprint-start merge,
   and later s59's rebase) update it, right after they write, and save at once.
   The first passing check records it when it is missing.
2. The runner compares the live checkout with the record at every
   opportunity: on `start` and `start --resume` (before kill recovery and
   preflight), on every router tick (so also while waiting), before every PO
   turn, before every commit or quarantine (which brackets every step), before
   every gate, and before every salvage. HEAD must be attached, on the
   recorded branch, at the recorded commit, with no rebase, merge,
   cherry-pick, revert or bisect in progress.
3. A mismatch is its own halt kind (`checkout`, status `checkout-changed`,
   exit 78). It posts a `question`, so it is an escalation to the human, not a
   note. Nothing else runs on the changed tree: no commit, quarantine, gate,
   salvage or further step. The reason names the expected and found branch and
   commit and the newest HEAD reflog entry.
4. The human either puts the checkout back (the next start answers the
   question as restored) or keeps it with `agile-team accept-checkout`, which
   records the new HEAD, logs a `checkout` event and answers the question.

## Options considered

- **Trust commits that carry the runner's co-author trailer.** Anyone can
  write the trailer, and a reset or a detached HEAD has no commit to inspect.
  Rejected.
- **Accept fast-forwards of the recorded commit.** A foreign commit on the
  branch is exactly what AC6 must catch. Rejected; acceptance is explicit.
- **Check only at step boundaries.** The incident changed HEAD while the
  runner was waiting between steps. Checking on every router tick costs three
  `git` calls per 5 s poll. Accepted.
- **Raise an exception and let the CLI classify it.** Broad `except
  Exception` handlers (router dispatch, boundary stages) could swallow it.
  The halt is therefore recorded first (`halt_run`), and the
  `CheckoutChanged` exception only unwinds the current step.

## Consequences

- A human commit between runs (for example the budget raise of ADR-007) now
  needs `agile-team accept-checkout` before `start --resume`; the budget
  advice says so.
- A step cut off by a checkout halt keeps its edits uncommitted in the tree
  (they were made on the wrong tree; the human decides). Preflight then
  refuses the dirty tree until the human commits, stashes or discards them.
- s59's boundary rebase must call `Runtime.record_checkout()` after it
  rewrites the recorded hashes.
- Unattended treats exit 78 as a failed job, which is the escalation wanted.
