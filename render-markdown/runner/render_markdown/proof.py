"""Check a finished PDF reads as rendered, and draw its first page for a look."""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from .document import Document, TitleSource
from .page import FAILED_PATTERN

PREVIEW_SCALE = 1.6
TELLING_LENGTH = 6
RAW_MARKDOWN = {
    "table rule": re.compile(r"\|\s*:?-{3,}"),
    "bold markers": re.compile(r"\*\*[^*\s][^*]*?\*\*"),
    "code fence": re.compile(r"`{3,}"),
}


@dataclass(frozen=True)
class Raster:
    """RGB pixels in rows of ``stride`` bytes."""

    width: int
    height: int
    stride: int
    pixels: bytes

    def read_row(self, row: int) -> bytes:
        """Row ``row``'s pixels, without the row's padding."""
        start = row * self.stride
        return self.pixels[start : start + self.width * 3]


@dataclass(frozen=True)
class Proof:
    """What the check found in a PDF."""

    pages: int
    problems: tuple[str, ...]


def check_pdf(pdf: Path, document: Document) -> Proof:
    """Read every page of ``pdf`` and list what shows it wasn't rendered properly."""
    reader = pdfium.PdfDocument(pdf)
    texts = [page.get_textpage().get_text_range() for page in reader]
    problems = [
        *find_raw_markdown(texts, document),
        *find_undrawn_diagrams(texts, document),
        *find_blank_pages(reader, texts),
        *find_missing_title(texts, document),
    ]
    reader.close()
    return Proof(len(texts), tuple(problems))


def strip_spaces(text: str) -> str:
    """``text`` without whitespace, so line breaks and spacing don't matter."""
    return re.sub(r"\s+", "", text)


def find_raw_markdown(texts: list[str], document: Document) -> list[str]:
    """Markdown syntax in the PDF's text that no code, escaped text or diagram explains."""
    allowed = strip_spaces(document.code_text + document.literal_text + "".join(document.diagrams))
    return [
        f"page {number}: raw Markdown ({kind}): {line.strip()[:80]}"
        for number, text in enumerate(texts, 1)
        for line in text.splitlines()
        for kind, pattern in RAW_MARKDOWN.items()
        if any(strip_spaces(match) not in allowed for match in pattern.findall(line))
    ]


def find_undrawn_diagrams(texts: list[str], document: Document) -> list[str]:
    """Diagrams whose own source lines show in the PDF though no note says they failed."""
    joined = "\n".join(texts)
    failed = {int(number) for number in re.findall(FAILED_PATTERN, joined)}
    failed_sources = [s for n, s in enumerate(document.diagrams, 1) if n in failed]
    explained = strip_spaces(document.code_text + "".join(failed_sources))
    shown = {
        number: list_shown_lines(source, Evidence(strip_spaces(joined), explained))
        for number, source in enumerate(document.diagrams, 1)
        if number not in failed
    }
    return [
        f"Mermaid diagram {number} was not drawn: {lines[0][:80]}"
        for number, lines in shown.items()
        if lines
    ]


@dataclass(frozen=True)
class Evidence:
    """The PDF's text, and the text that code and failed diagrams already explain."""

    printed: str
    explained: str


def list_shown_lines(source: str, evidence: Evidence) -> list[str]:
    """Lines only this diagram has (six or more characters) that the PDF shows as text."""
    lines = [line.strip() for line in source.splitlines()]
    telling = [line for line in lines if len(strip_spaces(line)) >= TELLING_LENGTH]
    return [
        line
        for line in telling
        if strip_spaces(line) not in evidence.explained and strip_spaces(line) in evidence.printed
    ]


def find_blank_pages(reader: pdfium.PdfDocument, texts: list[str]) -> list[str]:
    """Pages with no text and nothing drawn on them."""
    return [
        f"page {number}: blank"
        for number, text in enumerate(texts, 1)
        if not text.strip() and not any(True for _ in reader[number - 1].get_objects())
    ]


def find_missing_title(texts: list[str], document: Document) -> list[str]:
    """A heading title that page 1 doesn't show."""
    if document.title_source is not TitleSource.HEADING or not texts:
        return []
    if strip_spaces(document.title) in strip_spaces(texts[0]):
        return []
    return [f"page 1: the title is missing: {document.title[:80]}"]


def render_first_page(pdf: Path, preview: Path) -> None:
    """Write page 1 of ``pdf`` as a PNG at ``preview``."""
    reader = pdfium.PdfDocument(pdf)
    bitmap = reader[0].render(scale=PREVIEW_SCALE, rev_byteorder=True)
    raster = Raster(bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer))
    preview.write_bytes(encode_png(raster))
    reader.close()


def encode_png(raster: Raster) -> bytes:
    """An 8-bit RGB PNG of ``raster``."""
    lines = b"".join(b"\0" + raster.read_row(row) for row in range(raster.height))
    header = struct.pack(">IIBBBBB", raster.width, raster.height, 8, 2, 0, 0, 0)
    chunks = [("IHDR", header), ("IDAT", zlib.compress(lines, 9)), ("IEND", b"")]
    return b"\x89PNG\r\n\x1a\n" + b"".join(encode_chunk(kind, data) for kind, data in chunks)


def encode_chunk(kind: str, data: bytes) -> bytes:
    """One PNG chunk: length, type, data and CRC."""
    tagged = kind.encode() + data
    return struct.pack(">I", len(data)) + tagged + struct.pack(">I", zlib.crc32(tagged))
