"""The runner pins itself at a sprint end, or rolls back (s128, ADR-0065).

Everything this module needs is imported at the top: once ``pin-runner.sh`` has
swapped the pin directories, a lazy import in the old process would load new code.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn

from . import config, system
from .events import Event, EventKind
from .relay import Note

if TYPE_CHECKING:
    from .dispatch import Runtime

PIN_DIR = "runner-pin"
COMMIT_FILE = "runner-pin.commit"
MARKER_FILE = "repin.json"
PIN_SCRIPT = "agile-team/runner/scripts/pin-runner.sh"
PIN_EXE = ".venv/bin/agile-team"
PACKAGE_DIR = Path(__file__).parent
PIN_TIMEOUT_S = 300.0
CHECK_TIMEOUT_S = 600.0
TAIL_CHARS = 300
REPINNING = "re-pinning the runner at {new7}"
ROLLED_BACK_NOTE = (
    "The runner tried to re-pin itself from {old7} to {new7} at the end of sprint {sprint} "
    "and rolled back to {old7}: {reason}. The team carries on on {old7}; the failed pin is in "
    ".team/run/runner-pin.failed."
)


class Outcome(StrEnum):
    """Where a re-pin stands: on trial, confirmed, or rolled back."""

    TRIAL = "trial"
    PINNED = "pinned"
    ROLLED_BACK = "rolled_back"


class RepinError(RuntimeError):
    """A rollback that failed; the run crashes and the marker stays."""


class _StepFailed(Exception):
    """A re-pin step failed; the pin rolls back."""


@dataclass(frozen=True)
class Marker:
    """``.team/run/repin.json``: one re-pin, from ``old`` to ``new`` at ``sprint``."""

    old: str
    new: str
    sprint: int
    outcome: Outcome
    reason: str = ""

    def data(self) -> dict[str, Any]:
        """The marker's JSON and the ``runner-repin`` event's data."""
        return {
            "old": self.old,
            "new": self.new,
            "sprint": self.sprint,
            "outcome": str(self.outcome),
            "reason": self.reason,
        }


def pinned(run_dir: Path) -> bool:
    """P1: this runner's code lives inside the repo's pin directory."""
    here, pin = system.resolve(PACKAGE_DIR), system.resolve(run_dir / PIN_DIR)
    return here.is_relative_to(pin)


def pin_commit(run_dir: Path) -> str:
    """The pinned commit, or ``""`` when the pin has no commit file."""
    path = run_dir / COMMIT_FILE
    return system.read_text(path).strip() if system.is_file(path) else ""


def due(run_dir: Path, head: str) -> bool:
    """P2: a pinned runner whose pin is not ``head``."""
    return pinned(run_dir) and head != pin_commit(run_dir)


def read_marker(run_dir: Path) -> Marker | None:
    """The marker, or ``None`` when it is missing or does not parse."""
    path = run_dir / MARKER_FILE
    if not system.is_file(path):
        return None
    try:
        raw = json.loads(system.read_text(path))
        return Marker(
            raw["old"], raw["new"], raw["sprint"], Outcome(raw["outcome"]), raw.get("reason", "")
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def write_marker(run_dir: Path, marker: Marker) -> None:
    """Save the marker."""
    system.make_dirs(run_dir)
    system.write_text(run_dir / MARKER_FILE, json.dumps(marker.data()))


START_COMMAND: tuple[str, ...] = ("start", "--resume")
CHECK_COMMAND: tuple[str, ...] = ("config", "check")


def build_global_argv(repo: Path, home: str | None) -> tuple[str, ...]:
    """The CLI's global options for this run; they go before the subcommand."""
    base = ("--repo", str(repo))
    return (*base, "--home", home) if home else base


def start_argv(options: tuple[str, ...]) -> tuple[str, ...]:
    """P5: the arguments the next process starts with; the cadence is kept by the state."""
    return (*options, *START_COMMAND)


def drop_unpinned(runtime: Runtime) -> None:
    """P3: an unpinned runner has nothing to re-pin to; forget a leftover request."""
    if runtime.state.repin and not pinned(runtime.config.run_dir):
        runtime.state.repin = ""
        runtime.save()


