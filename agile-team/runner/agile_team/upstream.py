"""The one narrow interface to the remote (git) and the pull request service (gh).

Everything the runner does beyond the local repo goes through ``Upstream`` (git
fetch, rebase, push) and ``Prs`` (look up, open and update pull requests). Tests
use bare repos for the first and a fake for the second; they never run ``gh``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from . import stages, system
from .boundary import DETACHED, FETCH_FAILED, NO_REMOTE, NO_TARGET, SYNC_OFF, PrMode
from .ci import Check, UpstreamError, checks_of, job_of
from .ci_triage import Job, bucket_of_run, job_from
from .commands import TIMED_OUT
from .config import UpstreamSettings
from .git_ops import Git, GitError
from .rewrite import Listing, Stamped, pair, parse_listing
from .story_branches import LAND_SUFFIX

NO_GH = "gh is not installed"
GH_LOGGED_OUT = "gh is not logged in"
GH_UNREACHABLE = "gh could not check its login (rate limited or offline): {detail}"
GH_TRANSIENT = (
    "rate limit",
    "http 403",
    "http 429",
    "http 5",
    "error connecting",
    "timed out",
    "dial tcp",
    "no such host",
    "i/o timeout",
    "connection refused",
)
GH_TRUSTED_S = 600.0
NO_PR_SERVICE = "no pull request service is configured"
REFUSED_PUSH = (
    "refusing to push {branch}: only review branches ({prefix}* or {story_prefix}*) are pushed"
)
NOT_FAST_FORWARD = (
    "refusing to push {sha} to {branch}: it does not descend from the recorded {expect}; "
    "nothing was sent"
)
REFUSED_DELETE = (
    "refusing to delete {branch}: only landing branches ({story_prefix}*-land) are deleted"
)
REBASE_FLAGS = (
    "-c",
    "rebase.updateRefs=false",
    "-c",
    "rebase.rebaseMerges=false",
    "rebase",
    "--no-verify",
    "--no-autostash",
    "--no-autosquash",
)
REBASE_ARGV = (*REBASE_FLAGS, "--empty=drop")
SCRATCH_REBASE_ARGV = (*REBASE_FLAGS, "--empty=keep")
TEAM_MOVED = (
    "the team branch {team} moved from {old} while DevOps resolved the rebase; nothing was reset"
)
STAMP_FORMAT = "%H%x1f%an%x1f%ae%x1f%ad%x1f%B%x1e"
SYNC_LOST = (
    "rebasing {team} onto {target} changed paths only one side touched: {paths}; "
    "the team branch is back where it was"
)
GH_TIMEOUT = 120
GH_TIMED_OUT = "gh timed out after {limit:.0f}s"
CHECK_FIELDS = "name,state,bucket,link,workflow"
NO_JOB = "no Actions job to re-run at {link}"
NO_REQUIRED = "no required checks reported"

__all__ = ["UpstreamError"]


class SyncOutcome(StrEnum):
    """What rebasing the team branch onto the target did."""

    CURRENT = "current"
    REBASED = "rebased"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class Rebase:
    """The result of ``Upstream.rebase_onto``."""

    outcome: SyncOutcome
    sha: str = ""
    files: tuple[str, ...] = ()
    commit: str = ""
    subject: str = ""
    moved: Mapping[str, str] = field(default_factory=dict)
    output: str = ""


@dataclass(frozen=True)
class Spans:
    """The commits a rebase is judged by: HEAD before it, the old tip, the target, the head."""

    start: str
    old: str
    target_sha: str
    head: str = "HEAD"


@dataclass(frozen=True)
class Lease:
    """Push ``sha`` to ``branch``, expecting the remote at ``expect`` (empty: absent)."""

    branch: str
    expect: str
    sha: str


class PrState(StrEnum):
    """A pull request's state, as ``gh`` spells it."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


