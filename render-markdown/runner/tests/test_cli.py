"""The commands (AC2.1, AC3.3, AC4.1-AC4.6, AC6.4)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FIXTURES, FakeSystem
from render_markdown import cli, printer
from render_markdown.document import load_document
from render_markdown.printer import Outcome, Sent, Status, Traced
from render_markdown.proof import Proof
from render_markdown.render import Rendering

SAMPLE = FIXTURES / "sample.md"


def make_rendering(tmp_path: Path, problems: tuple[str, ...] = ()) -> Rendering:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF")
    document = load_document(SAMPLE)
    return Rendering(document, pdf, tmp_path / "sample.page1.png", Proof(3, problems))


@pytest.fixture
def rendered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list:
    requests: list = []

    def render(request):
        requests.append(request)
        return make_rendering(tmp_path)

    monkeypatch.setattr(cli, "render_pdf", render)
    return requests


def test_open_writes_the_page_and_opens_it(
    fake: FakeSystem,
    output_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    fake.answer("defaults", "en_US")
    assert cli.main(["open", str(SAMPLE)]) == 0
    page = output_dir / "sample.html"
    assert fake.find_calls("open") == [["open", str(page)]]
    assert capsys.readouterr().out.splitlines() == [
        "warning: missing image: no-such.png",
        f"opened: {page}",
    ]


def test_a_missing_file_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["open", "no-such.md"]) == 2
    assert "error: no such file: no-such.md" in capsys.readouterr().err


def test_pdf_reports_the_files_and_pages(
    rendered: list, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["pdf", str(SAMPLE), "-o", str(tmp_path / "x.pdf"), "--paper", "a4"]) == 0
    assert rendered[0].pdf == tmp_path / "x.pdf" and rendered[0].paper == "a4"
    out = capsys.readouterr().out
    assert f"pdf: {tmp_path / 'sample.pdf'} (3 pages, a4)" in out
    assert f"preview: {tmp_path / 'sample.page1.png'}" in out


def test_pdf_with_problems_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "render_pdf", lambda request: make_rendering(tmp_path, ("bad",)))
    assert cli.main(["pdf", str(SAMPLE), "--paper", "letter"]) == 1
    assert "problem: bad" in capsys.readouterr().out


def test_print_refuses_on_windows(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    assert cli.main(["print", str(SAMPLE)]) == 2
    assert "on Windows use `pdf`" in capsys.readouterr().err


def test_print_dry_run_sends_nothing(
    fake: FakeSystem, rendered: list, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.answer("lpoptions", "PageSize/Media Size: *A4 Letter\n")
    assert cli.main(["print", str(SAMPLE), "--printer", "hp", "--dry-run"]) == 0
    assert rendered[0].paper == "a4"
    out = capsys.readouterr().out
    assert "printer: hp, sides: two, copies: 1" in out and "dry run: nothing sent" in out
    assert fake.find_calls("lp") == []


def test_print_never_sends_a_pdf_that_failed_its_check(
    fake: FakeSystem,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "render_pdf", lambda request: make_rendering(tmp_path, ("bad",)))
    assert cli.main(["print", str(SAMPLE), "--printer", "hp", "--paper", "letter"]) == 1
    assert "not sent: the PDF failed its check" in capsys.readouterr().out
    assert fake.find_calls("lp") == [] and fake.find_calls("cupsfilter") == []


def test_print_sends_follows_and_reports_pages(
    fake: FakeSystem,
    rendered: list,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(printer, "PPD_DIR", Path("/nowhere"))
    monkeypatch.setattr(
        cli,
        "trace_job",
        lambda sent, clock: Traced(Outcome.PRINTED, Status("completed", "none", 3)),
    )
    fake.answer("lp", "request id is hp-71 (1 file(s))\n")
    code = cli.main(
        ["print", str(SAMPLE), "--printer", "hp", "--paper", "letter", "--sides", "one"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "sent: job hp-71 as application/pdf" in out and "printed: 3 pages on hp" in out
    assert "warning: no raster filter or PPD for this printer; sending the PDF itself" in out
    assert "sides=one-sided" in fake.find_calls("lp")[0]


@pytest.mark.parametrize(
    ("outcome", "status", "line"),
    [
        (Outcome.PRINTED_NOTHING, Status("completed", "none", 0), "completed but printed 0 pages"),
        (Outcome.FAILED, Status("aborted", "job-aborted", 0), "ended aborted (job-aborted)"),
        (Outcome.UNCONFIRMED, None, "is unknown; check the printer"),
        (Outcome.UNTRACKED, None, "sent; no ipptool to follow it"),
        (
            Outcome.COUNTED_BY_CUPS,
            Status("completed", "none", 2),
            "CUPS counted 2 pages for job hp-9; this printer's backend can't confirm",
        ),
    ],
)
def test_describe_outcome(outcome: Outcome, status: Status | None, line: str) -> None:
    assert line in cli.describe_outcome(Sent("hp", "hp-9"), Traced(outcome, status))


def test_a_print_that_printed_nothing_exits_1(
    fake: FakeSystem, rendered: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(printer, "PPD_DIR", Path("/nowhere"))
    nothing = Traced(Outcome.PRINTED_NOTHING, Status("completed", "none", 0))
    monkeypatch.setattr(cli, "trace_job", lambda sent, clock: nothing)
    fake.answer("lp", "request id is hp-72 (1 file(s))\n")
    assert cli.main(["print", str(SAMPLE), "--printer", "hp", "--paper", "a4"]) == 1


def test_runs_as_a_module() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "render_markdown", "--help"], capture_output=True, text=True
    )
    assert done.returncode == 0 and "open" in done.stdout and "print" in done.stdout


def test_a_count_only_cups_made_still_exits_0(
    fake: FakeSystem, rendered: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(printer, "PPD_DIR", Path("/nowhere"))
    counted = Traced(Outcome.COUNTED_BY_CUPS, Status("completed", "none", 2))
    monkeypatch.setattr(cli, "trace_job", lambda sent, clock: counted)
    fake.answer("lp", "request id is hp-73 (1 file(s))\n")
    assert cli.main(["print", str(SAMPLE), "--printer", "hp", "--paper", "a4"]) == 0


def test_a_raster_send_has_no_warning(
    fake: FakeSystem,
    rendered: list,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raster = printer.Payload(Path("/tmp/sample.raster"), "image/urf")
    monkeypatch.setattr(cli, "prepare_payload", lambda pdf, job: raster)
    printed = Traced(Outcome.PRINTED, Status("completed", "none", 3))
    monkeypatch.setattr(cli, "trace_job", lambda sent, clock: printed)
    fake.answer("lp", "request id is hp-74 (1 file(s))\n")
    assert cli.main(["print", str(SAMPLE), "--printer", "hp", "--paper", "a4"]) == 0
    out = capsys.readouterr().out
    assert "sent: job hp-74 as image/urf" in out and "no raster filter" not in out
