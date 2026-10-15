"""Markdown to an HTML body, with what the later checks need to know about it."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlsplit

import markdown

EXTENSIONS = ("tables", "fenced_code", "sane_lists", "toc")
MERMAID_BLOCK = re.compile(r'<pre><code class="language-mermaid">(.*?)</code></pre>', re.S)
CODE = re.compile(r"<code[^>]*>(.*?)</code>", re.S)
LINK = re.compile(r'\b(src|href)="([^"]*)"')
TAG = re.compile(r"<[^>]+>")


class TitleSource(StrEnum):
    """Where a document's title came from."""

    HEADING = "heading"
    FILE_NAME = "file name"


@dataclass(frozen=True)
class Document:
    """A rendered Markdown file."""

    source: Path
    title: str
    title_source: TitleSource
    body: str
    code_text: str
    diagrams: tuple[str, ...]
    warnings: tuple[str, ...]


def load_document(source: Path) -> Document:
    """Render ``source`` to an HTML body and collect its title, code, diagrams and warnings."""
    converter = markdown.Markdown(extensions=list(EXTENSIONS))
    body = converter.convert(source.read_text(encoding="utf-8"))
    title, title_source = find_title(converter.toc_tokens, source)
    body, warnings = replace_links(body, source.parent)
    diagrams = tuple(html.unescape(text) for text in MERMAID_BLOCK.findall(body))
    body = mark_diagrams(wrap_tables(body))
    code_text = "\n".join(html.unescape(text) for text in CODE.findall(body))
    return Document(source, title, title_source, body, code_text, diagrams, warnings)


def find_title(tokens: list[dict], source: Path) -> tuple[str, TitleSource]:
    """The first top-level heading's text, else the file name."""
    for token in tokens:
        if token["level"] == 1:
            return html.unescape(TAG.sub("", token["name"])), TitleSource.HEADING
    return source.stem, TitleSource.FILE_NAME


def mark_diagrams(body: str) -> str:
    """Turn each fenced Mermaid block into a numbered ``<pre class="mermaid">``."""
    numbers = iter(range(1, len(MERMAID_BLOCK.findall(body)) + 1))

    def mark(match: re.Match[str]) -> str:
        return f'<pre class="mermaid" data-index="{next(numbers)}">{match[1]}</pre>'

    return MERMAID_BLOCK.sub(mark, body)


def wrap_tables(body: str) -> str:
    """Wrap each table so a wide one scrolls sideways on screen."""
    opened = body.replace("<table>", '<div class="wide"><table>')
    return opened.replace("</table>", "</table></div>")


def replace_links(body: str, base: Path) -> tuple[str, tuple[str, ...]]:
    """Point relative ``src`` and ``href`` at absolute file URLs; name missing images."""
    warnings: list[str] = []

    def replace_link(match: re.Match[str]) -> str:
        attribute, target = match[1], html.unescape(match[2])
        if not is_relative(target):
            return match[0]
        path = (base / unquote(urlsplit(target).path)).resolve()
        if attribute == "src" and not path.exists():
            warnings.append(f"missing image: {target}")
        return f'{attribute}="{html.escape(join_fragment(path, target))}"'

    return LINK.sub(replace_link, body), tuple(warnings)


def is_relative(target: str) -> bool:
    """A local path, not a URL, an absolute path or a fragment."""
    parts = urlsplit(target)
    return not (parts.scheme or parts.netloc or target.startswith(("#", "/")) or not parts.path)


def join_fragment(path: Path, target: str) -> str:
    """``path`` as a file URL, keeping the target's ``#fragment``."""
    fragment = urlsplit(target).fragment
    return path.as_uri() + (f"#{fragment}" if fragment else "")
