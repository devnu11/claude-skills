"""Send a PDF to a CUPS printer and follow the job until paper comes out, or doesn't."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

from . import system

PPD_DIR = Path("/etc/cups/ppd")
CUPS_DEFAULT_HOST = "localhost:631"
CUPS_PORT = 631
PRINTER_BACKENDS = frozenset({"ipp", "ipps"})  # backends that relay the printer's own count
POLL_SECONDS = 2.0
WAIT_SECONDS = 300.0
ENVIRONMENT_PRINTERS = ("LPDEST", "PRINTER")
TERMINAL_STATES = frozenset({"completed", "canceled", "aborted"})
JOB_QUERY = """{
OPERATION Get-Job-Attributes
GROUP operation-attributes-tag
ATTR charset attributes-charset utf-8
ATTR naturalLanguage attributes-natural-language en
ATTR uri printer-uri $uri
ATTR integer job-id $job
ATTR keyword requested-attributes job-state,job-state-reasons,job-impressions-completed
STATUS successful-ok
}
"""


class PrinterError(Exception):
    """No printer to send to, or sending failed."""


class Sides(StrEnum):
    """One- or two-sided printing, as ``--sides`` names it."""

    TWO = "two"
    ONE = "one"


class Send(StrEnum):
    """What goes to the printer: a local raster conversion, or the PDF itself."""

    RASTER = "raster"
    PDF = "pdf"


class Outcome(StrEnum):
    """How a followed job ended."""

    PRINTED = "printed"
    PRINTED_NOTHING = "printed nothing"
    COUNTED_BY_CUPS = "counted by CUPS"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"
    UNTRACKED = "untracked"


SIDES_OPTIONS = {
    Sides.TWO: ("sides=two-sided-long-edge", "Duplex=DuplexNoTumble"),
    Sides.ONE: ("sides=one-sided", "Duplex=None"),
}
RASTER_FORMATS = ("image/urf", "image/pwg-raster")
PDF_FORMAT = "application/pdf"


@dataclass(frozen=True)
class Job:
    """One print request."""

    printer: str
    title: str
    sides: Sides
    copies: int
    send: Send


@dataclass(frozen=True)
class Sent:
    """A job CUPS accepted: the queue and the id ``lp`` gave it."""

    printer: str
    job_id: str


@dataclass(frozen=True)
class Payload:
    """The file sent to the printer, and its format."""

    path: Path
    format: str


@dataclass(frozen=True)
class Status:
    """A job's state as CUPS reports it."""

    state: str
    reasons: str
    impressions: int | None


@dataclass(frozen=True)
class Clock:
    """Time, so tests can follow a job without waiting."""

    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic


def select_printer(requested: str | None) -> str:
    """``--printer``, else ``LPDEST`` or ``PRINTER``, else the CUPS default."""
    environment = system.get_environment()
    named = [requested, *(environment.get(name) for name in ENVIRONMENT_PRINTERS)]
    chosen = next((name for name in named if name), None) or read_default_printer()
    if not chosen:
        raise PrinterError(f"no printer given and no default; printers: {list_printers()}")
    return chosen


def read_default_printer() -> str | None:
    """The CUPS default destination, from ``lpstat -d``."""
    match = re.search(r"destination: (\S+)", system.capture(["lpstat", "-d"]) or "")
    return match[1] if match else None


def list_printers() -> str:
    """The printer names ``lpstat -p`` knows, comma separated, or ``none``."""
    names = re.findall(r"^printer (\S+)", system.capture(["lpstat", "-p"]) or "", re.M)
    return ", ".join(names) or "none"


def prepare_payload(pdf: Path, job: Job) -> Payload:
    """The PDF converted to the printer's raster format, or the PDF itself."""
    ppd = find_ppd(job.printer) if job.send is Send.RASTER else None
    raster = find_raster_format(ppd)
    if not ppd or not raster:
        return Payload(pdf, PDF_FORMAT)
    target = pdf.with_suffix(".raster")
    convert(Conversion(pdf, target, raster, job, ppd))
    return Payload(target, raster)


def find_ppd(printer: str) -> Path | None:
    """The queue's PPD: the local file when readable, else a copy CUPS serves to anyone."""
    local = PPD_DIR / f"{printer}.ppd"
    if local.is_file() and os.access(local, os.R_OK):
        return local
    copy = Path(tempfile.gettempdir()) / "render-markdown" / f"{printer}.ppd"
    return copy if get_served_ppd(printer, copy) else None


def get_served_ppd(printer: str, copy: Path) -> bool:
    """Download the queue's PPD from the CUPS web server into ``copy``; False when it can't."""
    url = f"http://{get_cups_host()}/printers/{quote(printer)}.ppd"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = response.read()
    except OSError:
        return False
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(data)
    return True


def get_cups_host() -> str:
    """``CUPS_SERVER`` as host:port, or the local server; a socket path means the local one."""
    server = system.get_environment().get("CUPS_SERVER", "")
    if not server or server.startswith("/"):
        return CUPS_DEFAULT_HOST
    return server if ":" in server else f"{server}:{CUPS_PORT}"


