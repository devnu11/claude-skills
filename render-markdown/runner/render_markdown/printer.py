"""Send a PDF to a CUPS printer and follow the job until paper comes out, or doesn't."""

from __future__ import annotations

import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from . import system

PPD_DIR = Path("/etc/cups/ppd")
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
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"


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
    raster = find_raster_format(job.printer) if job.send is Send.RASTER else None
    if not raster:
        return Payload(pdf, PDF_FORMAT)
    target = pdf.with_suffix(".raster")
    convert(Conversion(pdf, target, raster, job))
    return Payload(target, raster)


def find_raster_format(printer: str) -> str | None:
    """The first raster format the queue's PPD has a filter for."""
    ppd = PPD_DIR / f"{printer}.ppd"
    text = ppd.read_text(errors="replace") if ppd.is_file() else ""
    filters = " ".join(re.findall(r"^\*cupsFilter2?:.*$", text, re.M))
    return next((kind for kind in RASTER_FORMATS if kind in filters), None)


@dataclass(frozen=True)
class Conversion:
    """A PDF to turn into ``format`` at ``target``, for ``job``."""

    pdf: Path
    target: Path
    format: str
    job: Job


def convert(conversion: Conversion) -> None:
    """Run ``cupsfilter`` with the queue's PPD to make the raster file."""
    options = [arg for option in SIDES_OPTIONS[conversion.job.sides] for arg in ("-o", option)]
    ppd = str(PPD_DIR / f"{conversion.job.printer}.ppd")
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
    """Poll CUPS until the job ends or the wait runs out, and evaluate_status the result."""
    deadline = clock.now() + WAIT_SECONDS
    status = read_status(sent)
    while (status is None or status.state not in TERMINAL_STATES) and clock.now() < deadline:
        clock.sleep(POLL_SECONDS)
        status = read_status(sent)
    return Traced(evaluate_status(status), status)


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
    """The job's state, reasons and impressions from the local CUPS server, via ``ipptool``."""
    number = sent.job_id.rsplit("-", 1)[-1]
    with tempfile.NamedTemporaryFile("w", suffix=".test", delete=False) as query:
        query.write(JOB_QUERY)
    uri = f"ipp://localhost/printers/{sent.printer}"
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
