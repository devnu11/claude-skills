"""The one narrow interface to the remote (git) and the PR service (gh).

``Upstream`` wraps the git commands that touch the remote: fetch, merge in,
push with a lease. ``Prs`` is the pull-request protocol; ``GhPrs`` implements it
with ``gh`` and ``NoPrs`` stands in when there is no service. Tests use bare
repos for the remote and a fake ``Prs``; nothing else in the runner runs
``git push`` or ``gh``.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .config import UpstreamSettings
from .git_ops import Git, GitError, with_trailer

NO_GH = "gh is not installed"
GH_LOGGED_OUT = "gh is not logged in"
NO_PR_SERVICE = "no pull request service is configured"
REFUSED_PUSH = "refusing to push {branch}: only review branches ({prefix}*) are pushed"
SYNC_OFF = "[upstream] remote is empty"
NO_REMOTE = "no remote {remote!r}"
FETCH_FAILED = "git fetch {remote} failed: {error}"
NO_TARGET = "{target} does not exist"
DETACHED = "the repo is on a detached HEAD; check out the team branch"
GH_TIMEOUT = 120
NOT_FOUND = 127

FETCH_PREFIX = "git fetch "

Exec = Callable[[list[str]], tuple[int, str]]


def fetch_failed(why: str) -> bool:
    """True when ``missing`` reported a failed fetch (the target may still exist locally)."""
    return why.startswith(FETCH_PREFIX)


class UpstreamError(Exception):
    """The remote or the PR service refused or failed."""


class MergeOutcome(StrEnum):
    """What merging the target into the team branch did."""

    CURRENT = "current"
    MERGED = "merged"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class Merge:
    """The result of ``Upstream.merge_in``."""

    outcome: MergeOutcome
    sha: str = ""
    files: tuple[str, ...] = ()
    output: str = ""


@dataclass(frozen=True)
class Lease:
    """A branch to push and the remote value it must still have (empty: absent)."""

    branch: str
    expect: str


class PrState(StrEnum):
    """A pull request's state, as ``gh`` names it."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


class PrMode(StrEnum):
    """How the runner wants a pull request to look."""

    NONE = "none"
    DRAFT = "draft"
    READY = "ready"
    CLOSED = "closed"


@dataclass(frozen=True)
class Pr:
    """A pull request as the service reports it."""

    number: int
    url: str
    state: PrState
    draft: bool
    base: str


@dataclass(frozen=True)
class PrSpec:
    """How a pull request should look."""

    branch: str
    base: str
    title: str
    body: str
    mode: PrMode


class Prs(Protocol):
    """The pull-request service."""

    def missing(self) -> str | None:
        """Why the service cannot be used, or ``None``."""

    def find(self, branch: str) -> Pr | None:
        """The newest PR whose head is ``branch``."""

    def create(self, spec: PrSpec) -> Pr:
        """Open a PR."""

    def edit(self, pr: Pr, spec: PrSpec) -> None:
        """Change only what differs from ``spec``."""


def command_runner(repo: Path) -> Exec:
    """An ``Exec`` that runs argv in ``repo``; a missing binary gives exit 127."""

    def run(argv: list[str]) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                argv, cwd=repo, capture_output=True, text=True, timeout=GH_TIMEOUT, check=False
            )
        except FileNotFoundError as exc:
            return NOT_FOUND, str(exc)
        return proc.returncode, proc.stdout + proc.stderr

    return run


@dataclass
class NoPrs:
    """No pull-request service: ``missing`` always says why."""

    why: str = NO_PR_SERVICE

    def missing(self) -> str | None:
        return self.why

    def find(self, branch: str) -> Pr | None:
        raise UpstreamError(self.why)

    def create(self, spec: PrSpec) -> Pr:
        raise UpstreamError(self.why)

    def edit(self, pr: Pr, spec: PrSpec) -> None:
        raise UpstreamError(self.why)


