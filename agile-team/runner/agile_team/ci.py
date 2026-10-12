"""CI results of the sprint's pull requests: the data, the verdict rules, the texts, and the wait.

``CiWatch`` waits for the checks of the watched PRs. ``gh`` is reached only through a ``Prs``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from . import system

if TYPE_CHECKING:
    from .boundary import StackEntry
    from .upstream import Prs

CI_POLL_S = 10.0
CI_LOOKS = 12
MAX_LINES = 20
TAIL_LINES = 10
READY_PHRASE = "ready to merge"
NO_CHECKS = "no checks reported"
JOB_LINK = re.compile(r"/actions/runs/\d+/job/(\d+)")
LOG_PREFIX = re.compile(r"^(?:[^\t]*\t){2}(?:\d{4}-\d\d-\d\dT[\d:.]+Z ?)?")
FAILING_LINE: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bFAILED\s+\S"),
    re.compile(r"\bERROR\s+\S+::"),
    re.compile(r"--- FAIL: "),
    re.compile(r"\b[1-9]\d* (?:failed|errors?)\b"),
)
CI_GREEN_REPORT = 'Sprint {sprint}\'s CI passed on {prs}: ready to merge with "Rebase and merge".'
CI_RED_REPORT = (
    "Sprint {sprint}: checks failed on {prs}, story {story} opened. "
    "The PR is NOT ready; do not merge it."
)
CI_NONE_REPORT = (
    "Sprint {sprint}'s review branches are pushed: {prs}. No CI result exists ({why}), "
    "so the PR is NOT called ready."
)
CI_TIMEOUT = "CI checks still running after {limit:.0f}s"
NO_CHECKS_WHY = "no CI checks reported"
NO_OPEN_PR_WHY = "no open, non-draft pull request to watch"
CHECK_LINE = "- {label}: {bucket} {link}"


class UpstreamError(Exception):
    """The remote or the PR service refused or failed."""


class Bucket(StrEnum):
    """``gh``'s bucket for one check."""

    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"
    SKIPPING = "skipping"
    CANCEL = "cancel"


class CiVerdict(StrEnum):
    """What the checks of a PR (or of all PRs) add up to."""

    GREEN = "green"
    RED = "red"
    PENDING = "pending"
    NONE = "none"


BUCKET_VERDICT = {
    Bucket.PASS: CiVerdict.GREEN,
    Bucket.FAIL: CiVerdict.RED,
    Bucket.CANCEL: CiVerdict.RED,
    Bucket.PENDING: CiVerdict.PENDING,
}
CHECK_ORDER = (CiVerdict.RED, CiVerdict.PENDING, CiVerdict.GREEN)
PR_ORDER = (CiVerdict.RED, CiVerdict.PENDING, CiVerdict.NONE, CiVerdict.GREEN)
FAILING = frozenset({Bucket.FAIL, Bucket.CANCEL})
PASSING = frozenset({Bucket.PASS, Bucket.SKIPPING})


@dataclass
class Check:
    """One CI check of a PR as gh reports it, plus its failing lines."""

    name: str
    bucket: Bucket
    workflow: str = ""
    link: str = ""
    lines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.bucket = Bucket(self.bucket)


@dataclass
class CiResult:
    """What CI said about one PR at one head."""

    pr: int
    url: str
    head: str
    verdict: CiVerdict
    checks: list[Check] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.verdict = CiVerdict(self.verdict)
        self.checks = [Check(**c) if isinstance(c, dict) else c for c in self.checks]


def bucket_of(raw: str) -> Bucket:
    """The bucket for gh's text; an unknown one is ``FAIL`` (never green)."""
    try:
        return Bucket(raw)
    except ValueError:
        return Bucket.FAIL


def check_of(raw: dict[str, Any]) -> Check:
    """A gh JSON row as a ``Check``."""
    bucket = bucket_of(str(raw.get("bucket", "")))
    return Check(str(raw.get("name", "")), bucket, raw.get("workflow") or "", raw.get("link") or "")


def checks_of(output: str) -> list[Check]:
    """The checks in gh's ``--json`` output; ``[]`` when none are reported."""
    if NO_CHECKS in output.lower():
        return []
    try:
        return [check_of(row) for row in json.loads(output)]
    except json.JSONDecodeError as exc:
        raise UpstreamError(output.strip()) from exc


