# ADR-0003: Mermaid flowchart with role grouping and live indication

**Date:** 2026-10-10  
**Status:** Accepted  
**Affected:** Dashboard Flow tab (s5)

## Context

The Flow tab displays the team structure and information flow between roles. The design needs to show:
- Who the roles are
- How information moves (briefs, handoffs, messages)
- Who is currently active
- Edge weights (thicker edges = more interactions)

Early mock used a hand-drawn SVG ring. The accepted design (A1 review feedback) asks for a Mermaid graph "because it auto-layouts and scales".

## Decision

Use **Mermaid 11.4.1 flowchart** from jsDelivr CDN, with role grouping by organizational side (Customer, Steering, Support) and phase (Design, Build, Verify).

**Key choices:**
- **Mermaid from CDN, not bundled:** Dynamic `import()` at first Flow render. No build step. Pinned version `@11.4.1` is the only control; Subresource Integrity cannot be used with dynamic import.
- **Lazy load:** Only fetch Mermaid if the user opens the Flow tab, saving bandwidth for dashboard viewers who only look at the Board.
- **Strict mode:** `securityLevel: "strict"` prevents injected labels from rendering as HTML.
- **Grouping:** Roles are placed in subgraphs by their organizational context:
  - `SIDE_ROLES`: customer-proxy → "Customer", manager → "Steering"
  - `PHASE_ROLES`: architect → "Design"; unit-tester, developer → "Build"; quality-czar, code-reviewer, integration-tester → "Verify"
  - Others → "Support"
  - PO always in Steering
  - Order: Customer, Steering, Design, Build, Verify, Support
- **Edge colors and weights:** Styled by interaction kind (brief=ink-2, handoff=s1, human=s2) and weighted by count (thicker = more).
- **Live indication:** Pulsing accent glow on the active role (via `markActive`), plus animated dots on edges playing recent events (step-start, step-end, message, answer).

## Consequences

**Safe:**
- Strict mode blocks label injection even if snapshot strings aren't escaped
- Graph scales to arbitrary role counts (grid, not hand-drawn)
- Known limit: without internet, Flow shows source text instead of diagram (other tabs unaffected)

**Predictable:**
- Auto-layout removes manual node positioning
- Same Mermaid version everywhere (pinned in code)
- Grouping mirrors the organizational structure (roles see their peers)

**Trade-offs:**
- One external dependency (Mermaid on jsDelivr); acceptable for a read-only dashboard
- Dynamic import carries no Subresource Integrity; users trust the CDN's version
- If Mermaid fails to load, Flow shows a fallback: source text + error message

## Implementation

**U6 (Mermaid loading):**
- `MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"`
- Load once, on the first `renderFlow()` call
- `mermaid.initialize({startOnLoad: false, securityLevel: "strict", theme: "base", themeVariables})`
- Theme variables read from CSS tokens: `--surface`, `--ink`, `--axis`, `--accent`

**U7 (Flow source generation):**
- `flowSource(view)` returns Mermaid text (pure function)
- Nodes: `you`, `po`, one `r<i>` per `ringRoles(view)`
- Groups: `subgraph grp<Group>["<Group>"] … end` for non-empty groups
- Edges: only when count > 0, styled by kind and weighted by count
- All labels through `mmdText(s)` to escape `"`, `<`, `>`
- Node ids are generated; never use role names as ids

**U7a (Live indication):**
- `markActive(view)` moves class `live-halo` to the SVG node of `activeNodeId(view)`
- `flushLive()` plays the last 6 queued events as animated dots
- `EVENT_EDGE` table maps event kinds to `[from, to, class]`: step-start → brief, step-end → back, message/answer → human
- `findEdge(from, to)` queries SVG by id prefix `L_<from>_<to>_` (Mermaid 11 ids, was `LS-`/`LE-` in v10) with reverse fallback for `<-->` edges
- `runDot()` animates a 5 px circle over 900 ms along the path
- Reduced motion: replace dot with static edge highlight (`edge-hit` class, 1.2 s)

**U8 (Rendering and error handling):**
- Memo on `source + theme`; skip if unchanged
- Call `mermaid.render("flow-svg-<seq>", source)`
- Race guard: only write SVG if `seq` is still latest
- On error (import or render): show fallback + source text, timeline still renders
- `safely()` wrapper catches and reports render errors without crashing other panels
