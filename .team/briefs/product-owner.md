# Product Owner: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## Backlog and sprint management

Every story starts in the backlog (`sprint: null` in state.json). To move a story into active work:
- Use `start_sprint(goal, stories)` to open a new sprint with named stories
- Unknown story IDs are refused with guidance
- Only sprint stories can proceed past their opener step; backlog stories are refused with "add it to a sprint"
- Legacy `state.json` files load stories into the backlog automatically
- On resume after a story is done, check whether to start a new sprint with remaining work

## Design and enforcement decisions

- **Dashboard live UI (s5):** Vanilla JS + EventSource, Mermaid 11.4.1 from CDN (lazy-loaded), CSS tokens for themes, all snapshot strings escaped. Five ADRs (0002–0006) document the technical choices. Review was 4 rounds; found and fixed two defects (bad selector, unescaped strings) and sparse-data crash.
- **Nested forbidden roots (s7):** Proxy sandbox computes the deepest literal path segment before wildcards, not just the top-level directory. The Proxy can read customer docs even when they share a parent directory with source code.
- **Deny on any view (s7):** Proxy Bash checks in two views (shell continuations and comment-aware). A denial in any view blocks the command, even if others allow it. This over-approximation prevents false negatives at the cost of rare false positives.

## What the human needs to know

No roles edit `.team/adr/` or `.team/briefs/` except the Product Owner's end-of-step handoff. Backstop the linchpin roles (Unit Tester, Integration Tester, Customer Proxy) by reviewing their self-checks in their final handoffs.
