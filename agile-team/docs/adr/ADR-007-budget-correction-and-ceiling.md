# ADR-007: Correct the PO overcount when the ledger is read; the budget is a ceiling that halts the run

Status: accepted (s38). Date: 2026-10-11. Design: [`../design/s38.md`](../design/s38.md).
Follows [ADR-004](ADR-004-po-cost-deltas.md).

## Context

- ADR-004 found that PO ledger entries written before s25 hold the PO
  session's running total, and it gave a one-off correction of $256.93 for
  lines 46–196. Nothing applied it. `status`, the dashboard, `budget_status`
  and the Manager all showed the raw ledger.
- The $256.93 was incomplete. The same session kept running until ledger
  line 310: 47 PO entries that rise strictly, from $1.86 to $32.49. Line 312
  ($1.65) is the first s25 delta. In this repo the PO entries on lines
  46–310 add up to about $1,057.35, and the PO really spent $32.49 over that
  span. The overcount is therefore about **$1,024.87**.
- `team.budget_usd` never stopped a run. It was documented as a soft budget
  ("hard caps belong to the key's Console workspace"). Its only use was the
  Manager checkpoints, so a run went on past 104% of it (104% of the inflated
  figure).

## Decision

1. **Correct when reading, in one function.** `ledger.corrected(entries)`
   turns each legacy PO entry into that query's own cost with s25's rule
   (`SessionCost.own_cost`: the difference from the previous legacy PO
   figure, or the figure itself after a drop). `Ledger.entries()` and the
   dashboard snapshot both pass through it, so every reader shows the same
   corrected spend. `budget_status` reports the amount taken off as
   `po_overcount_usd`.
2. **Legacy means a PO entry before a fixed instant.** `PO_DELTAS_FROM =
   1791694950.0` (2026-10-11 05:02:30 UTC), between line 310 and line 312.
   s25's code did not exist before that instant, so any PO entry written
   earlier, in any repo, is a running total. That makes the rule true by
   construction, not a guess.
3. **The budget is a ceiling.** After every role step lands, after every PO
   query is ledgered, and at run start, the runner halts when the corrected
   spend (rounded as `budget_status` shows it) has reached `budget_usd`.
   The halt is a normal halt: status `blocked`, a reason naming the spend
   and the ceiling, one liaison note, and exit **77**. `start --resume`
   reads the config afresh, so raising `budget_usd` is all the human does.

## Options considered

| Option | Why not |
|---|---|
| Rewrite old ledger lines (corrected cost, original kept in a new field, a marker) | It needs a migration trigger and a boundary all the same. It races with the runner and dashboard that append to and read the file. A partial write would damage the only cost record. The ledger stops being append-only. |
| Append one negative correction entry | It needs the same boundary. The per-step views and the spend-over-time chart would show the inflated curve and then a cliff, and the PO's per-entry figures would stay wrong. |
| Subtract a fixed constant ($256.93) | It is wrong (finding 2), it is specific to one repo, and it would have to be patched into each consumer. |
| Detect running totals from the shape of the data (a rising run of PO entries) | s25 deltas can rise too. On a fresh ledger it would "correct" real costs. |
| Exit 75 for a budget stop | `unattended` treats 75 as "wait for the reset and resume by itself", so it would loop on a budget stop. 77 (`EX_NOPERM`) ends the job and leaves the decision to the human. |

## Consequences

- In this repo, every view drops by about $1,024.87 at once. Plans made
  against the PO's "about $956" or the Manager's "about 518" were too
  pessimistic.
- `ledger.jsonl` is never rewritten. Anyone can recompute the raw figures
  from it, and `po_overcount_usd` shows the difference.
- A PO entry written by pre-s25 code *after* the cutoff (an install that
  upgraded late) is not corrected. It shows as more spend, never less. That
  is the safe direction for a budget, and it is documented.
- The ceiling is checked after spend is ledgered, so a run can pass it by
  at most one step or PO query. Steps are never cut off for budget.
- ADR-004's "Past entries are not rewritten" still holds. Its correction
  table is superseded by this ADR's read-time correction.
