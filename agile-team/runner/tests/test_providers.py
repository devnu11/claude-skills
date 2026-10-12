"""Provider environment, pricing and endpoint probing."""

from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from agile_team import system
from agile_team.providers import (
    MODEL_VARS,
    PLACEHOLDER_TOKEN,
    Billing,
    Provider,
    ProviderError,
    Providers,
    reachable,
)

from .fake_system import FakeSystem

LOCAL = Provider("local", "http://localhost:11434")
PAID = Provider("paid", "https://proxy.example", token_env="PROXY_TOKEN", billing=Billing.REPORTED)
PROVIDERS = Providers({"local": LOCAL, "paid": PAID}, {"PROXY_TOKEN": "tok"})


def role(provider: str, model: str = "qwen3-coder") -> SimpleNamespace:
    return SimpleNamespace(provider=provider, model=model)


def test_default_provider_adds_nothing() -> None:
    assert PROVIDERS.env_for(role("anthropic")) == {}
    assert PROVIDERS.names() == {"anthropic", "local", "paid"}


def test_local_provider_points_claude_code_at_the_endpoint() -> None:
    env = PROVIDERS.env_for(role("local"))
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
    assert env["ANTHROPIC_AUTH_TOKEN"] == PLACEHOLDER_TOKEN
    assert env["ANTHROPIC_API_KEY"] == ""
    assert {env[v] for v in MODEL_VARS} == {"qwen3-coder"}


def test_token_comes_from_the_named_variable() -> None:
    assert PROVIDERS.env_for(role("paid"))["ANTHROPIC_AUTH_TOKEN"] == "tok"
    assert Providers({"paid": PAID}).token(PAID) == ""


def test_unknown_provider_is_an_error() -> None:
    with pytest.raises(ProviderError, match="ghost"):
        PROVIDERS.env_for(role("ghost"))


@pytest.mark.parametrize(("name", "cost"), [("anthropic", 0.5), ("paid", 0.5), ("local", 0.0)])
def test_cost_follows_billing(name: str, cost: float) -> None:
    assert PROVIDERS.cost_of(role(name), 0.5) == cost


# ----- reachable: the probe goes through the seam (s77 Z4) --------------------------------

URL = "http://localhost:11434"


def test_reachable_when_something_answers(fake: FakeSystem) -> None:
    fake.web[URL] = system.HttpReply(200, "application/json", b"{}")
    assert reachable(URL) is True


def test_reachable_counts_an_http_error_status(fake: FakeSystem) -> None:
    fake.web[URL] = HTTPError(URL, 500, "boom", None, None)  # type: ignore[arg-type]
    assert reachable(URL) is True


def test_not_reachable_when_the_connection_is_refused(fake: FakeSystem) -> None:
    assert reachable(URL) is False


@pytest.mark.parametrize("error", [URLError("no route"), OSError("down"), ValueError("bad url")])
def test_not_reachable_on_a_network_or_url_error(fake: FakeSystem, error: Exception) -> None:
    fake.web[URL] = error
    assert reachable(URL) is False
