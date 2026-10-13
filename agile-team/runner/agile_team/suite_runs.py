"""Run the test command N times in a row after a story's suite step (s107 SR1-SR7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import system
from .results import result_tail
from .roles import RoleError, split_frontmatter

KEY = "suite_runs"
MOST_SUITE_RUNS = 10
SUITE_RUNS = "suite-runs"
SUITE_STEPS = ("e2e", "implement")
SUITE_PASSED = "the test command passed {total} runs in a row ({times})"
SUITE_FAILED = "the test command failed on run {n} of {total}:\n{tail}"
RUN_LINE = "run {n} of {total}: exit {code} in {seconds:.0f} s: {summary}"
BAD_SUITE_RUNS = (
    "story {story}'s suite_runs must be a whole number from 1 to {most}, not {value!r}; "
    "fix the story file's frontmatter"
)
BAD_FRONTMATTER = "story {story}'s frontmatter does not parse: {error}"
SUMMARY = re.compile(r"\b\d+ (passed|failed|errors?)\b")


@dataclass(frozen=True)
class Wanted:
    """How many suite runs a story asks for; ``refusal`` set when the value is bad."""

    count: int = 0
    refusal: str | None = None


def _in_range(value: Any) -> bool:
    return type(value) is int and 1 <= value <= MOST_SUITE_RUNS


def wanted(meta: dict[str, Any] | None, story: str) -> Wanted:
    """No key: no runs; a whole number from 1 to the most: that many; else a refusal."""
    if not meta or KEY not in meta:
        return Wanted()
    value = meta[KEY]
    if _in_range(value):
        return Wanted(value)
    return Wanted(0, BAD_SUITE_RUNS.format(story=story, most=MOST_SUITE_RUNS, value=value))


def declared(stories_dir: Path, story: str) -> Wanted:
    """The suite runs the story's file asks for; a missing file asks for none."""
    try:
        text = system.read_text(stories_dir / f"{story}.md")
    except OSError:
        return Wanted()
    try:
        meta, _ = split_frontmatter(story, text)
    except (RoleError, yaml.YAMLError) as error:
        return Wanted(0, BAD_FRONTMATTER.format(story=story, error=error))
    return wanted(meta, story)


def suite_step(steps: list[str]) -> str | None:
    """The first suite step in the pipeline, or ``None``."""
    return next((s for s in SUITE_STEPS if s in steps), None)


def summary(out: str) -> str:
    """The summary lines of a run, else its last non-blank line."""
    hits = [ln.strip("= ") for ln in out.splitlines() if SUMMARY.search(ln)]
    if hits:
        return " | ".join(hits)
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else "no output"


@dataclass(frozen=True)
class SuiteRun:
    """One run of the test command."""

    n: int
    total: int
    code: int
    seconds: float
    out: str = field(repr=False)

    def line(self) -> str:
        """The run's one-line report."""
        return RUN_LINE.format(
            n=self.n,
            total=self.total,
            code=self.code,
            seconds=self.seconds,
            summary=summary(self.out),
        )


def report(runs: list[SuiteRun]) -> str:
    """A line per run, then the failed last run's tail."""
    text = "\n".join(run.line() for run in runs)
    last = runs[-1]
    return text if last.code == 0 else f"{text}\n\n{result_tail(last.out)}"


def passed_text(runs: list[SuiteRun]) -> str:
    """The reason text for a streak of passing runs."""
    times = ", ".join(f"{run.seconds:.0f} s" for run in runs)
    return SUITE_PASSED.format(total=len(runs), times=times)
