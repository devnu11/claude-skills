"""CI results of the sprint's pull requests: the data, the verdict rules, the texts, and the wait.

``CiWatch`` waits for the checks of the watched PRs. ``gh`` is reached only through a ``Prs``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import cache
from typing import TYPE_CHECKING, Any

from . import system
from .ci_findings import pick_lines
from .ci_triage import (
    BUCKET_KIND,
    FAILING,
    PASSING,
    Bucket,
    CheckKind,
    Seen,
    failing_step,
    kind_of,
    ran,
    rerun_key,
)

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
CI_GREEN_REPORT = (
    "Sprint {sprint}'s CI passed on {prs}: ready to merge by fast-forward only, never by a "
    "rebase or squash merge."
)
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
NO_OPEN_PR_WHY = "no open pull request to watch"
CHECK_LINE = "- {label}: {bucket}{detail} {link}"
CI_MAIN_REPORT = (
    "Sprint {sprint} ended, CI blocked by main: the same job and step fail on {target}'s head, "
    "story {story} opened for it. {prs} is NOT ready; do not merge it. The team carries on, "
    "and the PR is checked again at the next sprint end."
)
CI_STALE = "a check ran on another commit than the pushed head; it does not count"
CI_OURS_REFUSAL = (
    "sprint {sprint}'s CI failed where our code ran: {failures}. A re-run is not a fix and "
    '"flaky" is not a reason: ask the liaison for a bug story (request_story) and '
    "record_ci_bug(story) once it is opened, or route the fix to an open story with "
    "record_ci_bug(story)"
)
NO_STEP_NAMED = "step not named"
__all__ = ["FAILING", "PASSING", "Bucket"]


class UpstreamError(Exception):
    """The remote or the PR service refused or failed."""


class CiVerdict(StrEnum):
    """What the checks of a PR (or of all PRs) add up to."""

    GREEN = "green"
    RED = "red"
    PENDING = "pending"
    INFRA = "infra"
    MAIN = "main"
    NONE = "none"


KIND_VERDICT = {
    CheckKind.OURS: CiVerdict.RED,
    CheckKind.INFRA: CiVerdict.INFRA,
    CheckKind.MAIN: CiVerdict.MAIN,
    CheckKind.PENDING: CiVerdict.PENDING,
    CheckKind.STALE: CiVerdict.PENDING,
    CheckKind.RERUN: CiVerdict.PENDING,
    CheckKind.GREEN: CiVerdict.GREEN,
}
CHECK_ORDER = (CiVerdict.RED, CiVerdict.INFRA, CiVerdict.MAIN, CiVerdict.PENDING, CiVerdict.GREEN)
PR_ORDER = (
    CiVerdict.RED,
    CiVerdict.INFRA,
    CiVerdict.MAIN,
    CiVerdict.PENDING,
    CiVerdict.NONE,
    CiVerdict.GREEN,
)


@dataclass
class Check:
    """One CI check of a PR as gh reports it, plus its failing lines."""

    name: str
    bucket: Bucket
    workflow: str = ""
    link: str = ""
    lines: list[str] = field(default_factory=list)
    kind: CheckKind | None = None
    step: str = ""
    head: str = ""

    def __post_init__(self) -> None:
        self.bucket = Bucket(self.bucket)
        self.kind = CheckKind(self.kind) if self.kind else None


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


def kind_or_bucket(check: Check) -> CheckKind:
    """The check's kind; an untriaged check is read from its bucket."""
    return check.kind or BUCKET_KIND[check.bucket]


def verdict_of(checks: list[Check]) -> CiVerdict:
    """One PR's verdict from its checks (skipped checks count for nothing)."""
    kinds = (kind_or_bucket(c) for c in checks)
    return first_of(CHECK_ORDER, (KIND_VERDICT[k] for k in kinds if k in KIND_VERDICT))


def overall(results: list[CiResult]) -> CiVerdict:
    """The boundary's verdict: green only when every watched PR is green."""
    return first_of(PR_ORDER, (r.verdict for r in results))


def _plain(line: str) -> str:
    return LOG_PREFIX.sub("", line).strip()


def failing_lines(log: str) -> list[str]:
    """The lines of a failed-step log that name what failed (or its tail)."""
    lines = [text for text in map(_plain, log.splitlines()) if text]
    hits = pick_lines(lines)
    return list(dict.fromkeys(hits))[:MAX_LINES] if hits else lines[-TAIL_LINES:]


