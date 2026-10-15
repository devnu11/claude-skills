"""render-markdown: show a Markdown file rendered, in the browser, as a PDF or on paper.

Exit codes: 0 done, 1 the PDF failed its check or the print wasn't confirmed,
2 a usage or setup error (no file, no Chrome, no printer, no browser).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .browser import BrowserError, open_in_browser
from .chrome import ChromeError
from .paper import Paper, select_paper
from .printer import (
    PDF_FORMAT,
    Clock,
    Job,
    Outcome,
    PrinterError,
    Send,
    Sent,
    Sides,
    Traced,
    prepare_payload,
    select_printer,
    send_job,
    trace_job,
)
from .render import PdfRequest, Rendering, render_pdf, write_page

USAGE_ERROR = 2
CHECK_FAILED = 1
SETUP_ERRORS = (BrowserError, ChromeError, PrinterError, FileNotFoundError)
type Arg = tuple[tuple[str, ...], dict[str, Any]]


class Mode(StrEnum):
    """Whether ``print`` sends the job or only reports what it would send."""

    SEND = "send"
    DRY_RUN = "dry run"


@dataclass(frozen=True)
class Command:
    """One subcommand: its name, help, handler and arguments."""

    name: str
    help: str
    handler: Callable[[argparse.Namespace], int]
    args: tuple[Arg, ...] = ()


def run_open(args: argparse.Namespace) -> int:
    """``open``: render to HTML and open it in the default browser."""
    document, page = write_page(require_file(args.file), select_paper(None, None))
    report_warnings(document.warnings)
    open_in_browser(page)
    print(f"opened: {page}")
    return 0


def run_pdf(args: argparse.Namespace) -> int:
    """``pdf``: render to a checked PDF."""
    paper = select_paper(args.paper, None)
    rendering = render_pdf(PdfRequest(require_file(args.file), paper, args.output))
    report_rendering(rendering, paper)
    return CHECK_FAILED if rendering.proof.problems else 0


def run_print(args: argparse.Namespace) -> int:
    """``print``: render, check, and send to a printer unless the check fails."""
    deny_windows_print()
    printer = select_printer(args.printer)
    rendering = render_for_printer(args, printer)
    if rendering.proof.problems:
        print("not sent: the PDF failed its check")
        return CHECK_FAILED
    job = Job(printer, rendering.document.title, args.sides, args.copies, args.send)
    return MODES[args.mode](rendering, job)


def report_dry_run(rendering: Rendering, job: Job) -> int:
    """Send nothing; the lines above already say what would have gone."""
    print("dry run: nothing sent")
    return 0


def render_for_printer(args: argparse.Namespace, printer: str) -> Rendering:
    """Render the file on the paper the request or the printer implies, and report it."""
    paper = select_paper(args.paper, printer)
    rendering = render_pdf(PdfRequest(require_file(args.file), paper))
    report_rendering(rendering, paper)
    print(f"printer: {printer}, sides: {args.sides}, copies: {args.copies}")
    return rendering


def deny_windows_print() -> None:
    """Windows has no ``lp``: point at ``pdf`` instead."""
    if sys.platform == "win32":
        raise PrinterError("print needs CUPS (macOS or Linux); on Windows use `pdf` and print it")


def send_and_trace(rendering: Rendering, job: Job) -> int:
    """Send the job, follow it to the end, and say whether paper came out."""
    payload = prepare_payload(rendering.pdf, job)
    if job.send is Send.RASTER and payload.format == PDF_FORMAT:
        print("warning: no raster filter or PPD for this printer; sending the PDF itself")
    sent = send_job(payload, job)
    print(f"sent: job {sent.job_id} as {payload.format}")
    traced = trace_job(sent, Clock())
    print(describe_outcome(sent, traced))
    return 0 if traced.outcome in DELIVERED else CHECK_FAILED


def describe_outcome(sent: Sent, traced: Traced) -> str:
    """One line on how the job ended."""
    status = traced.status
    state = f"{status.state} ({status.reasons})" if status else "unknown"
    lines = {
        Outcome.PRINTED: f"printed: {status and status.impressions} pages on {sent.printer}",
        Outcome.PRINTED_NOTHING: f"failed: job {sent.job_id} completed but printed 0 pages",
        Outcome.COUNTED_BY_CUPS: (
            f"completed: CUPS counted {status and status.impressions} pages for job "
            f"{sent.job_id}; this printer's backend can't confirm paper came out"
        ),
        Outcome.UNTRACKED: f"unconfirmed: job {sent.job_id} sent; no ipptool to follow it",
        Outcome.FAILED: f"failed: job {sent.job_id} ended {state}",
        Outcome.UNCONFIRMED: f"unconfirmed: job {sent.job_id} is {state}; check the printer",
    }
    return lines[traced.outcome]


def require_file(name: str) -> Path:
    """``name`` as a path to an existing file."""
    path = Path(name).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {name}")
    return path


def report_rendering(rendering: Rendering, paper: Paper) -> None:
    """The PDF, its preview, its pages and anything the check found."""
    report_warnings(rendering.document.warnings)
    print(f"pdf: {rendering.pdf} ({rendering.proof.pages} pages, {paper})")
    print(f"preview: {rendering.preview}")
    for problem in rendering.proof.problems:
        print(f"problem: {problem}")


def report_warnings(warnings: tuple[str, ...]) -> None:
    """Each rendering warning on its own line."""
    for warning in warnings:
        print(f"warning: {warning}")


DELIVERED = frozenset({Outcome.PRINTED, Outcome.COUNTED_BY_CUPS})
MODES: dict[Mode, Callable[[Rendering, Job], int]] = {
    Mode.SEND: send_and_trace,
    Mode.DRY_RUN: report_dry_run,
}
FILE_ARG: Arg = (("file",), {"help": "the Markdown file"})
PAPER_ARG: Arg = (("--paper",), {"type": Paper, "choices": list(Paper), "default": None})
COMMANDS = (
    Command("open", "render and open in the default browser", run_open, (FILE_ARG,)),
    Command(
        "pdf",
        "render to a checked PDF",
        run_pdf,
        (FILE_ARG, (("-o", "--output"), {"type": Path, "default": None}), PAPER_ARG),
    ),
    Command(
        "print",
        "render, check and print",
        run_print,
        (
            FILE_ARG,
            PAPER_ARG,
            (("--printer",), {"default": None}),
            (("--sides",), {"type": Sides, "choices": list(Sides), "default": Sides.TWO}),
            (("--copies",), {"type": int, "default": 1}),
            (("--send",), {"type": Send, "choices": list(Send), "default": Send.RASTER}),
            (
                ("--dry-run",),
                {"dest": "mode", "action": "store_const", "const": Mode.DRY_RUN},
            ),
        ),
    ),
)


def build_parser() -> argparse.ArgumentParser:
    """The parser for every command in ``COMMANDS``."""
    parser = argparse.ArgumentParser(prog="render-markdown", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        sub = commands.add_parser(command.name, help=command.help)
        sub.set_defaults(handler=command.handler, mode=Mode.SEND)
        for flags, options in command.args:
            sub.add_argument(*flags, **options)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command; a setup error prints ``error:`` and exits 2."""
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except SETUP_ERRORS as error:
        print(f"error: {error}", file=sys.stderr)
        return USAGE_ERROR