def confirm(runtime: Runtime) -> None:
    """P10: log the re-pin that led to this process; tell the human of a rollback."""
    run_dir = runtime.config.run_dir
    marker = read_marker(run_dir)
    if marker is None:
        return
    rolled = marker.outcome is Outcome.ROLLED_BACK
    outcome = marker.outcome if rolled else Outcome.PINNED
    data = {**marker.data(), "outcome": str(outcome)}
    runtime.events.emit(Event(EventKind.RUNNER_REPIN, "runner", None, data))
    if rolled:
        runtime.relay.post(Note("update", _rolled_back_text(marker), []))
    system.remove(run_dir / MARKER_FILE)


def _rolled_back_text(marker: Marker) -> str:
    return ROLLED_BACK_NOTE.format(
        old7=marker.old[:7], new7=marker.new[:7], sprint=marker.sprint, reason=marker.reason
    )


def failed_start(pin: Pin, exc: Exception) -> None:
    """P9: a first start on a trial pin that failed rolls back; otherwise nothing."""
    marker = read_marker(pin.run_dir)
    if marker is not None and marker.outcome is Outcome.TRIAL:
        pin.roll_back(marker, f"first start failed: {type(exc).__name__}: {exc}")


class Trial(NamedTuple):
    """One step of a re-pin: its name, how to build its argv, its timeout."""

    name: str
    argv: Callable[[Pin, Marker], tuple[str, ...]]
    timeout: float


def _pin_argv(pin: Pin, marker: Marker) -> tuple[str, ...]:
    return ("sh", str(pin.repo / PIN_SCRIPT), marker.new)


def _check_argv(pin: Pin, _marker: Marker) -> tuple[str, ...]:
    uv = system.which("uv")
    if uv is None:
        raise _StepFailed("uv is not on PATH")
    project = str(pin.run_dir / PIN_DIR)
    return (uv, "run", "--frozen", "--quiet", "--project", project, "agile-team",
            *pin.options, *CHECK_COMMAND)  # fmt: skip


TRIALS: tuple[Trial, ...] = (
    Trial("pin-runner.sh", _pin_argv, PIN_TIMEOUT_S),
    Trial("config check", _check_argv, CHECK_TIMEOUT_S),
)
FAILURES = (_StepFailed, system.TimeoutExpired, OSError)


def _tail(done: system.Completed) -> str:
    return (done.err or done.out).strip()[-TAIL_CHARS:]


def _run_checked(name: str, argv: tuple[str, ...], timeout: float) -> None:
    done = system.run(system.Command(argv, timeout=timeout))
    if done.code != 0:
        raise _StepFailed(f"{name} exited {done.code}: {_tail(done)}")


def _reason(exc: BaseException) -> str:
    text = str(exc)
    return text if isinstance(exc, _StepFailed) else f"{type(exc).__name__}: {text}"


@dataclass(frozen=True)
class Pin:
    """The repo's pinned runner: pin it, check it, exec it, or roll it back."""

    repo: Path
    options: tuple[str, ...]

    @property
    def run_dir(self) -> Path:
        """The repo's run directory."""
        return self.repo / config.RUN_DIR

    def repin(self, marker: Marker) -> NoReturn:
        """P4: pin ``marker.new``, check it, exec it; any failure rolls back."""
        try:
            for trial in TRIALS:
                _run_checked(trial.name, trial.argv(self, marker), trial.timeout)
            write_marker(self.run_dir, marker)
            self.exec()
        except FAILURES as exc:
            self.roll_back(marker, _reason(exc))

    def roll_back(self, marker: Marker, reason: str) -> NoReturn:
        """P8: restore the old pin if it was swapped, record why, exec the restored pin."""
        if self.pin_commit() == marker.new != marker.old:
            self._restore(reason)
        rolled = Marker(marker.old, marker.new, marker.sprint, Outcome.ROLLED_BACK, reason)
        write_marker(self.run_dir, rolled)
        self.exec()

    def pin_commit(self) -> str:
        """The commit file's sha."""
        return pin_commit(self.run_dir)

    def _restore(self, reason: str) -> None:
        argv = ("sh", str(self.repo / PIN_SCRIPT), "--rollback")
        try:
            _run_checked("rollback", argv, PIN_TIMEOUT_S)
        except FAILURES as exc:
            raise RepinError(f"{reason}; rollback failed: {_reason(exc)}") from exc

    def exec(self) -> NoReturn:
        """P5: replace this process with the pin's ``start --resume``."""
        system.exec_replace((str(self.run_dir / PIN_DIR / PIN_EXE), *start_argv(self.options)))
