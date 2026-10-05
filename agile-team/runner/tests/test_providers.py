"""Provider environment, pricing and endpoint probing."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from agile_team.providers import (
    MODEL_VARS,
    PLACEHOLDER_TOKEN,
    Billing,
    Provider,
    ProviderError,
    Providers,
    reachable,
)

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


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(404 if self.path == "/missing" else 200)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        pass


def test_reachable() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert reachable(base)
        assert reachable(base + "/missing")
    finally:
        server.shutdown()
        server.server_close()
    assert not reachable(base)
    assert not reachable("not a url")
