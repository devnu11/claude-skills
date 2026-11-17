from __future__ import annotations

import pytest
from unattended.pricing import RATES, Estimate, Rate, Usage, find_rate

SDK_USAGE = {
    "input_tokens": 100,
    "output_tokens": 50,
    "cache_creation_input_tokens": 30,
    "cache_read_input_tokens": 1000,
}


@pytest.mark.parametrize(
    ("model", "key"),
    [
        ("claude-opus-5-5", "opus-5-5"),
        ("claude-opus-4-5-20251101", "opus-4-5"),
        ("claude-fable-5-1", "fable-5-1"),
        ("claude-fable-5", "fable-5"),
        ("opus-5", "opus-5"),
    ],
)
def test_rate_for_known_models(model: str, key: str) -> None:
    assert find_rate(model) is RATES[key]


@pytest.mark.parametrize("model", ["haiku", "claude-opus-9-9", "", "gpt-4o"])
def test_rate_for_unknown_models(model: str) -> None:
    assert find_rate(model) is None


def test_usage_from_sdk_counts_unsplit_cache_writes_as_five_minute() -> None:
    assert Usage.from_sdk(SDK_USAGE) == Usage(100, 50, 30, 0, 1000)


def test_usage_from_sdk_prefers_the_cache_creation_split() -> None:
    split = {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 20}
    found = Usage.from_sdk({**SDK_USAGE, "cache_creation": split})
    assert (found.cache_write_5m, found.cache_write_1h) == (10, 20)


def test_usage_from_sdk_defaults_missing_kinds_to_zero() -> None:
    assert Usage.from_sdk({"output_tokens": 5}) == Usage(output=5)


def test_usage_adds_each_kind() -> None:
    assert Usage(1, 2, 3, 4, 5) + Usage(10, 20, 30, 40, 50) == Usage(11, 22, 33, 44, 55)


def test_usage_cost_prices_each_kind_per_million() -> None:
    rate = Rate(input=1, output=2, cache_write_5m=3, cache_write_1h=4, cache_read=5)
    usage = Usage(1_000_000, 1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert usage.compute_cost(rate) == 15.0


def test_opus_5_5_rates_match_the_pricing_page() -> None:
    usage = Usage(input=1_000_000, output=1_000_000, cache_read=1_000_000)
    assert usage.compute_cost(RATES["opus-5-5"]) == pytest.approx(4 + 20 + 0.20)


def test_estimate_sums_priced_models() -> None:
    million = Usage(output=1_000_000)
    by_model = {"claude-opus-5-5": million, "claude-haiku-5-5": million}
    assert Estimate.compute(by_model) == Estimate(20.5, [])


def test_estimate_is_null_with_an_unpriced_model() -> None:
    by_model = {"claude-opus-5-5": Usage(output=1_000_000), "mystery": Usage(output=1)}
    assert Estimate.compute(by_model) == Estimate(None, ["mystery"])


def test_estimate_of_nothing_is_zero() -> None:
    assert Estimate.compute({}) == Estimate(0.0, [])
