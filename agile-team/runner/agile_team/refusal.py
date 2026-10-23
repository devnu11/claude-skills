"""One shape for every Bash refusal: the rule, why, and the allowed form (s103)."""

from dataclasses import dataclass
from enum import StrEnum

FORMAT = "refused by rule `{rule}`: {why}. Allowed: {allowed}"


class Rule(StrEnum):
    """The guard's Bash rules, by the name a refusal reason shows (R7, R8)."""

    API_KEY = "api-key"
    GIT_WRITE = "git-write"
    GIT_OUTSIDE = "git-outside-workspace"
    GIT_UNKNOWN_DIR = "git-unknown-dir"
    GIT_ENV = "git-env"
    GIT_LOCAL = "git-local-only"
    ALLOWLIST = "allowlist"
    SANDBOX_PATH = "sandbox-path"
    WAIT = "wait-deadline"
    KILL_BY_NAME = "kill-by-name"
    KILL_RUNNER = "kill-runner"
    KILL_RUN_TIME = "kill-run-time"
    FULL_SUITE = "full-suite"
    COVERAGE = "coverage"
    TESTS_READ_ONLY = "tests-read-only"


@dataclass(frozen=True)
class Refusal:
    """A Bash refusal before its placeholders are filled (R7)."""

    rule: Rule
    why: str
    allowed: str

    def text(self) -> str:
        """The reason in the R7 shape; ``{…}`` placeholders in why/allowed survive."""
        return FORMAT.format(rule=self.rule, why=self.why, allowed=self.allowed)