def prs_text(results: list[CiResult]) -> str:
    """The PRs as ``#14 url; #15 url``."""
    return "; ".join(f"#{r.pr} {r.url}" for r in results)


def label(check: Check) -> str:
    """The check's workflow and name."""
    return f"{check.workflow} / {check.name}" if check.workflow else check.name


def detail(check: Check) -> str:
    """What the line says beyond the bucket: the failing step, or why it does not count."""
    if check.step:
        return f" at step {check.step}"
    return DETAILS.get(check.kind, "") if check.kind else ""


DETAILS = {CheckKind.INFRA: " (no step ran)", CheckKind.STALE: " (ran on another commit)"}


def _check_text(check: Check) -> str:
    fields = {"label": label(check), "bucket": check.bucket, "detail": detail(check)}
    head = CHECK_LINE.format(**fields, link=check.link).rstrip()
    return "\n".join([head, *(f"    {line}" for line in check.lines)])


def check_lines(results: list[CiResult]) -> str:
    """One entry per check that did not pass, with its failing lines below."""
    shown = [c for r in results for c in r.checks if c.bucket not in PASSING]
    return "\n".join(_check_text(c) for c in shown)


def _has_kind(checks: list[Check], kind: CheckKind) -> bool:
    return any(kind_or_bucket(c) is kind for c in checks)


def _of_kind(results: list[CiResult], kind: CheckKind) -> list[Check]:
    return [c for r in results for c in r.checks if kind_or_bucket(c) is kind]


def ours_text(results: list[CiResult]) -> str:
    """The checks that failed where our code ran, as ``<label>, step <step>``."""
    ours = _of_kind(results, CheckKind.OURS)
    return "; ".join(f"{label(c)}, step {c.step or NO_STEP_NAMED}" for c in ours)


def mark_main(checks: list[Check], failures: frozenset[tuple[str, str]]) -> list[Check]:
    """Our failing checks that also fail on main (same name and step) become ``main``."""

    def broken(c: Check) -> bool:
        return kind_or_bucket(c) is CheckKind.OURS and bool(c.step) and (c.name, c.step) in failures

    return [replace(c, kind=CheckKind.MAIN) if broken(c) else c for c in checks]


def rerun_due(entries: list[StackEntry]) -> list[tuple[StackEntry, Check]]:
    """The infra checks whose one re-run at this head is not used yet."""
    return [
        (e, c)
        for e in entries
        if e.ci
        for c in _of_kind([e.ci], CheckKind.INFRA)
        if rerun_key(e.head, label(c)) not in e.reran
    ]


class CardState(StrEnum):
    """The state of a sprint card's CI pill."""

    GREEN = "green"
    FAILED = "failed"
    MAIN = "main"
    RERUN = "rerun"
    RUNNING = "running"
    NONE = "none"


@dataclass(frozen=True)
class Card:
    """The CI pill of a stack entry."""

    state: CardState
    text: str

    def row(self) -> dict[str, str]:
        """The snapshot's ``{"state", "text"}``."""
        return {"state": str(self.state), "text": self.text}


CARD_ROWS = (
    (CheckKind.OURS, CardState.FAILED, "CI failed: {job}, {step}"),
    (CheckKind.INFRA, CardState.FAILED, "CI failed: {job}, no step ran"),
    (CheckKind.MAIN, CardState.MAIN, "CI blocked by main: {job}"),
    (CheckKind.RERUN, CardState.RERUN, "re-running {job}"),
    (CheckKind.PENDING, CardState.RUNNING, "CI running"),
    (CheckKind.STALE, CardState.RUNNING, "CI running"),
    (CheckKind.GREEN, CardState.GREEN, "CI green"),
)
NO_CARD = Card(CardState.NONE, "no CI result")


def card_of(result: CiResult) -> Card:
    """The pill for one CI read: the first row whose kind a check has."""
    for kind, state, text in CARD_ROWS:
        found = _of_kind([result], kind)
        if found:
            job, step = label(found[0]), found[0].step or NO_STEP_NAMED
            return Card(state, text.format(job=job, step=step))
    return NO_CARD


