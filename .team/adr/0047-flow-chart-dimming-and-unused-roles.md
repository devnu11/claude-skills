# ADR-0047: Flow chart dimming by colour; unused roles marked and hidden

**Decision:** The Flow chart shows only roles that have data or are routed to by the pipeline. Box labels are dimmed by colour (fill/stroke/color), never by opacity, to avoid WebKit compositing bugs. Boxes with no stats show "idle". Mermaid is configured for natural SVG size with no shrinking.

**Date:** 2026-10-13  
**Status:** Accepted  
**Affected:** Developer, Unit Tester, Integration Tester, Code Reviewer, Product Owner, Architect, Customer Proxy

## Context

The Flow chart (dashboard) showed empty boxes with labels piled at the top-left corner, and text was tiny. Story scope was especially broken.

Investigation revealed that Story scope dims every role that hasn't touched the current story by applying an opacity style through Mermaid's `classDef idle opacity:0.55`. WebKit (Safari) renders HTML inside a foreignObject with opacity < 1 on its own compositing layer, positioned at the SVG's origin (0,0), not at the box's location. The result is an unreadable label at the chart's top-left, with an empty box below.

Sprint and Run scopes rendered correctly because they only dimmed roles with no events at all, and that's just one built-in role (`developer-db`). The running box (architect) was never dimmed, and it rendered correctly.

Additionally, the chart was configured for `useMaxWidth: true`, shrinking to the column width, and roles with no data showed `0 · $0.00` instead of indicating they were idle.

## Decision

### Rules: dimming, used roles, text size, idle indication

| # | Rule | AC |
|---|---|---|
| FL1 | **No compositing styles.** No `classDef` line in `flowSource` contains `opacity`, `filter`, `transform` or `mix-blend-mode`. This holds in every scope. | AC1 |
| FL2 | **Dim by colour only.** The `idle` class recolours the node: `fill:<--surface-2>, stroke:<--grid>, color:<--muted>`. Which nodes are dimmed does not change. The active node is never dimmed. | AC1 |
| FL3 | **Same structure in every scope.** The scope changes only the stats text and which nodes carry `idle`. The node set, ids, groups and edges don't depend on the scope. | AC1 |
| FL4 | **Idle text.** If a role has no totals in the scope and no open step, its stats segment is `"idle"`. Otherwise `tokens · $ · time`. The `↩ N bounced` and running/live lines are unchanged. | AC2 |
| FL5 | **Natural size, scroll sideways.** Mermaid is initialised with `flowchart: { useMaxWidth: false }`, so the SVG carries its own pixel width and height and is drawn at scale 1. `themeVariables.fontSize` is 16 px. The CSS rule becomes `.flow svg { max-width: none; display: block; margin: 0 auto; }`. The chart scrolls horizontally if needed, not shrink. Rendered label size ≥ 12 CSS px. | AC3 |
| FL6 | **Drawing doesn't depend on tab visibility.** Nothing reads the layout of `#flow` or `#tab-flow` before or during drawing. Mermaid measures text in its own temporary element. Showing a hidden tab redraws only if the memo key changed. | AC1 |
| FL7 | **Each role has `used` boolean.** A role's snapshot entry gains `"used": bool`. A role is used when (a) any repo pipeline step routes to it (via `gates.STEP_ROLES`; the generic `developer` stands for the repo's assigned developer roles), or (b) it has at least one `step-start` event. | AC5 |
| FL8 | **Chart draws only used roles.** `ringRoles` filters to `r.used !== false`, so a role without the key (old replays) is still drawn. The PO node is always drawn, even if `used: false`. | AC5 |
| FL9 | **First step shows the box.** A role becomes used with its first `step-start`. The next snapshot changes `flowSource`, so the chart redraws with the new box. | AC5 |

### Implementation changes

**`dashboard/snapshot.py`:**
- Import `STEP_ROLES` from gates.
- `GENERIC_DEVELOPER = STEP_ROLES["implement"]`: the stand-in for the repo's developer roles.
- `_assigned_developers(state)`: every story's `developer` and `po_developer` that is set.
- `_step_role(files, step)`: private helper; maps a pipeline step to its role(s), expanding `GENERIC_DEVELOPER` to assigned developers.
- `_routed_roles(files)`: union of roles routed to by pipeline steps.
- `_stepped_roles(events)`: roles with at least one `step-start` event.
- `_used_roles(files)`: union of `_routed_roles` and `_stepped_roles`.
- `_roles(files)`: existing enabled roles, each with `used: r.name in used`.

