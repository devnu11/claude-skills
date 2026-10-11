# ADR-0022: Responsive sprint board with flexbox

**Date:** 2026-10-11  
**Story:** s21

## Context

The sprint board was a CSS Grid with columns fixed at a minimum of 190px wide. At a 1280px window (typical laptop/tablet viewport), the board had 10 columns (Backlog, 8 pipeline steps, Done), and Done was off-screen to the right. Horizontal scrolling was required to see it.

AC3 requires Done to be visible without horizontal scrolling at 1280px, even with cards in every column.

## Decision

- Replace CSS Grid with CSS Flexbox for the board layout
- Columns use `flex: 1 1 0; min-width: 0; overflow: hidden` to share available width proportionally
- Empty columns (no cards) are given the class `empty` and styled as 44px strips with vertical headings
- Card text wraps with `overflow-wrap: anywhere` to fit narrow columns
- Column headings in empty columns rotate vertically (`writing-mode: vertical-rl`) to fit the narrow space
- The `.seg + .seg` rule adds 8px margin between segmented controls (group + unit toggles)

## Consequences

**Positive:**
- Done column is visible at 1280px even with all 10 columns showing cards (each ~116px wide)
- Empty columns take minimal visual space (44px + 8px gap), reducing clutter
- Column layout adapts automatically to window size; no need for responsive media queries
- Cards in narrow columns wrap naturally rather than overflowing

**Constraints:**
- At full width with many columns, card titles and pills wrap over multiple lines (acceptable trade-off)
- No horizontal scrollbar; users cannot scroll left/right (intentional — the board fits)
- Vertical headings in empty columns are narrow; long step names wrap vertically
- The 44px strip width is a design choice; narrower would be harder to click, wider would waste space

## Trade-off

This layout prioritizes visibility of all columns (especially Done) over card readability when many columns are full. In practice, most step columns are empty or have few cards, so the full columns have adequate width. At 1440px and wider, cards are comfortably readable even at full width.

## Related

- s21 design: rules F7–F9
- s14: Done column visibility was deferred to s21