def green_report(sprint: int, results: list[CiResult]) -> str:
    """The only text that calls a PR ready; refuses unless every result is green."""
    if not results or overall(results) is not CiVerdict.GREEN:
        raise ValueError("a PR is called ready only when every watched PR is green")
    return CI_GREEN_REPORT.format(sprint=sprint, prs=prs_text(results))


@dataclass(frozen=True)
class Look:
    """One CI read: its deadline and the lazily read, cached failures of main."""

    deadline: float
    main: Callable[[], frozenset[tuple[str, str]]]


@dataclass(frozen=True)
class CiWatch:
    """Waits for the CI of watched PRs under one deadline."""

    prs: Prs
    limit_s: float
    target: str = ""

    def results(self, entries: list[StackEntry]) -> list[CiResult]:
        """One CiResult per entry, all under one deadline from now."""
        look = Look(system.monotonic() + self.limit_s, cache(self._main_failures))
        return [self._result(e, look) for e in entries]

    def rerun(self, number: int, check: Check) -> None:
        """Re-run the check's job, then look until the PR shows its new attempt."""
        self.prs.rerun(check.link)
        for _ in range(CI_LOOKS):
            if self._moved(number, check):
                return
            system.sleep(CI_POLL_S)

    def _moved(self, number: int, check: Check) -> bool:
        """True when the PR has a check with this label and another link."""
        return any(
            label(c) == label(check) and c.link != check.link for c in self.prs.checks(number)
        )

    def _result(self, entry: StackEntry, look: Look) -> CiResult:
        """Settled checks for the entry's PR, triaged against its head, and their verdict."""
        settled = self._settled(entry.pr or 0, look.deadline)
        checks = self._against_main([self._triaged(c, entry.head) for c in settled], look)
        return CiResult(entry.pr or 0, entry.url, entry.head, verdict_of(checks), checks)

    def _triaged(self, check: Check, head: str) -> Check:
        return classify_check(self.prs, check, head)

    def _against_main(self, checks: list[Check], look: Look) -> list[Check]:
        """Checks that fail on main too become ``main``; main is read once, when needed."""
        if not self.target or not _has_kind(checks, CheckKind.OURS):
            return checks
        return mark_main(checks, look.main())

    def _main_failures(self) -> frozenset[tuple[str, str]]:
        """``(check name, failing step)`` of each failing job on the target's head."""
        failing = [c for c in self.prs.main_checks(self.target) if c.bucket in FAILING]
        jobs = [(c.name, self.prs.job(c.link)) for c in failing if job_of(c.link)]
        return frozenset((n, failing_step(j)) for n, j in jobs if j and ran(j))

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


def classify_check(prs: Prs, check: Check, head: str) -> Check:
    """The check with its failing lines, its job's commit, its kind and failing step."""
    job = prs.job(check.link) if job_of(check.link) else None
    kind = kind_of(Seen(check.bucket, job), head)
    step = failing_step(job) if kind in (CheckKind.OURS, CheckKind.INFRA) else ""
    return replace(_add_lines(prs, check), kind=kind, step=step, head=job.head if job else "")


def _add_lines(prs: Prs, check: Check) -> Check:
    """A failing check with its failing lines; others unchanged."""
    if check.bucket not in FAILING or job_of(check.link) is None:
        return check
    return replace(check, lines=failing_lines(prs.failed_log(check.link)))


def _is_settled(checks: list[Check]) -> bool:
    return bool(checks) and all(c.bucket is not Bucket.PENDING for c in checks)


@dataclass(frozen=True)
class ShaWatch:
    """L8: waits for the checks of one commit (a landing head) with no pull request."""

    prs: Prs
    limit_s: float

    async def poll_result(
        self,
        sha: str,
        reran: list[str],
    ) -> CiResult:
        """Poll the commit's checks until they settle or the deadline passes, then triage them."""
        deadline = system.monotonic() + self.limit_s
        checks = await system.run_in_thread(self.prs.list_checks, sha)
        while not _is_settled(checks) and system.monotonic() < deadline:
            await system.async_sleep(CI_POLL_S)
            checks = await system.run_in_thread(self.prs.list_checks, sha)
        triaged = [await system.run_in_thread(classify_check, self.prs, c, sha) for c in checks]
        return CiResult(0, "", sha, verdict_of(triaged), triaged)
