"""Printing (AC4.1-AC4.3, AC4.5, AC4.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FakeSystem
from render_markdown import printer
from render_markdown.printer import (
    Clock,
    Job,
    Outcome,
    Payload,
    PrinterError,
    Send,
    Sent,
    Sides,
    Status,
    Traced,
    evaluate_status,
    parse_status,
    prepare_payload,
    select_printer,
    send_job,
    trace_job,
)
from render_markdown.system import Finished

JOB = Job("hp", "Story branches", Sides.TWO, 2, Send.RASTER)
SENT = Sent("hp", "hp-69")


def ipp(state: str, impressions: int | None = None) -> Finished:
    lines = [f"        job-state (enum) = {state}", "        job-state-reasons (keyword) = none"]
    if impressions is not None:
        lines.append(f"        job-impressions-completed (integer) = {impressions}")
    return Finished(0, "\n".join(lines), "")


class FakeClock:
    def __init__(self) -> None:
        self.time = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds

    def now(self) -> float:
        return self.time


def make_clock() -> tuple[Clock, FakeClock]:
    fake_clock = FakeClock()
    return Clock(fake_clock.sleep, fake_clock.now), fake_clock


def test_the_printer_flag_wins(fake: FakeSystem) -> None:
    fake.environment["LPDEST"] = "env"
    assert select_printer("flag") == "flag"


@pytest.mark.parametrize("name", ["LPDEST", "PRINTER"])
def test_the_environment_comes_next(fake: FakeSystem, name: str) -> None:
    fake.environment[name] = "env"
    fake.answer("lpstat", "system default destination: other\n")
    assert select_printer(None) == "env"


def test_then_the_cups_default(fake: FakeSystem) -> None:
    fake.answer("lpstat", "system default destination: hp\n")
    assert select_printer(None) == "hp"


def test_no_printer_lists_the_printers(fake: FakeSystem) -> None:
    fake.answers["lpstat"] = [
        Finished(0, "no system default destination\n", ""),
        Finished(0, "printer hp is idle.\nprinter office is idle.\n", ""),
    ]
    with pytest.raises(PrinterError, match="printers: hp, office"):
        select_printer(None)


def test_no_printers_at_all(fake: FakeSystem) -> None:
    fake.answer("lpstat", "", 1)
    with pytest.raises(PrinterError, match="printers: none"):
        select_printer(None)


def write_ppd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filters: str) -> None:
    monkeypatch.setattr(printer, "PPD_DIR", tmp_path)
    (tmp_path / "hp.ppd").write_text(f'*PPD-Adobe: "4.3"\n{filters}')


def test_raster_is_urf_when_the_ppd_has_it(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_ppd(tmp_path, monkeypatch, '*cupsFilter2: "image/urf image/urf 10 -"\n')
    payload = prepare_payload(tmp_path / "doc.pdf", JOB)
    assert payload == Payload(tmp_path / "doc.raster", "image/urf")
    assert payload.path.read_bytes() == b"raster"
    argv = fake.find_calls("cupsfilter")[0]
    assert argv[:5] == ["cupsfilter", "-p", str(tmp_path / "hp.ppd"), "-m", "image/urf"]
    assert "sides=two-sided-long-edge" in argv and "Duplex=DuplexNoTumble" in argv


def test_pwg_raster_when_the_ppd_lacks_urf(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_ppd(tmp_path, monkeypatch, '*cupsFilter: "image/pwg-raster 0 -"\n')
    assert prepare_payload(tmp_path / "doc.pdf", JOB).format == "image/pwg-raster"


def test_the_pdf_itself_without_a_raster_filter_or_when_asked(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    monkeypatch.setattr(printer, "PPD_DIR", tmp_path)
    assert prepare_payload(pdf, JOB) == Payload(pdf, "application/pdf")
    write_ppd(tmp_path, monkeypatch, '*cupsFilter2: "image/urf image/urf 10 -"\n')
    as_pdf = Job("hp", "t", Sides.TWO, 1, Send.PDF)
    assert prepare_payload(pdf, as_pdf) == Payload(pdf, "application/pdf")
    assert fake.find_calls("cupsfilter") == []


def test_a_failed_conversion_is_an_error(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_ppd(tmp_path, monkeypatch, '*cupsFilter2: "image/urf image/urf 10 -"\n')
    fake.answer("cupsfilter", "", 1)
    with pytest.raises(PrinterError, match="cupsfilter failed"):
        prepare_payload(tmp_path / "doc.pdf", JOB)


def test_send_job_runs_lp_with_the_options(fake: FakeSystem, tmp_path: Path) -> None:
    fake.answer("lp", "request id is hp-69 (1 file(s))\n")
    sent = send_job(Payload(tmp_path / "doc.raster", "image/urf"), JOB)
    assert sent == Sent("hp", "hp-69")
    assert fake.calls[0] == [
        "lp", "-d", "hp", "-t", "Story branches", "-n", "2", "-o", "sides=two-sided-long-edge",
        "-o", "document-format=image/urf", str(tmp_path / "doc.raster"),
    ]  # fmt: skip


def test_one_sided(fake: FakeSystem, tmp_path: Path) -> None:
    fake.answer("lp", "request id is hp-70 (1 file(s))\n")
    send_job(
        Payload(tmp_path / "doc.pdf", "application/pdf"), Job("hp", "t", Sides.ONE, 1, Send.RASTER)
    )
    assert "sides=one-sided" in fake.calls[0]


def test_a_refused_job_is_an_error(fake: FakeSystem, tmp_path: Path) -> None:
    fake.answer("lp", "", 1)
    with pytest.raises(PrinterError, match="lp failed"):
        send_job(Payload(tmp_path / "doc.pdf", "application/pdf"), JOB)


@pytest.fixture
def ipptool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")


def test_follow_polls_until_the_job_ends(fake: FakeSystem, ipptool: None) -> None:
    fake.answers["ipptool"] = [ipp("pending"), ipp("processing", 2), ipp("completed", 5)]
    fake.answer("lpstat", "device for hp: ipps://hp.local:631/ipp/print\n")
    clock, fake_clock = make_clock()
    traced = trace_job(SENT, clock)
    assert (traced.outcome, traced.status.impressions) == (Outcome.PRINTED, 5)
    assert fake_clock.sleeps == [2.0, 2.0]
    argv = fake.find_calls("ipptool")[0]
    assert argv[:6] == ["ipptool", "-T", "10", "-tv", "-d", "job=69"]
    assert argv[6] == "ipp://localhost:631/printers/hp"


def test_follow_gives_up_after_the_wait(fake: FakeSystem, ipptool: None) -> None:
    fake.answers["ipptool"] = [ipp("processing", 0)]
    clock, fake_clock = make_clock()
    assert trace_job(SENT, clock).outcome is Outcome.UNCONFIRMED
    assert fake_clock.time >= printer.WAIT_SECONDS


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (None, Outcome.UNCONFIRMED),
        (Status("processing", "", 1), Outcome.UNCONFIRMED),
        (Status("aborted", "job-aborted-by-system", 0), Outcome.FAILED),
        (Status("canceled", "", None), Outcome.FAILED),
        (Status("completed", "", None), Outcome.UNCONFIRMED),
        (Status("completed", "", 0), Outcome.PRINTED_NOTHING),
        (Status("completed", "", 3), Outcome.PRINTED),
    ],
)
def test_evaluate_status(status: Status | None, outcome: Outcome) -> None:
    assert evaluate_status(status) is outcome


def test_parse_status() -> None:
    assert parse_status(ipp("completed", 5).out) == Status("completed", "none", 5)
    assert parse_status("        job-state (enum) = pending") == Status("pending", "", None)
    assert parse_status("error") is None


def test_without_ipptool_the_job_is_untracked_at_once(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    clock, fake_clock = make_clock()
    assert trace_job(SENT, clock) == Traced(Outcome.UNTRACKED, None)
    assert fake_clock.sleeps == [] and fake.calls == []


@pytest.mark.parametrize(
    ("device", "outcome"),
    [
        ("ipp://hp.local/ipp/print", Outcome.PRINTED),
        ("dnssd://HP%20M453._ipps._tcp.local./?uuid=1", Outcome.PRINTED),
        ("dnssd://HP%20M453._pdl-datastream._tcp.local./", Outcome.COUNTED_BY_CUPS),
        ("usb://HP/LaserJet?serial=1", Outcome.COUNTED_BY_CUPS),
        ("socket://10.0.0.5", Outcome.COUNTED_BY_CUPS),
    ],
)
def test_only_an_ipp_backend_confirms_the_count(
    fake: FakeSystem, ipptool: None, device: str, outcome: Outcome
) -> None:
    fake.answers["ipptool"] = [ipp("completed", 4)]
    fake.answer("lpstat", f"device for hp: {device}\n")
    assert trace_job(SENT, make_clock()[0]).outcome is outcome


def test_the_cups_server_is_asked(fake: FakeSystem, ipptool: None) -> None:
    fake.environment["CUPS_SERVER"] = "print.example"
    fake.answers["ipptool"] = [ipp("completed", 0)]
    assert trace_job(SENT, make_clock()[0]).outcome is Outcome.PRINTED_NOTHING
    assert fake.find_calls("ipptool")[0][6] == "ipp://print.example:631/printers/hp"


@pytest.mark.parametrize(
    ("server", "host"),
    [("", "localhost:631"), ("/run/cups/cups.sock", "localhost:631"), ("a:8631", "a:8631")],
)
def test_get_cups_host(fake: FakeSystem, server: str, host: str) -> None:
    fake.environment["CUPS_SERVER"] = server
    assert printer.get_cups_host() == host


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.data


def test_an_unreadable_ppd_is_fetched_from_cups(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output_dir: Path
) -> None:
    write_ppd(tmp_path, monkeypatch, "")
    monkeypatch.setattr("os.access", lambda path, mode: False)
    urls: list[str] = []

    def answer(url: str, timeout: float) -> FakeResponse:
        urls.append(url)
        return FakeResponse(b'*cupsFilter2: "image/urf image/urf 10 -"\n')

    monkeypatch.setattr("urllib.request.urlopen", answer)
    payload = prepare_payload(tmp_path / "doc.pdf", JOB)
    assert payload.format == "image/urf" and urls == ["http://localhost:631/printers/hp.ppd"]
    assert fake.find_calls("cupsfilter")[0][2] == str(output_dir / "hp.ppd")


def test_no_ppd_at_all_sends_the_pdf(
    fake: FakeSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(printer, "PPD_DIR", tmp_path)
    pdf = tmp_path / "doc.pdf"
    assert prepare_payload(pdf, JOB) == Payload(pdf, "application/pdf")
