# ADR-0010: PO session renewal at sprint and story boundaries

**Date:** 2026-10-10  
**Status:** Accepted  
**Story:** s23  
**Deciders:** developer-cli, architect, code-reviewer, unit-tester, customer-proxy

## Context

The Product Owner's session cost was growing across the entire sprint because every turn re-sent everything previously read. By s19, a single PO session across the whole sprint cost $24.62 (close to the Architect's $26.30 over 15 steps), and the PO was spending most of its budget on reviewing the same context repeatedly.

Two clear renewal points exist: sprint start (a new task) and story completion (a phase boundary). At these points, the runner can drop step-by-step history and start fresh, keeping only what the PO needs to make decisions: open questions and answers, decisions still pending, next work and why, and artifact links.

The challenge was implementation: the Claude SDK's `/compact` command supports session compression in interactive clients, but support in SDK sessions is not guaranteed. A fallback was needed.

## Decision

When the runner reaches a renewal boundary (sprint start or story `DONE`), it offers the PO two paths to a fresh or refreshed session:

1. **Compact path (preferred):** Send `/compact` with instructions on what to keep. If the SDK detects a `compact_boundary` message, the session is compressed, history is dropped, and we carry on in the same session with carry-over context.

2. **Handoff fallback:** If `/compact` doesn't work (no boundary detected), ask the PO to write `.team/po/handoff.md` with the same content. Delete the file, then start a fresh session (no session id) with a formatted lead including the handoff, `story_status`, and carry-over. The runner saves the new session id as soon as the query completes.

The choice happens once per run (in `state.po_renew_path`): if `/compact` succeeds, the whole run uses compact. If it fails, switch to handoff for all later boundaries and never try compact again.

Open questions and pending answers are **never dropped**: they are carried over in every path from the relay, not from the session, because answers are tracked in `state.delivered` and re-handed over by the router (s19).

## Consequences

- **Cost reduced:** A sprint's PO budget drops from ~$25 to roughly $5 (one fresh lead per renewal, no $24 session growth).
- **Boundaries respected:** Renewal happens only at clear points (sprint start, story done), not mid-turn or on every step.
- **Fallback reliable:** If the SDK doesn't support `/compact`, the handoff file ensures a fresh start without losing open context.
- **Ledger is honest:** Every renewal query is recorded as a PO entry with its cost, so the dashboard shows what renewal costs.
- **One-time choice:** The run settles on one path (compact or handoff) after the first boundary, simplifying testing and debugging.

## Implementation details

- **Rules P1–P12** in `agile-team/docs/design/s23.md` define boundary queuing (`po_renew_due`), renewal logic, text templates, and error handling.
- **Ledger entry** P11: renewal queries are ordinary PO steps, visible in turn counts and cost.
- **Carry-over texts** P9: open questions list story ids they block; answers not yet delivered are handed over by the router next (not from the PO session).
- **Event logging** P8: `po-session` events record the path (`compact`, `handoff`, or `kept`), reasons for renewal, and pre-compaction token count if available.

## Placeholder: re-measure (AC4)

The story's acceptance criterion AC4 requires measuring the Unit Tester's context per turn after the new code runs, targeting under 60k tokens (s19 was 113.9k). This can only be confirmed during a live step with 20+ turns. The Scribe will record the measured value here once available.
