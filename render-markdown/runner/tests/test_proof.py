"""The PDF's self-check and preview (AC6.1-AC6.3)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pypdfium2 as pdfium

from conftest import FIXTURES
from render_markdown.document import Document, TitleSource, load_document
from render_markdown.proof import (
    Raster,
    check_pdf,
    encode_png,
    find_blank_pages,
    find_missing_title,
    find_raw_markdown,
    find_undrawn_diagrams,
    render_first_page,
)

SAMPLE = load_document(FIXTURES / "sample.md")


def make_document(code_text: str = "", diagrams: tuple[str, ...] = ()) -> Document:
    return Document(Path("x.md"), "T", TitleSource.HEADING, "", code_text, "", diagrams, ())


def make_blank_pdf(path: Path, pages: int = 1) -> Path:
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(612, 792)
    pdf.save(path)
    pdf.close()
    return path


def test_raw_markdown_outside_code_is_found() -> None:
    texts = ["Intro\n|---|---|\n**not bold** here\n```\n"]
    kinds = [
        problem.split("(")[1].split(")")[0] for problem in find_raw_markdown(texts, make_document())
    ]
    assert kinds == ["table rule", "bold markers", "code fence"]


def test_hashes_and_code_are_never_raw_markdown() -> None:
    texts = ["# a comment, #####, and **kwargs: f(**a, **b)\n|-----|---------|\n```sh\n# H\n"]
    assert find_raw_markdown(texts, SAMPLE) == []


def test_a_problem_names_the_page_and_the_line() -> None:
    assert find_raw_markdown(["ok", "x |---| y"], make_document()) == [
        "page 2: raw Markdown (table rule): x |---| y"
    ]


def test_a_diagram_whose_source_shows_was_not_drawn() -> None:
    document = make_document(diagrams=("graph TD\n  Start --> End\n",))
    assert find_undrawn_diagrams(["graph TD\nStart --> End"], document) == [
        "Mermaid diagram 1 was not drawn: graph TD"
    ]


def test_a_drawn_diagram_shows_only_its_labels() -> None:
    document = make_document(diagrams=("graph TD\n  Start --> End\n",))
    assert find_undrawn_diagrams(["Title\nStart\nEnd"], document) == []


def test_a_failed_diagram_with_its_note_is_not_a_problem() -> None:
    document = make_document(diagrams=("graph TD\n  A --> B\n", "graph TD\n  A[Broken --> ((\n"))
    text = "A\nB\ngraph TD\nA[Broken --> ((\nMermaid diagram 2 could not be drawn: Parse error"
    assert find_undrawn_diagrams([text], document) == []


def test_diagram_source_inside_a_code_block_is_not_a_problem() -> None:
    document = make_document("graph TD\n  Start --> End\n", ("graph TD\n  Start --> End\n",))
    assert find_undrawn_diagrams(["graph TD\nStart --> End"], document) == []


def test_a_page_with_nothing_on_it_is_blank(tmp_path: Path) -> None:
    pdf = pdfium.PdfDocument(make_blank_pdf(tmp_path / "blank.pdf", 2))
    assert find_blank_pages(pdf, ["text", ""]) == ["page 2: blank"]
    pdf.close()


def test_page_one_must_show_a_heading_title() -> None:
    document = make_document()
    assert find_missing_title(["no title here"], document) == ["page 1: the title is missing: T"]
    assert find_missing_title(["T\nmore"], document) == []
    named = Document(Path("x.md"), "x", TitleSource.FILE_NAME, "", "", "", (), ())
    assert find_missing_title(["anything"], named) == []
    assert find_missing_title([], document) == []


def test_prove_pdf_counts_pages_and_finds_blank_ones(tmp_path: Path) -> None:
    proof = check_pdf(make_blank_pdf(tmp_path / "blank.pdf", 2), make_document())
    assert proof.pages == 2
    assert proof.problems == ("page 1: blank", "page 2: blank", "page 1: the title is missing: T")


def test_the_preview_is_a_png_of_page_one(tmp_path: Path) -> None:
    preview = tmp_path / "page1.png"
    render_first_page(make_blank_pdf(tmp_path / "blank.pdf"), preview)
    data = preview.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (980, 1268)


def test_encode_png_drops_row_padding() -> None:
    raster = Raster(1, 2, 4, bytes([1, 2, 3, 9, 4, 5, 6, 9]))
    data = encode_png(raster)
    idat = data.index(b"IDAT")
    length = struct.unpack(">I", data[idat - 4 : idat])[0]
    assert zlib.decompress(data[idat + 4 : idat + 4 + length]) == bytes([0, 1, 2, 3, 0, 4, 5, 6])


def test_escaped_markdown_is_not_raw_markdown() -> None:
    document = Document(Path("x.md"), "T", TitleSource.HEADING, "", "", "a **b** |---|", (), ())
    assert find_raw_markdown(["a **b** |---|"], document) == []
