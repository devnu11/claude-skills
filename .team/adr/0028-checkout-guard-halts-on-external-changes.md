# ADR-0028: Checkout guard halts when the branch/commit changes externally

**Decision:** The runner records the branch and commit it expects and halts immediately when either changes without the runner's own git operation. The human can accept the new state explicitly with `agile-team accept-checkout`, or restore the branch and commit, then resume.

**Date:** 2026-10-11

## Context

On 2026-10-11 at 16:14, a dotfiles script ran `git checkout --detach 92a38ea` on the team's checkout, moving HEAD to an old commit (~230 commits behind). The runner did not notice. Every step from 16:14 to 17:11 ran on that stale tree: the Quality Czar found code "missing", s58 was rebuilt on old code and accepted, and s4 was re-reviewed unchanged. All results were void and had to be discarded.

The root cause: the runner had no memory of which branch and commit it started on, so it could not detect the external change. If it had, it would have halted immediately and escalated to the human.

## Decision

### Rules

| # | Rule | Consequence |
|---|---|---|
| **K1** | **Checkout record.** `state.checkout` is `{branch, head}` (full sha) or `null`. Written only by: (a) first check that passes while null, recording the live branch/HEAD; (b) `Runtime.record_checkout()` called after the runner's own git writes (step/PO commits, quarantine, salvage, sprint-start merge); (c) `agile-team accept-checkout` (command, K7). | The record outlives the run; changes between runs are caught. A detached HEAD cannot be recorded, so it halts at next check. |
| **K2** | **What is checked.** Checkout matches when: (a) HEAD is attached (`git symbolic-ref` names a branch); (b) no git operation in progress (`rebase`, `merge`, `cherry-pick`, `bisect`); (c) with a record: branch equals recorded and HEAD equals recorded head. Without a record, only (a) and (b) apply. | Checks are repeatable and provable. Operations in progress are detected via path existence in `.git/`. |
| **K3** | **When it is checked.** Before and after every step, before every gate, before every commit, at start/resume, and every router tick (including wait polls). The review worktree (s29) has its own git dir, so operations there are not seen (intended). | The runner cannot proceed while a mismatch exists. Every code path checks. |
| **K4** | **Halt on mismatch.** A mismatch halts the run immediately with kind `CHECKOUT` and status `checkout-changed`. No further step, gate, commit, salvage or quarantine runs. An in-run mismatch posts a liaison question with the exact reason (expected/found/last HEAD reflog move). A mismatch at start posts the question only when no open question has the same text (no duplicates on repeated resumes). | The halt is immediate and clear. No silent running on the wrong tree. The human decides what to do. |
| **K5** | **No salvage on a moved checkout.** `save_interrupted` returns `None` without touching git when the checkout does not match. The step's cost is still ledgered (it was spent). Uncommitted edits stay in the tree. | Salvage must not run on a tree the runner did not expect. Partial progress is left for the human to handle. |
| **K6** | **Start and resume.** On a mismatch, set status and reason, save, post the question (unless a duplicate is open), and exit 78. On a match, record if unrecorded and answer every open checkout question with `restored: <branch> at <sha7>`. This applies to every `start`, with or without `--task` or `--resume`; the record outlives the run. | No exemptions. A stale record blocks the next run. The human must act. |
| **K7** | **Accept command.** `agile-team accept-checkout`: refuses while the runner is alive, or a detached HEAD or operation is in progress. Otherwise records the live branch/HEAD, sets status `stopped` (if it was `checkout-changed`), logs an event, answers open checkout questions with `accepted: <branch> at <sha7>`, and exits 0. | The human can move on after consciously accepting the new state. The record updates to the accepted commit. |
| **K8** | **Reason text.** Exactly: `checkout changed: expected {expected}; found {found}; last HEAD move: {move}`. Where `{expected}` is `<branch> at <sha7>` or `a branch with no git operation in progress` (when unrecorded); `{found}` is `<branch> at <sha7>` or `detached HEAD at <sha7>` plus ` with a <operation> in progress` when one is; `{move}` is the newest HEAD reflog entry or `no reflog entry`. | The reason is precise enough to debug. The reflog move tells the human when and how the change happened. |
| **K9** | **Status.** New `RunStatus.CHECKOUT_CHANGED = "checkout-changed"`. `RunState.halted()` is true for it (with `done` and `blocked`). The dashboard status pill is `critical` (red). `status` JSON gains `checkout` field (the record or `null`). | The status is distinct from other halts. The human knows it is an external change, not a gate or limit. |
| **K10** | **Budget advice flow.** The human's budget-raise commit is a foreign commit. The advice becomes: "raise `team.budget_usd` in `.agile-team.toml` and commit it, run `agile-team accept-checkout`, then run `agile-team start --resume`". | The budget raise is now just another commit the human must accept. |

