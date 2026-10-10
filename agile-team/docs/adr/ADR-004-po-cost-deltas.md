# ADR-004: Ledger each PO query's own cost, not the session's running total

Status: proposed (s25). Date: 2026-10-10. Design: [`../design/s25.md`](../design/s25.md).
Follows up the open question in
[ADR-003](ADR-003-lean-context.md#the-pos-ledger-cost-looks-cumulative-across-resumes).

## Context

The runner ledgers every `query()` with `ResultMessage.total_cost_usd`
(`dispatch._Drain.step_result`). A role step always starts a fresh session.
The PO resumes one session (`state.po_session`) for query after query
(`po_tools.po_plan` sets `Launch.resume`). ADR-003 found that the PO's
ledger costs only ever go up while its tokens do not, and asked whether
`total_cost_usd` is a running total for the session.

### Evidence from the SDK (`claude_agent_sdk` 0.2.163, bundled CLI 2.1.286)

1. The SDK does not compute the figure. `_internal/message_parser.py:319`
   copies `total_cost_usd` straight from the CLI's `result` message, so its
   meaning is the CLI's.
2. `types.py:1438-1448`, `ConversationResetMessage`: a reset "clears the
   conversation history *and* zeroes the running totals reported on
   subsequent `ResultMessage` objects (e.g. `total_cost_usd`). If you
   accumulate those totals across a long-lived session, snapshot them when
   this message arrives." So `total_cost_usd` is a **running total for the
   session**, not a figure for one query. Only a reset sets it back to zero.
3. `ResultMessage.usage` is the query's own usage. In the ledger, PO token
   counts go up and down from one query to the next (point 4), so they are
   not a running total.

### Evidence from the ledger (`.team/run/ledger.jsonl`, up to line 196)

4. All 19 PO entries rise strictly: $1.86, $3.09, $4.75, $7.31, $7.60,
   $11.99, $14.97, $16.04, $17.12, $17.23, $17.62, $17.74, $17.88, $19.90,
   $20.11, $20.44, $20.51, $20.76, $20.98. Their tokens do not. Line 84 has
   3.37M cache reads and line 87 has 0.75M, yet 87 costs more.
5. The rise survives a model change. Line 147 (Opus) reports $16.04 and
   line 149 (Sonnet, the next PO query) reports $17.12. Only a session-level
   counter carries an Opus figure into a Sonnet query.
6. Each step up tracks that query's own tokens. The deltas are cents to
   about $2, not $7–$21:

   | Line | Model | Own tokens (cache read / cache write / output) | Reported | Delta from the previous PO entry |
   |---|---|---|---|---|
   | 87 | opus | 751k / 6.4k / 4.6k | $7.60 | **$0.29** |
   | 149 | sonnet | 255k / 256k / 0.8k | $17.12 | **$1.08** |
   | 155 | sonnet | 512k / 0.9k / 0.5k | $17.23 | **$0.11** |
   | 157 | sonnet | 1.56M / 6.1k / 4.9k | $17.62 | **$0.38** |
   | 168 | sonnet | 0 / 498k / 3.3k | $19.90 | **$2.02** |

   A rough list-price estimate from each row's tokens is the same order as
   its delta. For rows dominated by cache writes it is within 10% (149: about
   $1.05; 168: about $1.92). For rows dominated by cache reads the delta is
   55–70% of the estimate. The rest of that gap is not explained, but it is
   small next to the overcount. Claude Code's own pricing is the source the
   role steps already use, so the deltas keep PO and role costs comparable.
7. Role steps track their tokens and do not climb, because each one is a
   fresh session. Example: line 86, developer-cli, $0.27 for 154k reads and
   54k writes.
8. The first five PO entries add up to $24.62. That is the "$24.62 over
   five PO sessions" in s23's notes, so that figure counted the same spend
   up to five times.

**Finding: yes.** For a resumed session, `total_cost_usd` includes every
earlier query in that session. The ledger has counted the PO's spend again
on every PO query.

## Decision

1. **Ledger the delta.** For a PO query that resumes session S, the own
   cost is `reported − previous`, where `previous` is the running total last
   seen for S. A query with no resume (kickoff, or the fresh session after
   a handoff renewal) has `previous = 0`. The runner keeps
   `(session, reported)` in `state.json` (`RunState.po_cost`), so a
   `start --resume` in a new process still knows the baseline.
2. **A drop means the counter restarted.** If `reported < previous`, for
   example after a reset or if `/compact` ever zeroes the counter, the own
   cost is `reported`.
3. **Use the delta, not a price table.** Pricing from `usage` would need a
   rate table per model that goes stale, and it would differ from how role
   steps are priced. The delta needs no table, and the provider rule
   (`Providers.cost_of`, `billing = "free"` → 0) still applies after it.
4. **Unrecorded queries are not lost.** A PO query that ends in an error
   result is not ledgered today (s10 will cover it). The next query's
   running total still includes it, so its delta pays for it. Grand totals
   stay right.
5. **Role steps do not change.** They never resume, so their reported cost
   is already their own. A test pins that a role step's options have
   `resume=None`. Any future resumed role must use the same delta.
6. **Past entries are not rewritten** (AC3). The correction is the
   one-off note below.

## One-off correction (entries written before s25)

PO entries written before s25 ships are running totals. The figure never
fell from line 46 to line 196, not even across the Opus→Sonnet switch, so
the evidence points to one PO session over that whole span. The PO's
estimated true spend up to ledger line 196 is therefore the last figure,
**$20.98**. If an unseen session break happened, the true figure is higher,
by at most the figure just before the break.

| | USD |
|---|---|
| PO cost as ledgered (19 entries, lines 46–196) | 277.91 |
| PO spend estimated from the running total (line 196) | 20.98 |
| **Overcount to subtract** | **256.93** |

The run's budget is $300 (`team.budget_usd`). Subtract $256.93 from
`budget_status.spent_usd` (and from the dashboard's spend and the PO's row)
to get the real spend up to line 196. Budget checkpoints fired at the
inflated figure, so the Manager reviews at "25/50/75 %" came early.

Entries written after line 196 but before s25 ships (the run is still
going): while the running total keeps rising, a PO entry's overcount is the
previous PO entry's figure. If the figure ever falls, a new session began
and that entry is its own cost. The first PO query after s25 ships takes
its baseline from the last PO ledger entry (design rule C6), so it is
counted correctly.

## Consequences

- PO ledger entries, `budget_status`, `spend_by_role`, the dashboard's spend
  and the Manager's checkpoints reflect real spend from s25 on. Totals that
  include older lines stay inflated, and this note gives the correction.
- `state.json` gains `po_cost`. Older files load without it, and the first
  PO query seeds it from the ledger.
- If a later CLI makes `total_cost_usd` per query, a resumed query's
  `reported` would fall below the baseline, and rule 2 would ledger it as is.
  The delta would then be right too. It would only be wrong when such a
  query costs more than the previous one. The unit tests use a fake query,
  so they cannot catch a CLI change. Whoever upgrades `claude-agent-sdk`
  re-checks points 2 and 4 above against the new version and a fresh
  ledger.
