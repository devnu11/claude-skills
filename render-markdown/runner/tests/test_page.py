"""The HTML page and its stylesheet (AC1.4, AC2.2, AC3.2, AC3.3)."""

from __future__ import annotations

from conftest import FIXTURES
from render_markdown.document import load_document
from render_markdown.page import MERMAID_URL, build_page
from render_markdown.paper import Paper


def test_the_page_has_the_title_and_the_paper() -> None:
    page = build_page(load_document(FIXTURES / "sample.md"), Paper.A4)
    assert "<title>Sample render title</title>" in page
    assert "@page { size: A4; margin: 18mm; }" in page


def test_the_print_rules_keep_rows_and_headings_together_in_black_on_white() -> None:
    page = build_page(load_document(FIXTURES / "sample.md"), Paper.LETTER)
    print_rules = page.split("@media print")[1]
    assert "tr, figure, blockquote { break-inside: avoid; }" in print_rules
    assert "h1, h2, h3, h4, h5, h6 { break-after: avoid; }" in print_rules
    assert "--ink: #000;" in print_rules and "--paper: #fff;" in print_rules


def test_the_screen_rules_follow_the_dark_theme_and_scroll_wide_tables() -> None:
    page = build_page(load_document(FIXTURES / "sample.md"), Paper.LETTER)
    screen_rules = page.split("@media screen")[1].split("@media print")[0]
    assert "prefers-color-scheme: dark" in screen_rules and "overflow-x: auto" in screen_rules


def test_mermaid_loads_only_when_there_are_diagrams(tmp_path) -> None:
    with_diagrams = build_page(load_document(FIXTURES / "sample.md"), Paper.LETTER)
    assert f'<script src="{MERMAID_URL}">' in with_diagrams
    assert '"Mermaid diagram " + n + " could not be drawn: "' in with_diagrams
    plain = tmp_path / "plain.md"
    plain.write_text("# Plain\n")
    assert "<script" not in build_page(load_document(plain), Paper.LETTER)
