"""The one narrow interface to the remote (git) and the pull request service (gh).

Everything the runner does beyond the local repo goes through ``Upstream`` (git
fetch, merge, push) and ``Prs`` (look up, open and update pull requests). Tests
use bare repos for the first and a fake for the second; they never run ``gh``.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .boundary import DETACHED, FETCH_FAILED, NO_REMOTE, NO_TARGET, SYNC_OFF, PrMode
from .config import UpstreamSettings
from .git_ops import Git, GitError, with_trailer

NO_GH = "gh is not installed"
GH_LOGGED_OUT = "gh is not logged in"
NO_PR_SERVICE = "no pull request service is configured"
REFUSED_PUSH = "refusing to push {branch}: only review branches ({prefix}*) are pushed"
GH_TIMEOUT = 120


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
    """A review branch and the remote value we expect it to have (empty: absent)."""

    branch: str
    expect: str


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


Exec = Callable[[list[str]], tuple[int, str]]


def command_runner(repo: Path) -> Exec:
    """An ``Exec`` that runs argv in ``repo``; a missing binary gives exit 127."""

    def run(argv: list[str]) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                argv, cwd=repo, capture_output=True, text=True, timeout=GH_TIMEOUT, check=False
            )
        except FileNotFoundError as exc:
            return 127, str(exc)
        return proc.returncode, proc.stdout + proc.stderr

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


@dataclass
class GhPrs:
    """Pull requests through the ``gh`` command line."""

    run: Exec

    def missing(self) -> str | None:
        """Why ``gh`` cannot be used, or ``None``."""
        if self.run(["gh", "--version"])[0] != 0:
            return NO_GH
        return GH_LOGGED_OUT if self.run(["gh", "auth", "status"])[0] != 0 else None

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

    def _gh(self, *args: str) -> str:
        code, out = self.run(["gh", *args])
        if code != 0:
            raise UpstreamError(out.strip())
        return out


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
    """Git access to the remote: fetch, merge the target in, push review branches."""

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

    def merge_in(self, message: str) -> Merge:
        """Merge the target into the team branch; abort and report files on a conflict."""
        before = self.git.head()
        code, out = self.git.attempt(
            "merge", "--no-edit", "--no-verify", "-m", with_trailer(message), self.target
        )
        if code != 0:
            return self._failed_merge(out)
        after = self.git.head()
        return Merge(MergeOutcome.CURRENT) if after == before else Merge(MergeOutcome.MERGED, after)

    def _failed_merge(self, output: str) -> Merge:
        names = self.git.attempt("diff", "--name-only", "--diff-filter=U")[1]
        self.git.attempt("merge", "--abort")
        files = tuple(n for n in names.splitlines() if n)
        if not files:
            raise GitError(output.strip())
        return Merge(MergeOutcome.CONFLICT, files=files, output=output)

    def push(self, lease: Lease) -> str | None:
        """Push a review branch with its lease; ``None`` when pushed, else git's output."""
        self._guard(lease.branch)
        ref = f"refs/heads/{lease.branch}"
        argv = ["push", "--porcelain", "--no-verify", f"--force-with-lease={ref}:{lease.expect}"]
        code, out = self.git.attempt(*argv, self.settings.remote, f"{ref}:{ref}")
        return None if code == 0 else out

    def _guard(self, branch: str) -> None:
        protected = {self.settings.branch, self.git.branch()}
        if branch in protected or not branch.startswith(self.settings.prefix):
            raise UpstreamError(REFUSED_PUSH.format(branch=branch, prefix=self.settings.prefix))
