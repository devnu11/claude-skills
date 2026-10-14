# ADR-0052: The Flow chart is HTML with an SVG overlay; Mermaid goes

**Date:** 2026-10-13 (s118 design)
**Status:** Accepted
**Supersedes:** ADR-0003. **Amends:** ADR-0047.
**Design:** `agile-team/docs/design/s118.md` (FC1–FC30, R1–R4, R11, R12)

## Context

The Flow chart was a Mermaid flowchart (ADR-0003). Mermaid lays the graph out
by itself, so the human could not get the logical layout (Leadership on top,
stage groups left to right), the text was hard to read at real size, labels
broke in WebKit (ADR-0047), and every live change re-rendered the whole SVG,
which cancelled any moving dot. The human approved a hand-laid HTML mock
(variant N) and asked for it at 100 % zoom.

## Decision

- The chart is HTML and CSS built from the snapshot by pure functions
  (`flowModel` → `flowHtml`), with small inline SVGs for sparklines. Groups
  and their order are one table, `FLOW_GROUPS`; an unknown role goes to its
  pipeline step's group through the new snapshot key `step_roles` (the
  step-to-role map stays in Python, `gates.STEP_ROLES`), else to Leadership.
- Groups have one fixed width (`--group-w`); the gaps between them stretch.
  Nothing in `#flow` is scaled; a narrow window scrolls sideways.
- Paths that cross the layout (the PO's two-way paths) and every moving dot
  live in one SVG overlay that is created once and never replaced. A redraw
  writes only the HTML layer; the overlay's paths are re-measured in place,
  and each dot looks its path up by key on every frame, so a redraw never
  cancels a dot.
- Every Flow text's size and ink come from one table (`FLOW_TEXT`), ≥ 10 px
  and ≥ 4.5:1 in both themes; colours other than ink are never used for text.
- The settings panel hides features with classes on the chart root, kept in
  `localStorage`.
- The runner adds what the chart needs and the events lacked: `step` on
  `step-start`, and a tokens-per-minute series (`rate`, `rates.Rate`) on the
  heartbeat step, every `step-end` and every `po-turn`.

## Consequences

- One outside URL fewer: the page loads only markdown-it from the CDN, and
  the Flow chart works offline.
- The layout is ours to keep: a new built-in role needs a `FLOW_GROUPS` row
  (or lands in its step's group).
- Geometry (arrow heights, path ends) needs a browser; until A18 adds
  browser tests the customer proxy's screenshots are the evidence. Pure
  functions (model, HTML, dots, formats, text table) are tested in node.
- ADR-0047 still holds for dimming by colour (FL1, FL2), `idle` text (FL4)
  and used roles (FL7, FL8). Its FL5 (Mermaid natural size) and FL6 (Mermaid
  measuring) are replaced by FC4 and FC21.

## Amended by s118 round 3 (2026-10-13)

- **Group width.** The human's decision t74 replaces the one fixed width
  (`--group-w`) with two bounds, one setting each: groups are
  `--group-max` (236 px) when there is room and shrink to `--group-min`
  (216 px), and the gaps keep at least `--gap-min` (24 px). The four groups
  then fit the Flow card at a 1024 px window. Still nothing is scaled, and
  a window narrower than the minimum row scrolls sideways.
- **Tool descriptions (AC12).** The snapshot gains a top-level key
  `stage_descriptions`, `{name: description}`: every built-in stage from
  `stages.STAGES`, then each repo `[[tool]]` row. The page looks a tool
  box's second line up there by stage name, so `runner-stage` events stay
  as they are and the table stays in one place, in Python. A tool box's
  tooltip is its newest run's command (`data.detail`), not the description.
  The descriptions are written for a human: they say what is checked and
  on what (design s118 R12).
- **Consequence.** The `tools` command and the live panel show the
  rewritten descriptions too, since all of them read `stages.STAGES`.
