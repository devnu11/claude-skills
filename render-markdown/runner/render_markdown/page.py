"""The whole HTML page: one stylesheet for screen and print, and the Mermaid loader."""

from __future__ import annotations

import html

from .document import Document
from .paper import PAGE_RULES, Paper

MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.12.0/dist/mermaid.min.js"
FAILED_NOTE = "Mermaid diagram {n} could not be drawn"
FAILED_PATTERN = r"Mermaid diagram (\d+) could not be drawn"

BASE_CSS = """
:root { --ink: #1b1b1b; --muted: #555; --paper: #fff; --rule: #b8b8b8;
  --shade: #f2f2f2; --link: #0b57d0; }
body { margin: 0; background: var(--paper); color: var(--ink);
  font: 16px/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
main { padding: 0 16px; }
h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 1.4em 0 0.5em; }
h1 { font-size: 1.8em; margin-top: 0.6em; }
h2 { font-size: 1.4em; border-bottom: 1px solid var(--rule); padding-bottom: 0.15em; }
h3 { font-size: 1.15em; }
a { color: var(--link); }
table { border-collapse: collapse; margin: 0.8em 0; }
th, td { border: 1px solid var(--rule); padding: 0.3em 0.55em; text-align: left;
  vertical-align: top; }
th { background: var(--shade); }
code, pre { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.88em; }
code { background: var(--shade); padding: 0 0.2em; border-radius: 3px; }
pre { background: var(--shade); padding: 0.7em 0.9em; border-radius: 4px;
  white-space: pre-wrap; overflow-wrap: anywhere; }
pre code { background: none; padding: 0; }
blockquote { margin: 0.8em 0; padding: 0 0 0 0.9em; border-left: 3px solid var(--rule);
  color: var(--muted); }
figure.diagram { margin: 1em 0; text-align: center; }
figure.diagram svg { max-width: 100%; height: auto; }
p.diagram-failed { color: var(--muted); font-style: italic; }
"""

SCREEN_CSS = """
@media screen {
  main { max-width: 46rem; margin: 2rem auto 4rem; }
  .wide { overflow-x: auto; }
  @media (prefers-color-scheme: dark) {
    :root { --ink: #e6e6e6; --muted: #a8a8a8; --paper: #161616; --rule: #4a4a4a;
      --shade: #252525; --link: #8ab4f8; }
  }
}
"""

PRINT_CSS = """
@media print {
  :root { --ink: #000; --muted: #333; --paper: #fff; --rule: #888; --shade: #f0f0f0;
    --link: #000; }
  body { font-size: 10.5pt; }
  main { padding: 0; }
  a { text-decoration: none; }
  h1, h2, h3, h4, h5, h6 { break-after: avoid; }
  tr, figure, blockquote { break-inside: avoid; }
  table { font-size: 9pt; width: 100%; }
}
"""

MERMAID_SCRIPT = """
<script src="{url}"></script>
<script>
(async () => {{
  mermaid.initialize({{ startOnLoad: false, theme: "neutral" }});
  for (const block of document.querySelectorAll("pre.mermaid")) {{
    const source = block.textContent, n = block.dataset.index;
    try {{
      const {{ svg }} = await mermaid.render("mermaid-" + n, source);
      const figure = document.createElement("figure");
      figure.className = "diagram";
      figure.innerHTML = svg;
      block.replaceWith(figure);
    }} catch (error) {{
      document.getElementById("dmermaid-" + n)?.remove();
      const pre = document.createElement("pre");
      pre.textContent = source;
      const note = document.createElement("p");
      note.className = "diagram-failed";
      const reason = String((error && error.message) || error).split("\\n")[0];
      note.textContent = "{note}: " + reason;
      block.replaceWith(pre, note);
    }}
  }}
  document.body.dataset.diagrams = "done";
}})();
</script>
"""


def build_page(document: Document, paper: Paper) -> str:
    """The complete HTML page for ``document``, laid out for ``paper`` when printed."""
    page_rule = f"@page {{ {PAGE_RULES[paper]}; }}"
    style = BASE_CSS + SCREEN_CSS + PRINT_CSS + page_rule
    head = "<meta charset=utf-8><meta name=viewport content='width=device-width'>"
    title = f"<title>{html.escape(document.title)}</title>"
    script = build_mermaid_script() if document.diagrams else ""
    main = f"<main>{document.body}</main>"
    return f"<!doctype html><html lang=en>{head}{title}<style>{style}</style>{main}{script}"


def build_mermaid_script() -> str:
    """The script that draws each diagram, or shows its source with a note when it can't."""
    return MERMAID_SCRIPT.format(url=MERMAID_URL, note=FAILED_NOTE.replace("{n}", '" + n + "'))