**`dashboard/index.html`:**
- CSS: `.flow svg { max-width: none; display: block; margin: 0 auto; }` (no shrinking).
- Constants: `FLOW_FONT_PX = 16`, `MERMAID_OPTIONS` with `useMaxWidth: false`.
- Function `mermaidConfig(vars)`: returns Mermaid options with theme colours and font size.
- Function `idleClassDef()`: returns colour-only `classDef idle` (no opacity).
- Function `statsText(view, ctx, name)`: returns `"idle"` if role has no totals and no open step, else `tokens · $ · time`.
- `nodeLabel`: uses `statsText` for the stats segment.
- `ringRoles(view)`: filters to `r.used !== false` before mapping to names.
- `drawFlow`: calls `mermaid.initialize(mermaidConfig(vars))`.

**`dashboard/fixtures/snapshot.json`:**
- Every `roles[]` entry gains `"used"`, set by `_used_roles` for the fixture's pipeline and events.
- Add built-in role `developer-db` with `used: false` in sorted position, showing that unused roles are explicitly marked.

### Why this design

**Avoids WebKit bug:** Opacity on compositing blocks is a known issue in Safari. Dimming by colour change keeps all elements in the normal flow, rendering at the correct positions.

**Cleaner state:** The `used` field makes it explicit which roles have data or are expected. The chart only draws relevant roles, reducing clutter.

**Responsive without resize events:** Natural-size SVG doesn't reflow when the tab is shown or the window is resized. The Mermaid layout is stable once computed.

**Clarity:** "idle" text tells the user a role has no activity, not `$0.00` which could mean "free" or "no cost recorded".

## Consequences

**Positive:**
- **Labels render correctly in all scopes.** Every label sits inside its box, even in Story scope where roles are dimmed.
- **Text is readable.** 16 px font at scale 1 is at least as large as before sprint 30.
- **Unused roles are explicit.** The snapshot clearly marks whether a role is used, and the chart shows only active roles. Built-in roles that have never run don't clutter the view.
- **Chart is stable.** No resize handlers or tab-visibility checks needed. The layout is computed once and remains correct.
- **Idle roles are clear.** A box with no stats shows "idle", not misleading numbers.

**Tradeoffs:**
- **Geometric layout not unit-tested.** The node harness has no browser. Tests pin the cause (FL1, FL2, FL5, FL6) and the hidden-then-shown rendering path. The customer proxy confirms in a real browser that labels are inside boxes (AC1).
- **Wide charts scroll.** If a chart doesn't fit the viewport, it scrolls horizontally rather than shrinking. Most dashboards fit, but very wide ones require scrolling.

## Amended by s118 (2026-10-13)

The chart is now HTML (ADR-0052). Still in force: FL1 and FL2 (dimming is
by colour only, now `.fc-box.dim`, and no compositing style applies
anywhere in `#flow`), FL3 (structure does not depend on scope), FL4
(`idle`), FL7 to FL9 (used roles). Replaced: FL5 (Mermaid natural size) by
s118 FC4 (fixed group width, nothing scaled, sideways scroll), and FL6
(Mermaid measures text) by FC21 (geometry is measured after each write, on
resize and when the tab is shown). Why: Mermaid is gone.

## Related decisions

- **ADR-0027 (s4):** Snapshot raw data contract—this decision adds `used` to `roles[]`; the builder is ≤8 lines.
- **ADR-0003 (s3):** Mermaid flowchart with role groups—this decision refines the rendering rules for dimming and font size.

## Notes

**Cause confirmed:** The opacity issue was confirmed by the developer by reading WebKit compositing rules and checking that Sprint/Run (no dimming in most scopes) rendered correctly. The customer proxy confirmed in a headless Chromium browser that all labels now sit inside their boxes after load, tab switches, and resize. AC1's Safari check is left to the human; the PO will open a follow-up bug if any labels are still mispositioned after the runner is re-pinned.

