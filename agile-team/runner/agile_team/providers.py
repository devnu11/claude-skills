"""Model providers: which endpoint a role's Claude Code harness talks to.

Every provider today has a Claude front end: the role still runs inside Claude
Code (its tools, guard hooks and sandbox are unchanged) and only the model
behind the Anthropic Messages API changes. That covers Ollama, a LiteLLM proxy
or any other Anthropic-compatible server.

``kind`` names the harness. Only ``anthropic`` exists; another vendor's agent
CLI would be a new kind with its own dispatch path, and role files would not
change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

DEFAULT = "anthropic"
PLACEHOLDER_TOKEN = "agile-team"
PROBE_TIMEOUT_S = 3
# Claude Code picks its own model for background work; pin them all to the role's.
MODEL_VARS = (
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
)

Probe = Callable[[str], bool]


class ProviderError(Exception):
    """A role names a provider that is not configured."""


class ProviderKind(StrEnum):
    """The harness a provider runs under."""

    ANTHROPIC = "anthropic"  # Claude Code against an Anthropic-compatible endpoint


class Billing(StrEnum):
    """Where a step's cost comes from."""

    REPORTED = "reported"  # ResultMessage.total_cost_usd, priced at Claude rates
    FREE = "free"  # local or flat-rate: ledgered as zero


@dataclass(frozen=True)
class Provider:
    """One ``[providers.<name>]`` table from ``.agile-team.toml``."""

    name: str
    base_url: str = ""
    kind: str = ProviderKind.ANTHROPIC
    token_env: str = ""
    billing: str = Billing.FREE


@dataclass
class Providers:
    """Configured providers plus the environment their tokens come from."""

    table: dict[str, Provider] = field(default_factory=dict)
    environ: Mapping[str, str] = field(default_factory=dict)

    def names(self) -> set[str]:
        return {DEFAULT, *self.table}

    def get(self, name: str) -> Provider:
        if name not in self.table:
            raise ProviderError(f"unknown provider {name!r}")
        return self.table[name]

    def env_for(self, role: Any) -> dict[str, str]:
        """Child environment additions that point ``role`` at its provider."""
        if role.provider == DEFAULT:
            return {}
        provider = self.get(role.provider)
        models = dict.fromkeys(MODEL_VARS, role.model)
        return {**endpoint_env(provider, self.token(provider)), **models}

    def token(self, provider: Provider) -> str:
        if not provider.token_env:
            return PLACEHOLDER_TOKEN
        return self.environ.get(provider.token_env, "")

    def cost_of(self, role: Any, reported: float) -> float:
        """The cost to ledger for one of ``role``'s steps."""
        if role.provider == DEFAULT or self.get(role.provider).billing == Billing.REPORTED:
            return reported
        return 0.0


def endpoint_env(provider: Provider, token: str) -> dict[str, str]:
    """Point Claude Code at ``provider``; blank the API key so it never leaves for it."""
    return {
        "ANTHROPIC_BASE_URL": provider.base_url,
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_API_KEY": "",
    }


def reachable(url: str) -> bool:
    """True when anything answers at ``url``; an HTTP error status still counts."""
    try:
        with urlopen(url, timeout=PROBE_TIMEOUT_S):
            return True
    except HTTPError:
        return True
    except (URLError, OSError, ValueError):
        return False
