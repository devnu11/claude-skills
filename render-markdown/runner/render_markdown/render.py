"""The pipeline every verb shares: Markdown to a page, and the page to a checked PDF."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import chrome
from .document import Document, load_document
from .page import build_page
from .paper import Paper
from .proof import Proof, check_pdf, render_first_page

OUTPUT_DIR = "render-markdown"


@dataclass(frozen=True)
class Rendering:
    """A rendered and checked PDF, with its page-1 preview."""

    document: Document
    pdf: Path
    preview: Path
    proof: Proof


def get_output_dir() -> Path:
    """``<system temp>/render-markdown``, made on first use."""
    folder = Path(tempfile.gettempdir()) / OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_page(source: Path, paper: Paper) -> tuple[Document, Path]:
    """Render ``source`` to ``<output dir>/<stem>.html``, replacing any earlier one."""
    document = load_document(source)
    page = get_output_dir() / f"{source.stem}.html"
    page.write_text(build_page(document, paper), encoding="utf-8")
    return document, page


@dataclass(frozen=True)
class PdfRequest:
    """A Markdown file to render as a PDF on ``paper``, at ``pdf`` or the default path."""

    source: Path
    paper: Paper
    pdf: Path | None = None


def render_pdf(request: PdfRequest) -> Rendering:
    """Render the request's file to a PDF, check it and draw page 1 beside it."""
    document, page = write_page(request.source, request.paper)
    default = get_output_dir() / f"{request.source.stem}.pdf"
    target = (request.pdf or default).resolve()
    chrome.write_pdf(page, target)
    preview = target.with_name(f"{target.stem}.page1.png")
    render_first_page(target, preview)
    return Rendering(document, target, preview, check_pdf(target, document))
