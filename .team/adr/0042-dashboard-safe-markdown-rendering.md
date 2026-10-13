# ADR-0042: Dashboard safe Markdown rendering with markdown-it

**Decision:** Render Markdown on the dashboard using `markdown-it@14.1.0` configured to escape raw HTML, restrict links to http(s) only, disable images, and load as a single pinned URL from CDN like Mermaid, falling back to plain text until the library arrives.

**Date:** 2026-10-12  
**Status:** Accepted  
**Affected:** Dashboard Questions tab, timeline handoffs, Markdown display

## Context

The dashboard Questions tab and timeline show long text (open questions, answered questions, handoff summaries) as plain escaped text, making formatting hard to read. Rendering Markdown would help readability: lists, headings, emphasis, code blocks, and tables would become visible. However:

1. Raw HTML in the input must never run (no `<script>`, `<img onerror=…>`, `<iframe>`).
2. Links must be safe: `javascript:`, `data:`, `vbscript:`, `mailto:` and relative URLs should not fetch or navigate.
3. Images should not load (the page loads only two pinned libraries; new image fetches would break that guarantee).
4. The library must load from a single pinned URL, with no build step, matching the Mermaid precedent.
5. If the library doesn't load, the page must show plain text, not blank or error states.

## Decision

### Library choice and pinning

**D1: markdown-it@14.1.0.** UMD format, one self-contained file, MIT license, no runtime dependencies. Safe by configuration (unlike `marked`, which has no HTML escaping and would need a second library, DOMPurify). Hand-written renderers would break the single-function rule.

**D2: CDN pinned URL:** `https://cdn.jsdelivr.net/npm/markdown-it@14.1.0/dist/markdown-it.min.js`. Loaded dynamically via `import()`, same as Mermaid. No build step, no version management in the repo.

**D3: Testable offline.** Vendored copy (test data, not shipped) at `agile-team/runner/tests/vendor/markdown-it-14.1.0.min.js`. Tests run against the real library file, byte for byte. Version pin verified by parsing the URL and checking the file exists.

### Configuration (safe by design)

**D4: One renderer function `md(text)`** — the only place where `markdown.render()` is called. All Markdown display (Questions tab, timeline handoff summaries, answered question text) goes through it. No other code calls `.render()` on the library.

**D5: Configuration for safety:**
- `html: false` — escapes raw HTML tags and attributes as text (e.g., `<script>` becomes `&lt;script&gt;`).
- `linkify: false` — bare URLs are not auto-linked; write `<https://…>` to make a link.
- `breaks: true` — single newlines stay as `<br>`, preserving pre-line text formatting.
- `disable("image")` — `![alt](url)` never fetches; the syntax is silently ignored and shown as text.

**D6: Link validation.** Every link (markdown `[text](url)`, autolink `<url>`, reference link) is tested against `const SAFE_LINK = /^https?:\/\//i`. Refused links (starting with `javascript:`, `data:`, `vbscript:`, `mailto:`, relative, `#fragment`) do not render as links; markdown-it shows their source as text.

**D7: Link attributes.** Every `<a>` tag gets `target="_blank"` and `rel="noopener noreferrer"`. The `link_open` token rule modifies every link before rendering.

**D8: Supported syntax** from markdown-it's `default` preset: headings, paragraphs, lists (bulleted and numbered), emphasis (`*italic*`, `**bold**`), strikethrough (`~~text~~`), inline code, fenced code blocks (with language class), tables, blockquotes, horizontal rules, and links.

### Loading and fallback

**D9: Load once at boot, no retry.** `boot()` calls `loadMarkdown()` without awaiting it. The library is fetched dynamically from the pinned URL. On success, `globalThis.markdownit` is set (UMD wrapper behavior in module scope), `useMarkdown()` runs, and the page re-renders. On any failure (network, CSP, malformed wrapper, timeout), the promise resolves without rejecting, console warns with the error, and `markdown` stays `null`.

**D10: Plain text fallback.** Until the library arrives (or if it fails), `md(text)` returns escaped plain text in a fallback wrapper: `<div class="md plain">` + escaped text + `</div>`. No text becomes `null` or `undefined`; empty inputs give an empty div.

**D11: After load, full render.** Once the library arrives, `md(text)` calls `markdown.render()` and wraps the result: `<div class="md">` + HTML + `</div>`. The `.md.plain` class is removed; CSS switches from pre-line to normal wrapping to let rendered block elements flow.

### Usage in the page

**D12: Questions tab (AC3).** Open question text, raised question text (in handoffs), and answered question and answer text use `md()`. Pills, IDs, copy buttons stay escaped. A new `.q-answer` div holds answered questions with smaller font and upper margin.

