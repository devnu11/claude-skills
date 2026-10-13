"""s15: the dashboard page renders Markdown through one safe function (M1-M11)."""

import re
from importlib import resources

import pytest
from agile_team import system


@pytest.fixture
def page() -> str:
    """The shipped dashboard page source."""
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_markdown_is_pinned_to_one_versioned_url(page: str) -> None:
    pin = r"https://cdn\.jsdelivr\.net/npm/markdown-it@14\.1\.0/dist/markdown-it\.min\.js"
    assert len(re.findall(pin, page)) == 1


def test_there_is_exactly_one_renderer_function(page: str) -> None:
    assert page.count("function md(") == 1
    assert page.count("markdownit(") == 1
    assert len(re.findall(r"\bmarkdown\.render\(", page)) == 1


def test_the_instance_is_configured_safely(page: str) -> None:
    assert "html: false" in page
    assert "linkify: false" in page
    assert "breaks: true" in page
    assert 'disable("image")' in page
    assert "SAFE_LINK" in page
    assert "validateLink" in page


def test_links_open_in_a_new_tab_without_opener(page: str) -> None:
    assert 'attrSet("target", "_blank")' in page
    assert 'attrSet("rel", "noopener noreferrer")' in page


def test_load_failure_is_a_warning_not_an_error(page: str) -> None:
    assert "function loadMarkdown(" in page
    assert "markdown unavailable, showing plain text:" in page
    assert "loadMarkdown();" in page


def test_questions_and_handoffs_use_md(page: str) -> None:
    assert page.count("${md(q.text)}") >= 3
    assert "${md(answers[q.id].text)}" in page
    kinds = '["step-end", "message", "answer", "thread", "opinion"]'
    assert f"MARKDOWN_KINDS = new Set({kinds})" in page
    assert "bodyHtml(e.kind, t.body)" in page


def test_markdown_styles_exist(page: str) -> None:
    assert ".md.plain { white-space: pre-line; }" in page
    assert ".q-answer" in page
