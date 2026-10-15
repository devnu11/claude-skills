"""Finding Chrome and printing with it (AC1.5, AC3.1, AC3.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FakeSystem
from render_markdown import chrome, system
from render_markdown.chrome import ChromeError, find_chrome, write_pdf
from render_markdown.system import Finished


def make_browser(folder: Path, name: str = "chrome") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    browser = folder / name
    browser.write_text("")
    return browser


def test_the_override_comes_first(fake: FakeSystem, tmp_path: Path) -> None:
    browser = make_browser(tmp_path)
    fake.environment[chrome.OVERRIDE] = str(browser)
    fake.answer("chrome", "Google Chrome 155.0.8059.40\n")
    assert find_chrome() == browser


def test_a_command_name_is_found_on_path(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = make_browser(tmp_path, "chromium")
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: str(browser) if name == "chromium" else None)
    fake.answer("chromium", "Chromium 120.0.1.2\n")
    assert find_chrome() == browser


def test_windows_paths_expand_and_the_version_comes_from_the_folder(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = make_browser(tmp_path / "Google" / "Chrome" / "Application", "chrome.exe")
    (browser.parent / "141.0.7390.55").mkdir()
    (browser.parent / "SetupMetrics").mkdir()
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    candidate = "%ProgramFiles%/Google/Chrome/Application/chrome.exe"
    monkeypatch.setattr(chrome, "CANDIDATES", {"win32": (candidate,)})
    assert find_chrome() == browser
    assert fake.calls == []  # Windows Chrome has no --version: running it opens a window


def test_an_old_chrome_is_refused(fake: FakeSystem, tmp_path: Path) -> None:
    fake.environment[chrome.OVERRIDE] = str(make_browser(tmp_path))
    fake.answer("chrome", "Google Chrome 109.0.1.2\n")
    with pytest.raises(ChromeError, match="Chrome 109; 112 or later"):
        find_chrome()


def test_an_unreadable_version_is_accepted(fake: FakeSystem, tmp_path: Path) -> None:
    browser = make_browser(tmp_path)
    fake.environment[chrome.OVERRIDE] = str(browser)
    fake.answer("chrome", "", 1)
    assert find_chrome() == browser


def test_no_chrome_names_what_it_looked_for(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ChromeError, match="looked for: google-chrome, google-chrome-stable"):
        find_chrome()


def test_print_to_pdf_runs_in_a_scratch_home_it_removes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, pdf = tmp_path / "page.html", tmp_path / "out.pdf"
    homes: list[Path] = []

    def answer(argv: list[str], env: dict[str, str]) -> Finished:
        homes.append(Path(env["HOME"]))
        assert homes[0].is_dir() and env["HOME"] != str(Path.home())
        pdf.write_bytes(b"%PDF")
        return Finished(0, "", "")

    monkeypatch.setattr(system, "run", answer)
    monkeypatch.setattr(chrome, "find_chrome", lambda: Path("/bin/chrome"))
    write_pdf(page, pdf)
    assert not homes[0].exists()


def test_print_to_pdf_flags(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, pdf = tmp_path / "page.html", tmp_path / "out.pdf"
    monkeypatch.setattr(chrome, "find_chrome", lambda: Path("/bin/chrome"))
    fake.answer("chrome", "", 0)
    with pytest.raises(ChromeError, match="Chrome made no PDF"):
        write_pdf(page, pdf)
    argv = fake.calls[0]
    for flag in (*chrome.FLAGS, f"--print-to-pdf={pdf}", page.as_uri()):
        assert flag in argv
    assert "--virtual-time-budget=15000" in argv
    assert any(arg.startswith("--user-data-dir=") for arg in argv)
    assert fake.environments[0]["HOME"] in next(a for a in argv if a.startswith("--user-data"))


def test_version_runs_in_a_scratch_home(fake: FakeSystem, tmp_path: Path) -> None:
    fake.environment[chrome.OVERRIDE] = str(make_browser(tmp_path))
    fake.answer("chrome", "Chromium 130.0.1.2\n")
    find_chrome()
    home = fake.environments[0]["HOME"]
    assert fake.calls[0][1] == "--version" and home != str(Path.home())
    assert not Path(home).exists()