@dataclass
class GhPrs:
    """Pull requests through the ``gh`` CLI."""

    run: Exec

    def missing(self) -> str | None:
        if self.run(["gh", "--version"])[0] != 0:
            return NO_GH
        return None if self.run(["gh", "auth", "status"])[0] == 0 else GH_LOGGED_OUT

    def find(self, branch: str) -> Pr | None:
        fields = "number,url,state,isDraft,baseRefName"
        found = json.loads(self._ok(
            ["gh", "pr", "list", "--head", branch, "--state", "all", "--json", fields,
             "--limit", "1"]
        ))  # fmt: skip
        return _pr(found[0]) if found else None

    def create(self, spec: PrSpec) -> Pr:
        argv = ["gh", "pr", "create", "--head", spec.branch, "--base", spec.base]
        argv += ["--title", spec.title, "--body", spec.body]
        draft = spec.mode is PrMode.DRAFT
        url = self._ok(argv + (["--draft"] if draft else [])).strip().splitlines()[-1]
        return Pr(int(url.rsplit("/", 1)[1]), url, PrState.OPEN, draft, spec.base)

    def edit(self, pr: Pr, spec: PrSpec) -> None:
        for argv in _edit_commands(pr, spec):
            self._ok(argv)

    def _ok(self, argv: list[str]) -> str:
        code, output = self.run(argv)
        if code != 0:
            raise UpstreamError(output)
        return output


def _pr(item: dict) -> Pr:
    return Pr(
        item["number"], item["url"], PrState(item["state"]), item["isDraft"], item["baseRefName"]
    )


def _edit_commands(pr: Pr, spec: PrSpec) -> list[list[str]]:
    n = str(pr.number)
    rebase = [["gh", "pr", "edit", n, "--base", spec.base]] if pr.base != spec.base else []
    if pr.draft and spec.mode is PrMode.READY:
        return [*rebase, ["gh", "pr", "ready", n]]
    if not pr.draft and spec.mode is PrMode.DRAFT:
        return [*rebase, ["gh", "pr", "ready", n, "--undo"]]
    return rebase


@dataclass
class Upstream:
    """The remote branch the team syncs from, over one git work tree."""

    git: Git
    settings: UpstreamSettings

    @property
    def target(self) -> str:
        """``<remote>/<branch>``."""
        return f"{self.settings.remote}/{self.settings.branch}"

    def missing(self) -> str | None:
        """Why syncing is impossible (the first that applies), or ``None``."""
        remote = self.settings.remote
        if not remote:
            return SYNC_OFF
        if self.git.attempt("remote", "get-url", remote)[0] != 0:
            return NO_REMOTE.format(remote=remote)
        code, error = self.git.attempt("fetch", "--quiet", "--prune", remote)
        if code != 0:
            return FETCH_FAILED.format(remote=remote, error=error.strip())
        return self._no_target()

    def _no_target(self) -> str | None:
        found = self.git.attempt("rev-parse", "--verify", "--quiet", self.target)[0] == 0
        return None if found else NO_TARGET.format(target=self.target)

    def team_branch(self) -> str:
        """The checked-out branch; a detached HEAD is an error."""
        name = self.git.branch()
        if name is None:
            raise UpstreamError(DETACHED)
        return name

    def merge_in(self, message: str) -> Merge:
        """Merge the target into the team branch; abort and name the files on a conflict."""
        before = self.git.head()
        code, output = self.git.attempt(
            "merge", "--no-edit", "--no-verify", "-m", with_trailer(message), self.target
        )
        if code != 0:
            return self._failed_merge(output)
        after = self.git.head()
        return Merge(MergeOutcome.CURRENT) if after == before else Merge(MergeOutcome.MERGED, after)

    def _failed_merge(self, output: str) -> Merge:
        names = self.git.attempt("diff", "--name-only", "--diff-filter=U")[1]
        files = tuple(names.split())
        self.git.attempt("merge", "--abort")
        if not files:
            raise GitError(output.strip())
        return Merge(MergeOutcome.CONFLICT, files=files, output=output)

    def merge_base(self) -> str:
        """The common ancestor of HEAD and the target."""
        return self.git.run("merge-base", "HEAD", self.target).strip()

    def push(self, lease: Lease) -> str | None:
        """Push a review branch with a lease; ``None`` when pushed, else git's output."""
        self._allow(lease.branch)
        ref = f"refs/heads/{lease.branch}"
        code, output = self.git.attempt(
            "push", "--porcelain", "--no-verify", f"--force-with-lease={ref}:{lease.expect}",
            self.settings.remote, f"{ref}:{ref}",
        )  # fmt: skip
        return None if code == 0 else output

    def _allow(self, branch: str) -> None:
        protected = {self.settings.branch, self.git.branch()}
        if branch in protected or not branch.startswith(self.settings.prefix):
            raise UpstreamError(REFUSED_PUSH.format(branch=branch, prefix=self.settings.prefix))
