# ADR-0004: CSS tokens for light and dark theme support

**Date:** 2026-10-10  
**Status:** Accepted  
**Affected:** Dashboard theming (s5)

## Context

The dashboard must support both light and dark themes. The user's OS preference should be respected by default, with a manual override available.

Requirements:
- Follow the user's system `prefers-color-scheme` setting (light, dark, no preference)
- Allow manual override with a theme picker (◐/☀/☾ buttons)
- No hardcoded hex colors outside CSS
- No custom HTML or CSS framework beyond the existing mock

## Decision

Use CSS custom properties (CSS variables / tokens) to define all colors, shadows, and semantic color names. The root `:root` block defines the palette; a `[data-theme]` attribute overrides it per user choice.

**Key choices:**
- **Tokens in `:root`:** All colors, borders, shadows etc. are defined as `--<name>` variables, never as hex strings in component CSS
- **Semantic naming:** Names like `--ink`, `--surface`, `--accent` describe intent, not raw color (blue, red). Same token may have different hex values in light vs dark mode
- **`prefers-color-scheme` media blocks:** The existing mock defines light colors under `@media (prefers-color-scheme: light)` and dark under `@media (prefers-color-scheme: dark)`
- **`[data-theme]` override:** When user clicks ◐/☀/☾, set `document.documentElement.dataset.theme` to `"light"` / `"dark"` / `"auto"`. CSS uses `:root[data-theme="dark"]` to override the media query
- **Token refresh on theme change:** Mermaid graph memo clears on theme change, so `drawFlow()` re-renders with updated `themeVariables` from CSS tokens

## Consequences

**Safe:**
- No hardcoded colors to accidentally leak in dark mode
- Colors are CSS only; no JavaScript color logic

**Predictable:**
- Users with dark-mode OS setting see dark theme automatically
- Manual override persists across page reloads (stored in `data-theme` attribute; not persisted to storage)
- Mermaid inherits theme tokens and redraws on change

**Trade-offs:**
- Override does not persist to localStorage (known limit; acceptable for a lab tool)
- If CSS is not loaded, colors fall back to browser defaults
- Token names must be documented or discoverable (they are; see the `:root` block)

## Implementation

**U13 (CSS tokens, architecture.md):**
- All colors defined in `:root` blocks only
- No new hex colors outside `:root` (e.g., `color: #f0f0f0` forbidden; use `var(--surface)` instead)
- Light mode: `@media (prefers-color-scheme: light) { :root { --ink: #000; --surface: #fff; … } }`
- Dark mode: `@media (prefers-color-scheme: dark) { :root { --ink: #fff; --surface: #1a1a1a; … } }`
- Override: `:root[data-theme="light"] { --ink: #000; … }` (and dark variant)

**Theme picker (UI logic, not arch):**
- Three buttons (◐/☀/☾) set `data-theme` to "auto" / "light" / "dark"
- `data-theme="auto"` removes the override, letting `prefers-color-scheme` take effect
- Button highlights the active choice (via `aria-pressed`)

**Mermaid theme variables (U6):**
- `getComputedStyle(root).getPropertyValue('--surface')` reads each token
- Pass to Mermaid as `themeVariables: {primaryColor: surface_value, primaryTextColor: ink_value, …}`
- Clear memo on theme change so `renderFlow()` redraws with updated variables

**Default tokens (example):**
```css
:root {
  --surface: #ffffff;
  --ink: #000000;
  --accent: #0066cc;
  --axis: #999999;
  --s1: #ff6b6b;   /* status 1 = handoff */
  --s2: #4ecdc4;   /* status 2 = message */
  --ink-2: #333333; /* dimmed ink */
}

@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1a1a1a;
    --ink: #ffffff;
    --accent: #66b3ff;
    --axis: #666666;
    --s1: #ff9999;
    --s2: #99e6e0;
    --ink-2: #cccccc;
  }
}

:root[data-theme="dark"] {
  /* dark overrides, ignoring prefers-color-scheme */
  --surface: #1a1a1a;
  /* etc. */
}
```
