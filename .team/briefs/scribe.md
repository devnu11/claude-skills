# Scribe: Current context and conventions

**Last updated:** 2026-10-10 (s5 done)

## s5 decisions recorded

Story s5 (Dashboard live UI) is complete. Five new ADRs document the technical decisions:
- **ADR-0002:** Vanilla JS + EventSource for live updates (relative URLs, auto-reconnect, full snapshot pushes)
- **ADR-0003:** Mermaid 11.4.1 flowchart from CDN, lazy-loaded, with role grouping and animated flow indication
- **ADR-0004:** CSS tokens for light/dark themes (no hardcoded colors, prefers-color-scheme + override)
- **ADR-0005:** Consistent HTML escaping for all snapshot strings (every `${…}` wrapped in `esc()` or `mmdText()`)
- **ADR-0006:** Defensive rendering for sparse/malformed snapshot data (normalize on load, per-row error handling, empty states)

Role briefs updated: developer-gui (lessons learned), code-reviewer (escaping rule + selector checks), integration-tester (manual acceptance checklist), unit-tester (test gaps noted), product-owner (s5 summary in design decisions).

## Process notes

The Scribe role is unaffected by backlog/sprint gating (s3) or Customer Proxy enforcement (s7). Continue documenting decisions and outcomes as usual.

Note: decisions made in s7 and s3 are also recorded in `.team/adr/` and `.team/briefs/` by the Product Owner; you may reference these in your summaries.
