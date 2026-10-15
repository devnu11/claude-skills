---
name: render-markdown
description: Show a Markdown file rendered for reading - opened in the browser, as a checked PDF, or printed on paper - instead of improvising a converter. Use when the user says "render this markdown", "preview this markdown", "show me X rendered", "open it in my browser", "make a PDF of", "print this to my printer", "print it on paper" or "send it to my printer". A bare "print this" is not a trigger: it usually means printing a value.
---

# render-markdown

One renderer, three outputs. Tables, code, block quotes and Mermaid diagrams
render the same in the browser, the PDF and on paper. Every flag, the checks
and the exit codes are in `reference/protocol.md` next to this file.

```sh
RM="uv run --frozen --quiet --project ~/.claude/skills/render-markdown/runner render-markdown"
```

`--frozen` runs the skill's tested `uv.lock` as it is; never drop it.

| Command | What it does |
|---|---|
| `$RM open FILE.md` | Render and open in the default browser. Prints the HTML's path. |
| `$RM pdf FILE.md [-o OUT.pdf] [--paper a4\|letter]` | Render to a PDF and check it. Prints the PDF and its page-1 preview PNG. |
| `$RM print FILE.md [--printer NAME] [--sides two\|one] [--copies N] [--dry-run]` | Render, check, send, and follow the job until the printer reports pages. |

`pdf` and `print` need Chrome 112 or later; `print` needs CUPS (macOS or Linux).

## Steps

1. **Where to show it.** When the request doesn't say, run `open` and give
   the path (a session without a display can still use it). "Make a PDF"
   means `pdf`. Print only when the human asked for paper in this request.
2. **Printing:**
   1. Run `print … --dry-run`. It renders, checks, and reports the printer,
      pages and sides, sending nothing.
   2. Read the preview PNG it names with the Read tool. Stop if page 1 shows
      raw Markdown, broken tables, a blank or cut-off page, or a diagram as
      source text.
   3. Ask once: the printer, the page count, and two-sided (the default)
      unless the request already said.
   4. Run `print` without `--dry-run`.
3. **A failed check** (exit 1, `problem:` lines) means the PDF isn't fit to
   read: report the problems, don't print it, and don't hand-patch the PDF.
4. **Report one line:** the path, or `printed N pages on PRINTER`. Never say a
   job printed because `lp` gave a job id: only `printed:` from the command
   means paper came out. Never paste the rendered content into the chat.
