# ADR-0005: Consistent HTML escaping for all snapshot strings

**Date:** 2026-10-10  
**Status:** Accepted  
**Affected:** Dashboard rendering security (s5)

## Context

The dashboard renders user-provided strings from the snapshot: story IDs, requirement IDs, AC IDs, role names, filter values, etc. These strings may contain special characters (`<`, `>`, `"`, `'`, `&`) that can break HTML markup or enable injection attacks.

Three approaches:
1. **Trust all strings (unsafe):** Render `${id}` directly into attributes and text
2. **Escape at the edge:** Use `esc()` helper when placing each string into HTML
3. **Type-safe templates:** Use a template language that escapes by default

## Decision

Establish a rule: **Every snapshot string that reaches `innerHTML` or attributes must be escaped through the `esc()` helper.**

`esc(s)` encodes `<`, `>`, `&`, `"`, and `'` as HTML entities (`&lt;`, `&gt;`, `&amp;`, `&quot;`, `&#39;`).

A reviewer checks that every interpolation matches the rule; violations are defects.

## Consequences

**Safe:**
- A `"` in a story ID cannot break a quoted attribute
- A `<` in a role name cannot inject an HTML tag
- Even if a snapshot string is malformed JSON, it cannot break the rendered page
- Mermaid's `securityLevel: "strict"` provides defense-in-depth, so escaping errors do not reach the SVG

**Predictable:**
- Rule is simple and mechanical (escaping is a grep away)
- All strings handled uniformly; no special cases

**Trade-offs:**
- Double-escaping is possible if escaping happens twice. Tooltip text is escaped once; the attribute is escaped again. This is safe (decoded once on display) but verbose.
- Mermaid labels must escape `"`, `<`, `>` differently (`mmdText()` uses `#quot;`, `#lt;`, `#gt;`). Two separate helpers needed.

## Implementation

**D2 (review round 1):**
In `index.html`, six places were unescaped in round 1:
- Timeline filter `value` attribute: `value="${s.id}"` → `value="${esc(s.id)}"`
- Board column class: `class="col ${id}"` → `class="col ${esc(id)}"`
- Requirement chip: `<span class="req-chip">${r}</span>` → `<span class="req-chip">${esc(r)}</span>`
- Matrix header: `<th class="req">${id}</th>` → `<th class="req">${esc(id)}</th>`
- AC id (bold): `<b>${c.ac.id}</b>` → `<b>${esc(c.ac.id)}</b>`
- Requirements list id: `<span class="id">${r.id}</span>` → `<span class="id">${esc(r.id)}</span>`
- Questions id in code: `<code>${q.id}</code>` → `<code>${esc(q.id)}</code>`
- Questions id in attribute: `data-copy='${q.id}'` → `data-copy='${esc(q.id)}'` (single-quoted; `&#39;` is safe)

All fixed in review round 3 (commit afdf32d3).

**Rule for reviewers:**
- Every `${…}` that places a snapshot field into HTML must be wrapped with either `esc()` (for HTML) or `mmdText()` (for Mermaid labels)
- Exception: computed values that are already safe (e.g., the result of `map().join()` of escaped strings)
- Exception: values that come from code, not snapshots (e.g., `[0-9]+` regex matches)

**Safe grep patterns (not exhaustive):**
```
# OK patterns:
${ *esc\(
data-[a-z-]*=["'].*\${esc\(
href="${esc\(

# Suspicious patterns (may be OK, but check):
${ *[a-z.-]+\}[^)]
innerHTML *=.*\$
<span .*\${[a-z]
```

**Helper functions in code:**
- `esc(s)` (existing): encodes `<>\"'&` for HTML context
- `mmdText(s)` (existing): encodes `<>"` as Mermaid entities for labels
