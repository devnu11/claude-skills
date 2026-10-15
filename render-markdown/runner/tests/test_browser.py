"""Opening the browser (AC2.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FakeSystem
from render_markdown.browser import BrowserError, open_in_browser


@pytest.mark.parametrize(
    ("platform", "opener"),
    [("darwin", ["open"]), ("linux", ["xdg-open"]), ("win32", ["cmd", "/c", "start", ""])],
)
def test_each_platform_has_its_opener(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch, platform: str, opener: list[str]
) -> None:
    monkeypatch.setattr("sys.platform", platform)
    open_in_browser(Path("/tmp/x.html"))
    assert fake.calls == [[*opener, "/tmp/x.html"]]


def test_an_unknown_platform_says_to_open_it_by_hand(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "plan9")
    with pytest.raises(BrowserError, match=r"open /tmp/x\.html by hand"):
        open_in_browser(Path("/tmp/x.html"))


def test_a_failing_opener_is_an_error(fake: FakeSystem, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    fake.answer("xdg-open", "", 4)
    with pytest.raises(BrowserError, match="xdg-open failed"):
        open_in_browser(Path("/tmp/x.html"))
