"""s29 helpers: a fake pull-request service. No network, no gh."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agile_team.ci import Bucket, Check
from agile_team.upstream import Pr, PrMode, PrSpec, PrState, UpstreamError

if TYPE_CHECKING:
    from agile_team.ci_triage import Job


@dataclass
class FakePrs:
    """Holds PRs in a dict and records every call."""

    reason: str | None = None
    prs: dict[str, Pr] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)
    next_number: int = 1
    check_list: list = field(default_factory=lambda: [Check("build", Bucket.PASS, "ci")])
    jobs: dict[str, Job] = field(default_factory=dict)
    main_list: list = field(default_factory=list)

    def checks(self, number: int) -> list:
        return self.check_list

    def job(self, link: str) -> Job | None:
        return self.jobs.get(link)

    def main_checks(self, branch: str) -> list:
        self.calls.append(("main_checks", branch))
        return self.main_list

    def rerun(self, link: str) -> None:
        self.calls.append(("rerun", link))

    def wait_checks(self, number: int, seconds: float) -> bool:
        return True

    def failed_log(self, link: str) -> str:
        return ""

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

    def close(self, pr: int, note: str) -> None:
        self.calls.append(("close", pr, note))

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