@dataclass(frozen=True)
class Pr:
    """A pull request as found on the service."""

    number: int
    url: str
    state: PrState
    draft: bool
    base: str


@dataclass(frozen=True)
class PrSpec:
    """What a stack entry's pull request should look like."""

    branch: str
    base: str
    title: str
    body: str
    mode: PrMode


class Prs(Protocol):
    """The pull request service the runner talks to."""

    def missing(self) -> str | None:
        """Why pull requests cannot be made, or ``None``."""

    def find(self, branch: str) -> Pr | None:
        """The pull request whose head is ``branch``."""

    def create(self, spec: PrSpec) -> Pr:
        """Open a pull request."""

    def edit(self, pr: Pr, spec: PrSpec) -> None:
        """Change only what differs from ``spec``."""

    def wait_checks(self, number: int, limit_s: float) -> bool:
        """Wait for the PR's checks to finish; False when ``limit_s`` ran out."""

    def checks(self, number: int) -> list[Check]:
        """The PR's checks now ([] when none are reported)."""

    def job(self, link: str) -> Job | None:
        """The Actions job behind a check link; None when the link names no job."""

    def main_checks(self, branch: str) -> list[Check]:
        """The latest check runs on ``branch``'s head commit."""

    def sha_checks(  # house-rules: allow verb-name -- name fixed by the s159 tests
        self,
        sha: str,
    ) -> list[Check]:
        """The check runs on commit ``sha``."""

    def close(self, pr: int, note: str) -> None:
        """Close pull request ``pr`` with a comment."""

    def rerun(self, link: str) -> None:
        """Re-run the Actions job at ``link``: a new attempt on the same commit."""

    def failed_log(self, link: str) -> str:
        """The failed steps' log of the Actions job at ``link``; "" when there is none."""


class Exec(Protocol):
    """Runs a command line and returns its exit code and output."""

    def __call__(self, argv: list[str], limit_s: float = GH_TIMEOUT) -> tuple[int, str]: ...


def describe_login_failure(out: str) -> str:
    """``GH_UNREACHABLE`` when gh says it hit a rate limit or the network, else logged out."""
    lines = [line.strip() for line in out.splitlines()]
    found = [line for line in lines if any(mark in line.lower() for mark in GH_TRANSIENT)]
    return GH_UNREACHABLE.format(detail=found[0]) if found else GH_LOGGED_OUT


def _noted(argv: list[str], result: tuple[int, str]) -> tuple[int, str]:
    stages.note(" ".join(argv), result[0])
    return result


def command_runner(repo: Path) -> Exec:
    """An ``Exec`` that runs argv in ``repo``; a missing binary gives exit 127."""

    def run(argv: list[str], limit_s: float = GH_TIMEOUT) -> tuple[int, str]:
        return _noted(argv, attempt(argv, limit_s))

    def attempt(argv: list[str], limit_s: float) -> tuple[int, str]:
        try:
            done = system.run(system.Command(tuple(argv), repo, limit_s))
        except FileNotFoundError as exc:
            return 127, str(exc)
        except system.TimeoutExpired:
            return TIMED_OUT, GH_TIMED_OUT.format(limit=limit_s)
        return done.code, done.out + done.err

    return run


@dataclass
class NoPrs:
    """No pull request service: always reports why."""

    why: str = NO_PR_SERVICE

    def missing(self) -> str | None:
        return self.why

    def find(self, branch: str) -> Pr | None:
        raise UpstreamError(self.why)

    def create(self, spec: PrSpec) -> Pr:
        raise UpstreamError(self.why)

    def edit(self, pr: Pr, spec: PrSpec) -> None:
        raise UpstreamError(self.why)

    def wait_checks(self, number: int, limit_s: float) -> bool:
        raise UpstreamError(self.why)

    def checks(self, number: int) -> list[Check]:
        raise UpstreamError(self.why)

    def job(self, link: str) -> Job | None:
        raise UpstreamError(self.why)

    def main_checks(self, branch: str) -> list[Check]:
        raise UpstreamError(self.why)

    def sha_checks(  # house-rules: allow verb-name -- name fixed by the s159 tests
        self,
        sha: str,
    ) -> list[Check]:
        raise UpstreamError(self.why)

    def close(self, pr: int, note: str) -> None:
        raise UpstreamError(self.why)

    def rerun(self, link: str) -> None:
        raise UpstreamError(self.why)

    def failed_log(self, link: str) -> str:
        raise UpstreamError(self.why)