def find_raster_format(ppd: Path | None) -> str | None:
    """The first raster format the PPD has a filter for."""
    text = ppd.read_text(errors="replace") if ppd else ""
    filters = " ".join(re.findall(r"^\*cupsFilter2?:.*$", text, re.M))
    return next((kind for kind in RASTER_FORMATS if kind in filters), None)


@dataclass(frozen=True)
class Conversion:
    """A PDF to turn into ``format`` at ``target``, for ``job``."""

    pdf: Path
    target: Path
    format: str
    job: Job
    ppd: Path


def convert(conversion: Conversion) -> None:
    """Run ``cupsfilter`` with the queue's PPD to make the raster file."""
    options = [arg for option in SIDES_OPTIONS[conversion.job.sides] for arg in ("-o", option)]
    ppd = str(conversion.ppd)
    argv = ["cupsfilter", "-p", ppd, "-m", conversion.format, *options, str(conversion.pdf)]
    done = system.run_into(argv, conversion.target)
    if done.code != 0 or conversion.target.stat().st_size == 0:
        raise PrinterError(f"cupsfilter failed (exit {done.code}): {done.err.strip()[-400:]}")


def send_job(payload: Payload, job: Job) -> Sent:
    """Hand ``payload`` to ``lp``; the job as CUPS accepted it."""
    sides = SIDES_OPTIONS[job.sides][0]
    argv = ["lp", "-d", job.printer, "-t", job.title, "-n", str(job.copies), "-o", sides]
    argv += ["-o", f"document-format={payload.format}", str(payload.path)]
    done = system.run(argv)
    match = re.search(r"request id is (\S+)", done.out)
    if done.code != 0 or not match:
        raise PrinterError(f"lp failed (exit {done.code}): {(done.err or done.out).strip()}")
    return Sent(job.printer, match[1])


@dataclass(frozen=True)
class Traced:
    """How a job ended, and the last status CUPS gave for it."""

    outcome: Outcome
    status: Status | None


def trace_job(sent: Sent, clock: Clock) -> Traced:
    """Poll CUPS until the job ends or the wait runs out, and judge the result."""
    if not shutil.which("ipptool"):
        return Traced(Outcome.UNTRACKED, None)
    deadline = clock.now() + WAIT_SECONDS
    status = read_status(sent)
    while (status is None or status.state not in TERMINAL_STATES) and clock.now() < deadline:
        clock.sleep(POLL_SECONDS)
        status = read_status(sent)
    return Traced(limit_outcome(evaluate_status(status), sent.printer), status)


def limit_outcome(outcome: Outcome, printer: str) -> Outcome:
    """A page count CUPS made itself, for a non-IPP backend, doesn't prove paper came out."""
    if outcome is not Outcome.PRINTED or read_backend(printer) in PRINTER_BACKENDS:
        return outcome
    return Outcome.COUNTED_BY_CUPS


def read_backend(printer: str) -> str:
    """The queue's backend: ``ipp``, ``ipps``, ``usb``…; a dnssd URI names its service type."""
    out = system.capture(["lpstat", "-v", printer]) or ""
    uri = out.split(": ", 1)[-1].strip()
    service = re.search(r"\._(ipps?)\._tcp", uri)
    return service[1] if uri.startswith("dnssd:") and service else uri.split(":", 1)[0]


def evaluate_status(status: Status | None) -> Outcome:
    """Printed only when the job completed and the printer counted pages."""
    if status is None or status.state not in TERMINAL_STATES:
        return Outcome.UNCONFIRMED
    if status.state != "completed":
        return Outcome.FAILED
    if status.impressions is None:
        return Outcome.UNCONFIRMED
    return Outcome.PRINTED if status.impressions > 0 else Outcome.PRINTED_NOTHING


def read_status(sent: Sent) -> Status | None:
    """The job's state, reasons and impressions from the CUPS server, via ``ipptool``."""
    number = sent.job_id.rsplit("-", 1)[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".test", delete=False) as query:
        query.write(JOB_QUERY)
    uri = f"ipp://{get_cups_host()}/printers/{sent.printer}"
    out = system.capture(["ipptool", "-T", "10", "-tv", "-d", f"job={number}", uri, query.name])
    Path(query.name).unlink()
    return parse_status(out or "")


def parse_status(out: str) -> Status | None:
    """Read ``job-state``, its reasons and ``job-impressions-completed`` from ipptool."""
    state = re.search(r"job-state \(enum\) = (\S+)", out)
    if not state:
        return None
    reasons = re.search(r"job-state-reasons \([^)]*\) = (.+)", out)
    impressions = re.search(r"job-impressions-completed \(integer\) = (\d+)", out)
    count = int(impressions[1]) if impressions else None
    return Status(state[1], reasons[1].strip() if reasons else "", count)
