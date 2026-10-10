# Developer (GUI): Current context and conventions

**Last updated:** 2026-10-10 (s5 done)

See `developer.md` for base conventions.

## s5 complete: Dashboard live UI

Story s5 delivered the browser-side dashboard with five tabs (Flow, Board, Tokens, Questions, Requirements), live updates via EventSource, and theme support. Key decisions documented in ADRs 0002–0006:

- **ADR-0002:** Vanilla JS with `EventSource` for live snapshot streams (no build step, relative URLs, auto-reconnect with backoff)
- **ADR-0003:** Mermaid 11.4.1 flowchart from jsDelivr CDN, lazy-loaded with role grouping and animated flow indication
- **ADR-0004:** CSS tokens for light/dark themes (no hardcoded colors, follows prefers-color-scheme)
- **ADR-0005:** All snapshot strings escaped through `esc()` helper before rendering
- **ADR-0006:** Defensive rendering with per-row error handling and empty-state fallbacks

Review found two defects (D1, D2) in round 1; both closed by round 3. Round 4 fixed a sparse-data crash (empty sprint-start). Known gap: no executable test for live features (dots, halo, reconnect); they were verified by hand in headless Chrome. Add a follow-up story for runtime checks (render every TIMELINE handler with `data: {}`, match `findEdge` against a Mermaid 11 SVG).

**Backlog and sprints:** Stories must be in a sprint before development starts.