def job_of(link: str) -> str | None:
    """The Actions job id in a check's link, if it has one."""
    found = JOB_LINK.search(link)
    return found.group(1) if found else None


def first_of(order: tuple[CiVerdict, ...], found: Iterable[CiVerdict]) -> CiVerdict:
    """The first verdict of ``order`` that is in ``found``, else ``NONE``."""
    present = set(found)
    return next((v for v in order if v in present), CiVerdict.NONE)


def verdict_of(checks: list[Check]) -> CiVerdict:
    """One PR's verdict from its checks (skipped checks count for nothing)."""
    return first_of(
        CHECK_ORDER, (BUCKET_VERDICT[c.bucket] for c in checks if c.bucket in BUCKET_VERDICT)
    )


def overall(results: list[CiResult]) -> CiVerdict:
    """The boundary's verdict: green only when every watched PR is green."""
    return first_of(PR_ORDER, (r.verdict for r in results))


def _plain(line: str) -> str:
    return LOG_PREFIX.sub("", line).strip()


def failing_lines(log: str) -> list[str]:
    """The lines of a failed-step log that name what failed (or its tail)."""
    lines = [text for text in map(_plain, log.splitlines()) if text]
    hits = [t for t in lines if any(p.search(t) for p in FAILING_LINE)]
    return list(dict.fromkeys(hits))[:MAX_LINES] if hits else lines[-TAIL_LINES:]


def prs_text(results: list[CiResult]) -> str:
    """The PRs as ``#14 url; #15 url``."""
    return "; ".join(f"#{r.pr} {r.url}" for r in results)


def _label(check: Check) -> str:
    return f"{check.workflow} / {check.name}" if check.workflow else check.name


def _check_text(check: Check) -> str:
    head = CHECK_LINE.format(label=_label(check), bucket=check.bucket, link=check.link).rstrip()
    return "\n".join([head, *(f"    {line}" for line in check.lines)])


def check_lines(results: list[CiResult]) -> str:
    """One entry per check that did not pass, with its failing lines below."""
    shown = [c for r in results for c in r.checks if c.bucket not in PASSING]
    return "\n".join(_check_text(c) for c in shown)


def green_report(sprint: int, results: list[CiResult]) -> str:
    """The only text that calls a PR ready; refuses unless every result is green."""
    if not results or overall(results) is not CiVerdict.GREEN:
        raise ValueError("a PR is called ready only when every watched PR is green")
    return CI_GREEN_REPORT.format(sprint=sprint, prs=prs_text(results))


@dataclass(frozen=True)
class CiWatch:
    """Waits for the CI of watched PRs under one deadline."""

    prs: Prs
    limit_s: float

    def results(self, entries: list[StackEntry]) -> list[CiResult]:
        """One CiResult per entry, all under one deadline from now."""
        deadline = system.monotonic() + self.limit_s
        return [self._result(e, deadline) for e in entries]

    def _result(self, entry: StackEntry, deadline: float) -> CiResult:
        """Settled checks for the entry's PR, with failing lines, and their verdict."""
        checks = [self._with_lines(c) for c in self._settled(entry.pr or 0, deadline)]
        return CiResult(entry.pr or 0, entry.url, entry.head, verdict_of(checks), checks)

    def _settled(self, number: int, deadline: float) -> list[Check]:
        """Watch, read, and look again while nothing is settled."""
        checks: list[Check] = []
        for _ in range(CI_LOOKS):
            ended = self._wait(number, deadline)
            checks = self.prs.checks(number)
            if not ended or (checks and all(c.bucket is not Bucket.PENDING for c in checks)):
                return checks
            system.sleep(CI_POLL_S)
        return checks

    def _wait(self, number: int, deadline: float) -> bool:
        """False when the deadline has passed or the watch timed out."""
        left = deadline - system.monotonic()
        return left > 0 and self.prs.wait_checks(number, left)

    def _with_lines(self, check: Check) -> Check:
        """A failing check with its failing lines; others unchanged."""
        if check.bucket not in FAILING or job_of(check.link) is None:
            return check
        return replace(check, lines=failing_lines(self.prs.failed_log(check.link)))