### Implementation approach

- **`checkout.py` (new):** Pure functions and dataclasses: `Found` (live branch, HEAD, operation), `Drift` (record, found, reflog move), `check()` (returns drift or `None`), `answer_open()` (answers matching questions), `Guard` class (for start/accept outside a run). No imports from `dispatch`, `recovery` or `cli` (they import it).
- **`state.py`:** `CheckoutRecord` dataclass (branch, head, text method). `RunStatus.CHECKOUT_CHANGED`. `RunState.checkout: CheckoutRecord | None`. `halted()` includes it.
- **`dispatch.py` (`Runtime`):** `checkout_moved()` (checks and records), `verify_checkout()` (raises `CheckoutChanged` if moved), `record_checkout()` (after runner's own writes). `run_role` catches `CheckoutChanged` before generic `Exception`. `settle_tree` verifies first, records after commit/quarantine. `gate` verifies first. `save_interrupted` checks checkout before salvaging. `_step_failed` re-raises `CheckoutChanged` (no crash.log).
- **`router.py`:** `_tick` checks at start of loop.
- **`po_tools.py`:** `_turn` checks before query. `_settle` suppresses `CheckoutChanged` (halt already recorded). `pass_tests` checks before gate.
- **`cli.py`:** `cmd_start` guards with `Guard.on_start()`. New `cmd_accept_checkout` command. `status_report` includes `checkout` field.
- **`boundary_runner.py`:** `_merge_in` records after `MERGED` outcome.
- **`recovery.py`:** `recover_killed` records after salvage.
- **`dashboard/index.html`:** `STATUS_TONE["checkout-changed"] = "critical"`.

### Why this design

**Immutable team branch:** The team's work is done via the runner's commits only. Hashes recorded in state stay valid forever. Any external change is detected at once, preventing silent corruption.

**Clear escalation:** Halt is immediate, reason is precise, and the human chooses whether to accept the new state or restore the old one. No retries, no guessing.

**Narrow scope:** Only the runner's own git operations move the record. Role Bash is read-only (s7), so any move is foreign. The check is deterministic.

**Cost stays:** A step that ran on the wrong tree still cost money. The human must decide whether to re-run it.

## Consequences

**Positive:**
- External changes (rebases, checkouts, cherry-picks) are caught immediately, not silently.
- The human has full visibility: the reason names what was expected and what was found, plus the reflog move that caused it.
- The runner never again runs on a tree the human did not intend.
- The human can accept the new state consciously after understanding the change.

**Tradeoffs:**
- A mid-run rebase, merge or checkout by the human (or another script) halts the run at once.
- The human must use `accept-checkout` explicitly; there is no "retry" shortcut.
- If the human's workflow involves external edits between runs (e.g., rebase-before-main), they must run `accept-checkout` after each one before resuming.

**Future:**
- A liaison-assisted recovery flow could simplify the `accept-checkout` step (e.g., "you rebased; run accept-checkout to move forward").
- A follow-up (F1–F3 in design review) may deduplicate questions, improve rebase detection, or extract common predicates.

## References

- Story: `.team/stories/s61.md`
- Design: `agile-team/docs/design/s61.md` (rules K1–K10, modules, test checklist)
- Review: `.team/reviews/s61.md` (verdict: ship; three follow-ups, not blocking)
- Fixture: `agile-team/dashboard/fixtures/snapshot.json` (gains `checkout` field)
- Protocol: `agile-team/reference/protocol.md` (status table, exit codes, halt kinds, CLI row)
- SKILL.md: Step 9 updated (checkout guard)
