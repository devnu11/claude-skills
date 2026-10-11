"""s29 helpers: a bare ``origin`` plus a clone, and a fake PR service. No network, no gh."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agile_team.upstream import Pr, PrMode, PrSpec, PrState, UpstreamError

from .conftest import git


def make_origin(tmp_path: Path) -> tuple[Path, Path]:
    """A bare origin with one commit on main, and the clone that is the team repo."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    configure(seed)
    (seed / "base.txt").write_text("base\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "base")
    git(seed, "push", "-q", "origin", "HEAD:main")
    work = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    configure(work)
    (work / ".gitignore").write_text(".team/run/\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "ignore run dir")
    git(work, "branch", "-q", "-m", "agile-team")
    return origin, work


def configure(repo: Path) -> None:
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "commit.gpgsign", "false")


def commit(repo: Path, name: str, text: str = "x\n", message: str = "") -> str:
    """Write ``name`` and commit it; return the sha."""
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message or f"add {name}")
    return git(repo, "rev-parse", "HEAD").strip()


def land_upstream(tmp_path: Path, origin: Path, name: str, text: str = "up\n") -> str:
    """Commit ``name`` to origin's main from a second clone."""
    other = tmp_path / "other"
    if not other.exists():
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(other)], check=True, capture_output=True
        )
        configure(other)
    git(other, "pull", "-q", "--rebase", "origin", "main")
    sha = commit(other, name, text)
    git(other, "push", "-q", "origin", "HEAD:main")
    return sha


def land_by_rebase(tmp_path: Path, origin: Path, shas: list[str], repo: Path) -> None:
    """Rebase-merge ``shas`` (cherry-pick, new hashes) onto origin's main."""
    other = tmp_path / "other"
    land_upstream(tmp_path, origin, ".keep", "k\n")
    git(repo, "fetch", "-q", str(origin))
    for sha in shas:
        git(other, "fetch", "-q", str(repo), sha)
        git(other, "cherry-pick", sha)
    git(other, "push", "-q", "origin", "HEAD:main")


def rev(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", ref).strip()


def is_ancestor(repo: Path, old: str, new: str) -> bool:
    return (
        subprocess.run(["git", "merge-base", "--is-ancestor", old, new], cwd=repo).returncode == 0
    )


@dataclass
class FakePrs:
    """Holds PRs in a dict and records every call."""

    reason: str | None = None
    prs: dict[str, Pr] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)
    next_number: int = 1

    def missing(self) -> str | None:
        return self.reason

    def find(self, branch: str) -> Pr | None:
        return self.prs.get(branch)

    def create(self, spec: PrSpec) -> Pr:
        self.calls.append(("create", spec))
        pr = Pr(
            self.next_number,
            f"https://example/pull/{self.next_number}",
            PrState.OPEN,
            spec.mode is PrMode.DRAFT,
            spec.base,
        )
        self.next_number += 1
        self.prs[spec.branch] = pr
        return pr

    def edit(self, pr: Pr, spec: PrSpec) -> None:
        self.calls.append(("edit", pr.number, spec))
        self.prs[spec.branch] = Pr(
            pr.number, pr.url, pr.state, spec.mode is PrMode.DRAFT, spec.base
        )

    def set_state(self, branch: str, state: PrState) -> None:
        old = self.prs[branch]
        self.prs[branch] = Pr(old.number, old.url, state, old.draft, old.base)


class BrokenPrs(FakePrs):
    def create(self, spec: PrSpec) -> Pr:
        raise UpstreamError("boom")