**D13: Timeline (AC3).** A data-driven `MARKDOWN_KINDS` set contains kinds that use `md()`: `step-end` (handoff summary), `message` (step-start brief, etc.), and `answer` (Q&A row). Other kinds (`gate`, `hold`, `release`, etc.) stay escaped. Helper `bodyHtml(kind, text)` picks the renderer based on kind.

**D14: CSS for Markdown blocks.** `.md` resets `white-space: normal` to let rendered block elements flow. `.md.plain` keeps `pre-line` for plain text. Margin collapsing is reset on first and last children. All block elements (`p`, `ul`, `ol`, `pre`, `table`, `blockquote`) get bottom margin of 6px. Headings, lists, and code blocks are styled with existing tokens (`--surface-2`, `--accent`, `--grid`, `--ink-2`).

### Coverage and scope

**D15: No Python changes.** The snapshot, server, and `fixtures/snapshot.json` stay the same. Markdown rendering is a front-end display detail; the data contract is unchanged.

**D16: Two outside URLs (rule change).** The "only outside URL is Mermaid" rule becomes "only outside URLs are pinned Mermaid and markdown-it". The e2e URL scan verifies exactly these two, no others.

### Rules (M1–M12 from design, enforced in code)

| # | Rule | AC |
|---|---|---|
| M1 | **One renderer.** `md(text)` is the only function that turns Markdown into HTML. `markdownit(` appears once, inside `safeMarkdown`. No other code calls `.render()` on the library. | AC1, AC3 |
| M2 | **Output shape.** Loaded: `<div class="md">` + `markdown.render(String(text ?? ""))` + `</div>`. Not loaded: `<div class="md plain">` + `esc(text)` + `</div>`. Null/undefined give empty div. | AC1, AC4 |
| M3 | **Syntax:** markdown-it `default` preset with `{ html: false, linkify: false, typographer: false, breaks: true }` and `disable("image")`. | AC1 |
| M4 | **No raw HTML.** `html: false` escapes all tags and attributes. | AC2 |
| M5 | **Links: http(s) only.** `validateLink = (url) => SAFE_LINK.test(url)` with `const SAFE_LINK = /^https?:\/\//i`. Other schemes and relative URLs show as text. | AC2 |
| M6 | **Link attributes.** `link_open` rule sets `target="_blank"` and `rel="noopener noreferrer"` on every link. | AC2 |
| M7 | **No images.** `disable("image")` prevents `![](url)` from fetching. | AC2 |
| M8 | **Load once at boot, re-render on arrival.** `boot()` calls `loadMarkdown()` not awaited. Promise resolves on success or error; never rejects. On success, `useMarkdown()` then `render()`. On failure, warns and stays `null`. No retry. | AC4 |
| M9 | **Where it is used.** Questions tab: open, raised, and answered question text. Timeline: `step-end`, `message`, `answer` row bodies. All else plain text. | AC3 |
| M10 | **Timeline picks by data.** `const MARKDOWN_KINDS = new Set(["step-end", "message", "answer"]); const bodyHtml = (kind, text) => MARKDOWN_KINDS.has(kind) ? md(text) : esc(text);` | AC3 |
| M11 | **No literal URLs in code.** `MARKDOWN_URL` constant holds the pinned URL. `SAFE_LINK` written with escaped slashes and "http(s)" comment. | AC4 |
| M12 | **Styles.** `.md`, `.md.plain`, `.md > :first/last-child`, block elements, headings, lists, code, pre, blockquote, links use existing tokens. `.md.plain` keeps `pre-line`. | AC1, AC4 |

## Consequences

**Questions are now readable** on the dashboard, with formatting preserved. Long handoff summaries and Q&A text benefit most (lists, code blocks, emphasis).

**Safe by design.** Raw HTML is escaped, dangerous schemes are blocked, images don't load. The configuration is portable (markdown-it's settings are stable); changing the renderer later would be a one-file change to `safeMarkdown()`.

**Two outside URLs now.** The frontend loads Mermaid and markdown-it from CDN. Both are pinned versions with no build step. The e2e test verifies no others exist (beyond SVG namespace, which is internal).

**Graceful degradation.** If the library doesn't load, users see plain text, not breakage. Reloading the page retries; the fallback is permanent per session unless the user refreshes.

**One function, no copies.** All Markdown rendering passes through `md()`, enforced by code review. The test suite verifies `markdownit(` and `.render(` occur only in the right place (M1 test).

## Related decisions

- **ADR-0003 (s3):** Mermaid flowcharts from CDN. This decision treats markdown-it the same way: pinned URL, dynamic import, no build step.
- **ADR-0004 (s5):** CSS tokens. Markdown styles use the same token set.
- **ADR-0005 (s8):** Consistent HTML escaping. This decision ensures `esc()` is used for plain text, `md()` for Markdown.
- **ADR-0027 (s4):** Dashboard snapshot raw data contract. No snapshot changes; Markdown is a display layer on existing data.
