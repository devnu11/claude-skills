# render-markdown: how it works

## Rendering (every command)

- **Converter:** python-markdown with `tables`, `fenced_code`, `sane_lists` and
  `toc`. Every table is wrapped so it scrolls sideways on screen.
- **Title:** the first `#` heading's text, else the file name. It is the HTML
  `<title>`, the PDF's title and the print job's name.
- **Links and images:** relative `src` and `href` are rewritten to absolute
  `file://` URLs under the Markdown file's folder, keeping any `#fragment`,
  because the HTML is written elsewhere. Text inside code (`<code>`) is left as
  written, so a code span that quotes HTML stays as it was. A missing image is
  a `warning:` line; rendering goes on.
- **Mermaid:** a ```` ```mermaid ```` block becomes a numbered
  `<pre class="mermaid">`. The page loads mermaid.js 11.12.0 from jsDelivr
  (pinned in `page.MERMAID_URL`) only when there is a diagram, and draws each
  diagram on its own, with Mermaid's own error drawing off
  (`suppressErrorRendering`). A diagram that fails to parse shows its source in
  a code block, followed by "Mermaid diagram N could not be drawn: <reason>";
  the others still draw. Diagrams need the network, as the agent does.
- **One stylesheet** with `@media screen` rules (a 46rem column, the system's
  dark theme) and `@media print` rules (black on white, 10.5pt, table rows,
  figures and quotes never split, headings kept with what follows).
- **Paper**, written as `@page { size: … }`, is the first of:
  1. `--paper`;
  2. for `print`, the printer's default PageSize (`lpoptions -p NAME -l`), if
     it is Letter or A4;
  3. the locale: on macOS the region of `AppleLocale` (an `@rg=` override
     wins; US, CA or MX means letter, anything else, a locale with no region
     included, A4), on Linux the height
     `locale -k LC_PAPER` gives (279 mm is letter, anything else A4);
  4. letter.

## Output files

All go in `<system temp>/render-markdown/`, named after the Markdown file's
stem, and are replaced by the next render of the same name: `<stem>.html`,
`<stem>.pdf`, `<stem>.page1.png` and, for raster printing, `<stem>.raster`.
The commands never delete them. `pdf -o OUT.pdf` puts the PDF and its preview
(`OUT.page1.png`) beside `OUT.pdf` instead.

## Chrome

- **Found** through a table per OS (`chrome.CANDIDATES`), the first match
  winning: `RENDER_MARKDOWN_CHROME` first; macOS Google Chrome, Chromium,
  Edge or Brave under `/Applications`; Linux `google-chrome`,
  `google-chrome-stable`, `chromium` or `chromium-browser` on `PATH`; Windows
  `chrome.exe` under `%ProgramFiles%`, `%ProgramFiles(x86)%` or
  `%LocalAppData%`.
- **Version:** 112 or later (for `--headless=new` and
  `--no-pdf-header-footer`). It is read from `--version`, run in a scratch
  `HOME` (Linux's `google-chrome` wrapper writes under `$HOME` even then). On
  Windows it comes only from the version folder beside `chrome.exe`, because
  Windows Chrome has no `--version` and would open a browser window. A version
  that can't be read is accepted.
- **Run** with `--headless=new --no-pdf-header-footer --no-first-run
  --disable-crash-reporter --use-mock-keychain --virtual-time-budget=15000`,
  a scratch `--user-data-dir`, and `HOME` set to that scratch folder, which is
  removed afterwards. The time budget lets mermaid.js load and draw before the
  page prints.
- **Time limit:** every program the runner starts, Chrome included, is stopped
  after 300 s (exit 124), so a network that drops packets to the CDN fails the
  render instead of hanging it.
- **No page numbers:** Chrome's command line can't add a footer once its own
  header and footer are off.

## The check (`pdf` and `print`)

After printing to PDF, pypdfium2 reads every page's text, and the render
fails (exit 1, one `problem:` line each) on:

| Problem | Rule |
|---|---|
| Raw Markdown | A table rule (`\|---`), a `**…**` pair or a ```` ``` ```` fence in the text, unless that text is in one of the document's code blocks, code spans, diagram sources, or source lines that escape `*`, `\|` or a backtick with `\` (they render as literal marks on purpose). A `#` is never checked: code and comments have them. |
| An undrawn diagram | A source line of six or more characters that only that diagram has shows in the text, and no "could not be drawn" note names the diagram. |
| A blank page | A page with no text and nothing drawn on it. |
| A missing title | Page 1's text lacks a title that came from a heading. |

Page 1 is also drawn to `<stem>.page1.png` (pypdfium2, at 1.6×), so the agent
can look at the real page before printing.

## Printing

1. **The printer** is `--printer`, else `LPDEST` or `PRINTER`, else `lpstat -d`.
   With none, it exits 2 and lists `lpstat -p`. Windows is refused (exit 2):
   use `pdf`.
2. **Render and check.** A failed check sends nothing (exit 1).
   `--dry-run` stops here (exit 0).
3. **Convert** (`--send raster`, the default): `cupsfilter` with the queue's
   PPD makes `image/urf`, or `image/pwg-raster` when the PPD has no URF filter,
   with the sides passed as both `sides=` and the PPD's `Duplex`. The PPD is
   `/etc/cups/ppd/<printer>.ppd` when readable; otherwise (on Debian it is
   readable only by the `lp` group) a copy from the CUPS web server
   (`http://<server>/printers/<printer>.ppd`). A queue with no PPD or neither
   filter, or `--send pdf`, gets the PDF itself. Raster is the default because a Chrome PDF sent straight to an
   HP Color LaserJet Pro M453 completed with 0 pages printed, while the same
   document as URF printed.
4. **Send:** `lp -d PRINTER -t TITLE -n COPIES -o sides=two-sided-long-edge|one-sided
   -o document-format=<format> FILE`. Two-sided is the default.
5. **Follow:** every 2 s, for up to 5 minutes, `ipptool` asks the CUPS
   server (`ipp://<server>/printers/<printer>`) for the job's `job-state`,
   `job-state-reasons` and `job-impressions-completed`. The server is
   `CUPS_SERVER` when it names a host, else `localhost:631`.
6. **Whose count:** for a queue whose backend is `ipp` or `ipps` (a `dnssd`
   URI for an `_ipp` or `_ipps` service included), CUPS relays the printer's
   own count, so a positive count means paper came out. For any other backend
   (`usb`, `socket`, `lpd`…), CUPS counts pages itself and can't know whether
   the printer printed them; the result says so.

| Result | Output | Exit |
|---|---|---|
| Completed with pages the printer counted | `printed: N pages on PRINTER` | 0 |
| Completed with pages only CUPS counted (non-IPP backend) | `completed: CUPS counted N pages for job …; this printer's backend can't confirm paper came out` | 0 |
| Completed with 0 pages | `failed: job … completed but printed 0 pages` | 1 |
| Aborted or cancelled | `failed: job … ended <state> (<reasons>)` | 1 |
| Not finished after 5 minutes, or no count | `unconfirmed: job … is <state>; check the printer` | 1 |
| No `ipptool` installed (told at once) | `unconfirmed: job … sent; no ipptool to follow it` | 1 |

## Exit codes

0 done; 1 the check failed or the print wasn't confirmed; 2 a usage or setup
error (no such file, no Chrome, no printer, no browser opener, Windows `print`).
