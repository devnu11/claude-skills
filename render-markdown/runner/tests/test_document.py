"""Markdown to an HTML body (AC1.1-AC1.4, AC1.6)."""

from __future__ import annotations

from pathlib import Path

from conftest import FIXTURES
from render_markdown.document import TitleSource, is_relative, load_document


def write(tmp_path: Path, text: str) -> Path:
    source = tmp_path / "note.md"
    source.write_text(text)
    return source


def test_the_sample_renders_elements_not_syntax() -> None:
    body = load_document(FIXTURES / "sample.md").body
    assert '<div class="wide"><table>' in body and "</table></div>" in body
    assert "<strong>bold</strong>" in body and "<blockquote>" in body
    assert "|---|" not in body.split("<pre")[0]


def test_the_title_is_the_first_top_level_heading() -> None:
    document = load_document(FIXTURES / "sample.md")
    assert (document.title, document.title_source) == ("Sample render title", TitleSource.HEADING)


def test_without_a_heading_the_title_is_the_file_name(tmp_path: Path) -> None:
    document = load_document(write(tmp_path, "## Only a second level\n\ntext\n"))
    assert (document.title, document.title_source) == ("note", TitleSource.FILE_NAME)


def test_mermaid_blocks_are_numbered_and_kept_as_source() -> None:
    document = load_document(FIXTURES / "sample.md")
    assert '<pre class="mermaid" data-index="1">graph TD' in document.body
    assert '<pre class="mermaid" data-index="2">' in document.body
    assert document.diagrams[0] == "graph TD\n  Start --> End\n"


def test_code_text_holds_code_but_not_diagrams() -> None:
    document = load_document(FIXTURES / "sample.md")
    assert "#include <stdio.h>" in document.code_text and "**kwargs" in document.code_text
    assert "Start --> End" not in document.code_text


def test_relative_links_and_images_become_file_urls(tmp_path: Path) -> None:
    (tmp_path / "pic.png").write_bytes(b"png")
    source = write(tmp_path, "[other](other.md#part) ![pic](pic.png) [web](https://x.org/a)\n")
    document = load_document(source)
    assert f'href="{(tmp_path / "other.md").resolve().as_uri()}#part"' in document.body
    assert f'src="{(tmp_path / "pic.png").resolve().as_uri()}"' in document.body
    assert 'href="https://x.org/a"' in document.body and document.warnings == ()


def test_a_missing_image_is_a_warning() -> None:
    assert load_document(FIXTURES / "sample.md").warnings == ("missing image: no-such.png",)


def test_only_local_paths_are_relative() -> None:
    assert is_relative("a/b.md") and is_relative("pic%20one.png")
    for target in ("#part", "/abs/x.md", "https://x.org", "mailto:a@b.c", ""):
        assert not is_relative(target)


def test_links_inside_code_are_left_as_written(tmp_path: Path) -> None:
    document = load_document(write(tmp_path, 'Write `<img src="pic.png">` or `<a href="x.md">`.\n'))
    assert 'src="pic.png"' in document.body and 'href="x.md"' in document.body
    assert document.warnings == ()


def test_escaped_marks_are_literal_text(tmp_path: Path) -> None:
    document = load_document(write(tmp_path, "Plain line\nShow \\*\\*bold\\*\\* and \\|---\\|\n"))
    assert document.literal_text == "Show **bold** and |---|"
