# Scribe: Current context and conventions

**Last updated:** 2026-10-10 (s19 done)

## s19: Automatic Scribe runs after each story is done

Story s19 (Routing in code) is complete. The scribe now runs automatically after each sprint story reaches `DONE`, without waiting for PO mediation. The runner queues the story id in `state.scribe_due` when a gate moves it to `DONE`, and the next router pass picks it for a story-bound Scribe step with a scribe-specific brief ("Story sN is done. Record its decisions as ADRs and refresh the role briefs.").

**What changed for you:** Your role is unchanged. You still record decisions as ADRs and update briefs. The difference is the runner now calls you automatically, without the PO's `run_role` tool call. You receive a standard brief (story file, design, review file, any previous handoff) plus the scribe heading. After a story reaches `DONE`, the runner hands you control, not the PO.

## Earlier decisions recorded (s5)

Three new ADRs document technical decisions:
- **ADR-0002:** Vanilla JS + EventSource for live updates (relative URLs, auto-reconnect, full snapshot pushes)
- **ADR-0003:** Mermaid 11.4.1 flowchart from CDN, lazy-loaded, with role grouping and animated flow indication
- **ADR-0004:** CSS tokens for light/dark themes (no hardcoded colors, prefers-color-scheme + override)
- **ADR-0005:** Consistent HTML escaping for all snapshot strings (every `${…}` wrapped in `esc()` or `mmdText()`)
- **ADR-0006:** Defensive rendering for sparse/malformed snapshot data (normalize on load, per-row error handling, empty states)

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
