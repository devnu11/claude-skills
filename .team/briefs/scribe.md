# Scribe: Current context and conventions

**Last updated:** 2026-10-10 (s23 done)

## s23: Cost reduction — session renewal and context isolation

Two new ADRs document the cost-reduction strategy:
- **ADR-0010:** PO session renewal at sprint and story boundaries (`/compact` vs. handoff fallback, open questions never dropped)
- **ADR-0011:** Context reduction — MCP isolation + guided reads (no connectors for roles, per-story designs, read little guidance)

Role briefs updated: product-owner (renewal workflow), unit-tester (work lean, read little), architect (focused design files), manager (long-running roles friction), developer-cli (context awareness).

## s19: Routing in code

Story s19 is done. The runner now drives the fixed pipeline automatically; the PO judges only. Scribe runs automatically after each story reaches `DONE`. ADR-0009 and `agile-team/docs/design/s19.md` document the architecture.

## Dashboard and earlier decisions

Stories s5 (dashboard), s8 (halt), s13 (presentation), s7 (proxy), s3 (backlog) are completed. Their decisions are recorded in ADRs 0002–0009 and role briefs. Your job remains the same: record decisions as ADRs and refresh briefs after each completed story.
