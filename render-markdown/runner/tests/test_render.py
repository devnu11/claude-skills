"""The shared pipeline, with a real Chrome (AC1.1, AC1.4, AC1.5, AC3.1, AC6.1-AC6.3)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from conftest import FIXTURES
from render_markdown.paper import Paper
from render_markdown.render import PdfRequest, render_pdf, write_page


def test_write_page_replaces_the_html_in_the_output_dir(output_dir: Path) -> None:
    _, page = write_page(FIXTURES / "sample.md", Paper.LETTER)
    assert page == output_dir / "sample.html" and "<title>Sample" in page.read_text()


@pytest.mark.chrome
def test_the_sample_renders_draws_its_diagram_and_passes(
    real_chrome: Path, output_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    rendering = render_pdf(PdfRequest(FIXTURES / "sample.md", Paper.A4))
    assert rendering.pdf == output_dir / "sample.pdf"
    assert (rendering.proof.pages, rendering.proof.problems) == (1, ())
    assert list(home.iterdir()) == []


@pytest.mark.chrome
def test_the_preview_has_the_paper_shape(
    real_chrome: Path, output_dir: Path, tmp_path: Path
) -> None:
    rendering = render_pdf(PdfRequest(FIXTURES / "sample.md", Paper.A4, tmp_path / "a4.pdf"))
    assert rendering.preview == tmp_path / "a4.page1.png"
    width, height = struct.unpack(">II", rendering.preview.read_bytes()[16:24])
    assert abs(height / width - 297 / 210) < 0.01


@pytest.mark.chrome
def test_markdown_that_slipped_through_fails_the_check(
    real_chrome: Path, output_dir: Path, tmp_path: Path
) -> None:
    rendering = render_pdf(PdfRequest(FIXTURES / "raw.md", Paper.LETTER, tmp_path / "raw.pdf"))
    assert rendering.proof.problems == (
        "page 1: raw Markdown (table rule): |---|---|",
        "page 1: raw Markdown (bold markers): **not bold**",
    )
