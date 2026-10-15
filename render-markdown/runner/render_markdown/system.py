"""The one door to other programs, so tests can stand in for all of them."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finished:
    """A finished program: its exit code and what it printed."""

    code: int
    out: str
    err: str


MISSING = Finished(127, "", "not found")


def run(argv: Sequence[str], env: Mapping[str, str] | None = None) -> Finished:
    """Run ``argv`` to the end; a program that isn't installed exits 127."""
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, env=env, check=False)
    except FileNotFoundError:
        return MISSING
    return Finished(done.returncode, done.stdout, done.stderr)


def run_into(argv: Sequence[str], target: Path) -> Finished:
    """Run ``argv`` with its standard output written, as bytes, to ``target``."""
    try:
        with target.open("wb") as out:
            done = subprocess.run(list(argv), stdout=out, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError:
        return MISSING
    return Finished(done.returncode, "", done.stderr.decode(errors="replace"))


def capture(argv: Sequence[str]) -> str | None:
    """What ``argv`` prints, or None when it fails or isn't installed."""
    done = run(argv)
    return done.out if done.code == 0 else None


def get_environment() -> dict[str, str]:
    """A copy of this process's environment."""
    return dict(os.environ)