@dataclass
class GhPrs:
    """Pull requests through the ``gh`` command line."""

    run: Exec
    _trusted_until: float = field(default=float("-inf"), init=False, repr=False)

    def missing(self) -> str | None:
        """Why ``gh`` cannot be used, or ``None``; a working gh is trusted for ``GH_TRUSTED_S``.

        ``gh auth status`` costs an API request, so a success is not asked again for a while;
        a failure is, on the next call. A token that dies meanwhile fails the real call.
        """
        if system.monotonic() < self._trusted_until:
            return None
        why = self._find_missing()
        if why is None:
            self._trusted_until = system.monotonic() + GH_TRUSTED_S
        return why

    def _find_missing(  # house-rules: allow query-property -- runs gh, an API request
        self,
    ) -> str | None:
        if self.run(["gh", "--version"])[0] != 0:
            return NO_GH
        code, out = self.run(["gh", "auth", "status"])
        return None if code == 0 else describe_login_failure(out)

    def find(self, branch: str) -> Pr | None:
        """The newest pull request with head ``branch``."""
        fields = "number,url,state,isDraft,baseRefName"
        argv = ["pr", "list", "--head", branch, "--state", "all", "--json", fields, "--limit", "1"]
        found = json.loads(self._gh(*argv))
        return _pr_of(found[0]) if found else None

    def create(self, spec: PrSpec) -> Pr:
        """Open the pull request; draft when the spec says so."""
        argv = ["pr", "create", "--head", spec.branch, "--base", spec.base]
        argv += ["--title", spec.title, "--body", spec.body]
        draft = spec.mode is PrMode.DRAFT
        out = self._gh(*argv, *(["--draft"] if draft else []))
        url = out.strip().splitlines()[-1]
        return Pr(int(url.rstrip("/").rsplit("/", 1)[-1]), url, PrState.OPEN, draft, spec.base)

    def edit(self, pr: Pr, spec: PrSpec) -> None:
        """Change the base, then ready or draft, only when they differ."""
        number = str(pr.number)
        if pr.base != spec.base:
            self._gh("pr", "edit", number, "--base", spec.base)
        if pr.draft and spec.mode is PrMode.READY:
            self._gh("pr", "ready", number)
        if not pr.draft and spec.mode is PrMode.DRAFT:
            self._gh("pr", "ready", number, "--undo")

    def wait_checks(self, number: int, limit_s: float) -> bool:
        """Watch the PR's checks; False when the limit ran out first."""
        argv = ["gh", "pr", "checks", str(number), "--watch"]
        return self.run(argv, limit_s)[0] != TIMED_OUT

    def checks(self, number: int) -> list[Check]:
        """The PR's checks now; gh's exit code says only pass or fail, so it is ignored."""
        argv = ["gh", "pr", "checks", str(number), "--required", "--json", CHECK_FIELDS]
        out = self.run(argv)[1]
        if NO_REQUIRED in out.lower():
            out = self.run([a for a in argv if a != "--required"])[1]
        return checks_of(out)

    def job(self, link: str) -> Job | None:
        """The Actions job behind a check link; None when the link names no job."""
        job = job_of(link)
        if job is None:
            return None
        return job_from(json.loads(self._gh("api", f"repos/{{owner}}/{{repo}}/actions/jobs/{job}")))

    def main_checks(self, branch: str) -> list[Check]:
        """The latest check runs on ``branch``'s head commit."""
        return self.sha_checks(branch)

    def sha_checks(  # house-rules: allow verb-name -- name fixed by the s159 tests
        self,
        sha: str,
    ) -> list[Check]:
        """The check runs on commit ``sha`` (or a branch name)."""
        out = self._gh("api", f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100")
        return [_run_check(r) for r in json.loads(out)["check_runs"]]

    def close(self, pr: int, note: str) -> None:
        """Close the pull request with ``note``; a PR GitHub shows as merged is already done."""
        code, out = self.run(["gh", "pr", "close", str(pr), "--comment", note])
        if code != 0 and not self._is_merged(pr):
            raise UpstreamError(out.strip())

    def _is_merged(self, pr: int) -> bool:
        code, out = self.run(["gh", "pr", "view", str(pr), "--json", "state"])
        try:
            return code == 0 and json.loads(out).get("state") == PrState.MERGED
        except (ValueError, AttributeError):
            return False

    def rerun(self, link: str) -> None:
        """Re-run the Actions job at ``link``: a new attempt on the same commit."""
        job = job_of(link)
        if job is None:
            raise UpstreamError(NO_JOB.format(link=link))
        self._gh("run", "rerun", "--job", job)

    def failed_log(self, link: str) -> str:
        """The failed steps' log for the check's Actions job; "" when unavailable."""
        job = job_of(link)
        if job is None:
            return ""
        code, out = self.run(["gh", "run", "view", "--job", job, "--log-failed"])
        return out if code == 0 else ""

    def _gh(self, *args: str) -> str:
        code, out = self.run(["gh", *args])
        if code != 0:
            raise UpstreamError(out.strip())
        return out


def _run_check(raw: dict[str, Any]) -> Check:
    return Check(raw["name"], bucket_of_run(raw), "", raw.get("details_url") or "")


def _pr_of(raw: dict[str, object]) -> Pr:
    return Pr(
        int(str(raw["number"])),
        str(raw["url"]),
        PrState(raw["state"]),
        bool(raw["isDraft"]),
        str(raw["baseRefName"]),
    )


@dataclass
class Upstream:
    """Git access to the remote: fetch, rebase onto the target, push review branches."""

    git: Git
    settings: UpstreamSettings

    @property
    def target(self) -> str:
        """``<remote>/<branch>``, what review branches are built on."""
        return f"{self.settings.remote}/{self.settings.branch}"

    def missing(self) -> str | None:
        """Why syncing must be skipped (remote, fetch, target, in that order), or ``None``."""
        remote = self.settings.remote
        if not remote:
            return SYNC_OFF
        if self.git.attempt("remote", "get-url", remote)[0] != 0:
            return NO_REMOTE.format(remote=remote)
        code, out = self.git.attempt("fetch", "--quiet", "--prune", remote)
        if code != 0:
            return FETCH_FAILED.format(remote=remote, error=out.strip())
        return self._target_missing()

    def _target_missing(self) -> str | None:
        found = self.git.attempt("rev-parse", "--verify", "--quiet", self.target)[0] == 0
        return None if found else NO_TARGET.format(target=self.target)

    def team_branch(self) -> str:
        """The checked-out branch; raises on a detached HEAD."""
        name = self.git.branch()
        if name is None:
            raise UpstreamError(DETACHED)
        return name

    def merge_base(self) -> str:
        """The commit the team branch shares with the target."""
        return self.git.run("merge-base", "HEAD", self.target).strip()

    def behind(self) -> int:
        """How many commits the target has that HEAD lacks."""
        out = self.git.run("rev-list", "--count", f"HEAD..{self.target}")
        return int(out.strip() or 0)

    def count(self, head: str) -> int:
        """How many commits ``head`` has that the target lacks."""
        out = self.git.run("rev-list", "--count", f"{self.target}..{head}")
        return int(out.strip() or 0)

    def count_unpicked(self, head: str) -> int:
        """How many commits of ``head`` the target lacks by patch (``git cherry`` ``+`` lines)."""
        out = self.git.run("cherry", self.target, head)
        return sum(1 for ln in out.splitlines() if ln.startswith("+"))

    def why_in_target(  # house-rules: allow verb-name -- name fixed by the s163 design
        self, head: str
    ) -> str | None:
        """``"contained"``, ``"patch-equivalent"`` or ``None`` when the target lacks ``head``."""
        if self.is_ancestor(head, self.target):
            return "contained"
        return "patch-equivalent" if self.count_unpicked(head) == 0 else None

    def rebase_onto(self, old: str) -> Rebase:
        """Rebase HEAD onto the target; abort and report on a conflict, check the result."""
        start, target_sha = self.git.head(), self.git.run("rev-parse", self.target).strip()
        code, out = self.git.attempt(*REBASE_ARGV, self.target)
        if code != 0:
            return self._failed_rebase(out)
        after = self.git.head()
        if after == old:
            return Rebase(SyncOutcome.CURRENT)
        self._check_kept(Spans(start, old, target_sha))
        return self._build_rebased(old, after, target_sha)

    def confirm_kept(self, spans: Spans) -> None:
        """Raise ``UpstreamError`` when a replay changed paths only one side touched (R2)."""
        lost = self.find_lost_paths(spans)
        if lost:
            text = SYNC_LOST.format(
                team=self.git.branch(), target=self.target, paths=", ".join(lost)
            )
            raise UpstreamError(text)

    def has_story_merges(self, old: str) -> bool:
        """True when the first-parent line ``target..old`` holds a story merge commit (R1)."""
        span = f"{self.target}..{old}"
        return bool(self.git.attempt("rev-list", "--first-parent", "--merges", span)[1].strip())

    def reset_team_branch(self, old: str, sha: str) -> None:
        """Move the team branch to ``sha`` while it is still at ``old`` (R3)."""
        self._refuse_moved(old)
        self.git.run("reset", "--keep", sha)

    def find_upstreamed(self, old: str) -> frozenset[str]:
        """The shas of ``target..old`` whose patch is already in the target."""
        out = self.git.run("cherry", self.target, old)
        return frozenset(ln[2:].strip() for ln in out.splitlines() if ln.startswith("- "))

    def move_team_branch(self, old: str, sha: str) -> Rebase:
        """Move the team branch to ``sha`` while it is still at ``old``; the moved pairs."""
        self._refuse_moved(old)
        target_sha = self.git.run("rev-parse", self.target).strip()
        self.git.run("reset", "--keep", sha)
        return self._build_rebased(old, sha, target_sha)

    def _build_rebased(self, old: str, sha: str, target_sha: str) -> Rebase:
        moved = pair(self.listing(f"{self.target}..{old}"), self._new_listing(target_sha))
        return Rebase(SyncOutcome.REBASED, sha, moved=moved)

    def _refuse_moved(self, old: str) -> None:
        if self.git.head() != old:
            raise UpstreamError(TEAM_MOVED.format(team=self.git.branch(), old=old))

    def listing(self, span: str) -> tuple[Stamped, ...]:
        """The commits of ``span`` (``a..b``), oldest first, with their stamps."""
        argv = ("log", "--reverse", "--topo-order", "--date=raw", f"--format={STAMP_FORMAT}")
        return parse_listing(self.git.run(*argv, span))

    def _new_listing(self, target_sha: str) -> Listing:
        return Listing(target_sha, self.listing(f"{self.target}..HEAD"))

    def _failed_rebase(self, output: str) -> Rebase:
        names = self.git.attempt("diff", "--name-only", "--diff-filter=U")[1]
        files = tuple(n for n in names.splitlines() if n)
        if not files:
            raise GitError(output.strip())
        commit = self.git.attempt("rev-parse", "REBASE_HEAD")[1].strip()
        subject = self.git.attempt("log", "-1", "--format=%s", commit)[1].strip()
        self.git.attempt("rebase", "--abort")
        return Rebase(SyncOutcome.CONFLICT, "", files, commit, subject, output=output)

    def _check_kept(self, spans: Spans) -> None:
        lost = self.find_lost_paths(spans)
        if not lost:
            return
        self.git.run("reset", "--hard", spans.start)
        text = SYNC_LOST.format(team=self.git.branch(), target=self.target, paths=", ".join(lost))
        raise UpstreamError(text)

    def find_lost_paths(self, spans: Spans) -> list[str]:
        """The paths a rebase changed that only one side touched, sorted."""
        base = self.git.run("merge-base", spans.old, self.target).strip()
        upstream, team = self._names(base, self.target), self._names(base, spans.old)
        mine = self._names(spans.old, spans.head) - upstream
        theirs = self._names(self.target, spans.head) - team
        return sorted(mine | theirs)

    def _names(self, a: str, b: str) -> set[str]:
        out = self.git.run("diff", "--name-only", "--no-renames", a, b)
        return {n for n in out.splitlines() if n}

    def push(self, lease: Lease) -> str | None:
        """Push a review branch with its lease; ``None`` when pushed, else the refusal (P2)."""
        self._guard(lease.branch)
        if lease.expect and not self.is_ancestor(lease.expect, lease.sha):
            return NOT_FAST_FORWARD.format(sha=lease.sha, branch=lease.branch, expect=lease.expect)
        ref = f"refs/heads/{lease.branch}"
        argv = ["push", "--porcelain", "--no-verify", f"--force-with-lease={ref}:{lease.expect}"]
        code, out = self.git.attempt(*argv, self.settings.remote, f"{lease.sha}:{ref}")
        return None if code == 0 else out

    def is_ancestor(self, older: str, newer: str) -> bool:
        """True when ``older`` is an ancestor of ``newer``."""
        return self.git.attempt("merge-base", "--is-ancestor", older, newer)[0] == 0

    def delete(self, lease: Lease) -> str | None:
        """Delete a landing branch with its lease (P5); the refusal or git's output on failure."""
        story_prefix = self.settings.story_prefix
        if not (lease.branch.startswith(story_prefix) and lease.branch.endswith(LAND_SUFFIX)):
            return REFUSED_DELETE.format(branch=lease.branch, story_prefix=story_prefix)
        ref = f"refs/heads/{lease.branch}"
        argv = ["push", "--porcelain", "--no-verify", f"--force-with-lease={ref}:{lease.expect}"]
        code, out = self.git.attempt(*argv, self.settings.remote, f":{ref}")
        return None if code == 0 else out

    def remote_head(  # house-rules: allow verb-name -- name fixed by the s159 tests
        self,
        branch: str,
    ) -> str:
        """The sha of ``branch`` on the remote; ``""`` when it is absent."""
        out = self.git.attempt("ls-remote", self.settings.remote, f"refs/heads/{branch}")[1]
        return out.split()[0] if out.split() else ""

    def fast_forward(  # house-rules: allow verb-name -- name fixed by the s159 tests
        self,
        sha: str,
    ) -> bool:
        """Fast-forward the checked-out branch to ``sha``; False when it can't."""
        return self.git.attempt("merge", "--ff-only", sha)[0] == 0

    def _guard(self, branch: str) -> None:
        protected = {self.settings.branch, self.git.branch()}
        prefixes = (self.settings.prefix, self.settings.story_prefix)
        if branch in protected or not branch.startswith(prefixes):
            raise UpstreamError(
                REFUSED_PUSH.format(
                    branch=branch,
                    prefix=self.settings.prefix,
                    story_prefix=self.settings.story_prefix,
                )
            )
