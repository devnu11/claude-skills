# Developer (GUI): Current context and conventions

**Last updated:** 2026-10-12 (s15 done)

See `developer.md` for base conventions.

## s15 complete: Dashboard renders Markdown safely

Questions tab and timeline now display Markdown with formatting (headings, lists, emphasis, code, tables) and fall back to plain text if the library doesn't load. All four ACs pass.

- **AC1 syntax:** `md()` renders headings, paragraphs, lists, emphasis, inline/fenced code, tables, links via markdown-it default preset.
- **AC2 safe:** Raw HTML escapes (`html: false`), links http(s) only (`validateLink`), images disabled, script/onerror payloads inert (confirmed in tests).
- **AC3 one function:** `md(text)` is the only renderer; questions, raised questions, answered questions, and timeline bodies (step-end, message, answer) use it. Plain text stays escaped.
- **AC4 pinned URL:** markdown-it@14.1.0 loaded from CDN like Mermaid, graceful plain-text fallback, testable offline with vendored copy.

**Implementation notes:**
- New markdown section in `index.html` (MARKDOWN_URL, SAFE_LINK, markdown state, functions: safeMarkdown, useMarkdown, loadMarkdown, md).
- `boot()` calls `loadMarkdown()` (not awaited); on success, useMarkdown then re-render; on failure, warn and stay plain.
- `renderQuestions` and `renderAnswered` call `md()` for question/answer text; `.q-answer` div styled smaller.
- Timeline: data-driven `MARKDOWN_KINDS` set and `bodyHtml()` helper pick renderer by kind.
- CSS: `.md` normal wrap, `.md.plain` pre-line; block elements 6px margin, headings bold, lists indented, code/pre on surface-2.
- Vendored copy in tests/vendor/markdown-it-14.1.0.min.js for offline e2e (integration-tester's job).

**Rule change (ADR-0042):** "Only outside URL is Mermaid" becomes "exactly two outside URLs: Mermaid and markdown-it" (both pinned).
