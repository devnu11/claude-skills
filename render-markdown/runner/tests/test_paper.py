"""Choosing the paper (AC3.2)."""

from __future__ import annotations

import pytest

from conftest import FakeSystem
from render_markdown.paper import Paper, find_region, select_paper

PRINTER_OPTIONS = "Duplex/2-Sided: None *DuplexNoTumble\nPageSize/Media Size: Legal *A4 Letter\n"


def test_an_asked_for_paper_wins(fake: FakeSystem) -> None:
    fake.answer("lpoptions", PRINTER_OPTIONS)
    assert select_paper(Paper.LETTER, "hp") is Paper.LETTER
    assert fake.calls == []


def test_the_printer_default_comes_next(fake: FakeSystem) -> None:
    fake.answer("lpoptions", PRINTER_OPTIONS)
    assert select_paper(None, "hp") is Paper.A4
    assert fake.calls[0] == ["lpoptions", "-p", "hp", "-l"]


def test_an_unknown_printer_size_falls_to_the_locale(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    fake.answer("lpoptions", "PageSize/Media Size: *Legal A4\n")
    fake.answer("defaults", "en_GB\n")
    assert select_paper(None, "hp") is Paper.A4


@pytest.mark.parametrize(
    ("locale", "paper"),
    [
        ("en_US", Paper.LETTER),
        ("fr_CA", Paper.LETTER),
        ("en_GB", Paper.A4),
        ("zh-Hans_CN", Paper.A4),
        ("en_US@rg=dezzzz", Paper.A4),
        ("en", Paper.A4),
        ("en_150", Paper.A4),
    ],
)
def test_the_mac_region_picks_the_paper(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch, locale: str, paper: Paper
) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    fake.answer("defaults", locale + "\n")
    assert select_paper(None, None) is paper


@pytest.mark.parametrize(("height", "paper"), [("279", Paper.LETTER), ("297", Paper.A4)])
def test_the_linux_locale_height_picks_the_paper(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch, height: str, paper: Paper
) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    fake.answer("locale", f"height={height}\nwidth=216\n")
    assert select_paper(None, None) is paper


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_letter_when_nothing_says(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr("sys.platform", platform)
    fake.answer("defaults", "", 1)
    fake.answer("locale", "", 1)
    assert select_paper(None, None) is Paper.LETTER


def test_a_region_override_beats_the_language_region() -> None:
    assert find_region("en_US@rg=gbzzzz") == "GB"
    assert find_region("garbage") is None
