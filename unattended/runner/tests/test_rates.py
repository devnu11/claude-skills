from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from unattended import rates
from unattended.pricing import RATES, Rate
from unattended.rates import (
    REFRESH_EVERY,
    RETRY_AFTER,
    Diff,
    compare_rates,
    describe_store,
    fetch_rates,
    format_key,
    load_rates,
    parse_rates,
    refresh_rates,
    resolve_store,
)

PAGE = """
## Model pricing

| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| :-- | :-- | :-- | :-- | :-- | :-- |
| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |
| Claude Mythos 5.2 ([limited availability](https://support.claude.com/x)) | $8 / MTok | $10 / MTok | $16 / MTok | $0.20 / MTok<sup>1</sup> | $40 / MTok |
| Claude Opus 4 ([retired, except on Claude Models on Google Cloud (Google managed)](https://x)) | $15 / MTok | $18.75 / MTok | $30 / MTok | $1.50 / MTok | $75 / MTok |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |

## Other tables

| Model | Cache hit multiplier | Cache hit price |
| :-- | :-- | :-- |
| Claude Opus 5.5 | 0.05x | $0.20 USD |
"""  # noqa: E501
PAGE_RATES = {
    "opus-5-5": Rate(4, 20, 5, 8, 0.20),
    "mythos-5-2": Rate(8, 40, 10, 16, 0.20),
    "opus-4": Rate(15, 75, 18.75, 30, 1.50),
    "haiku-5-5": Rate(0.10, 0.50, 0.125, 0.20, 0.01),
}
NOW = 1_800_000_000.0


# ----- the page ------------------------------------------------------------------------


def test_parse_rates_reads_each_model_row_once() -> None:
    assert parse_rates(PAGE) == PAGE_RATES


def test_parse_rates_skips_rows_without_five_prices() -> None:
    assert parse_rates("| Claude Opus 5.5 | 0.05x | $0.20 USD | a | b | c |\n") == {}


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Opus 5.5", "opus-5-5"),
        ("Mythos 5.2 ([limited availability](https://x))", "mythos-5-2"),
        ("Haiku 5.5 (for prompts up to 100,000 tokens)", "haiku-5-5"),
        ("Opus 4", "opus-4"),
    ],
)
def test_format_key(name: str, key: str) -> None:
    assert format_key(name) == key


def test_parsed_keys_are_the_builtin_tables_keys() -> None:
    assert set(parse_rates(PAGE)) <= set(RATES)


# ----- the store -----------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return resolve_store(tmp_path)


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The page the fetch returns; each fetch appends to the returned list."""
    fetched: list[str] = []

    def fetch(url: str = rates.PRICING_URL) -> str:
        fetched.append(url)
        return PAGE

    monkeypatch.setattr(rates, "fetch_page", fetch)
    return fetched


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(url: str = rates.PRICING_URL) -> str:
        raise OSError("no network")

    monkeypatch.setattr(rates, "fetch_page", fail)


def test_rates_file_is_under_the_homes_claude_dir(tmp_path: Path) -> None:
    assert resolve_store(tmp_path) == tmp_path / ".claude" / "unattended" / "rates.json"


def test_load_rates_falls_back_to_the_builtin_table(store: Path) -> None:
    assert load_rates(store) is RATES


def test_fetch_rates_stores_the_page(store: Path, page: list[str]) -> None:
    assert fetch_rates(store, NOW) == PAGE_RATES
    data = json.loads(store.read_text())
    assert (data["read_at"], data["checked_at"], data["source"]) == (NOW, NOW, rates.PRICING_URL)
    assert data["rates"]["opus-5-5"] == asdict(Rate(4, 20, 5, 8, 0.20))
    assert load_rates(store) == PAGE_RATES


def test_fetch_rates_offline_keeps_what_was_stored(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rates, "fetch_page", lambda url=rates.PRICING_URL: PAGE)
    fetch_rates(store, NOW)
    monkeypatch.setattr(rates, "fetch_page", _fail)
    assert fetch_rates(store, NOW + 10) == PAGE_RATES
    data = json.loads(store.read_text())
    assert (data["read_at"], data["checked_at"]) == (NOW, NOW + 10)


def test_fetch_rates_offline_with_nothing_stored_uses_the_builtin_table(
    store: Path, offline: None
) -> None:
    assert fetch_rates(store, NOW) is RATES
    assert json.loads(store.read_text()) == {"checked_at": NOW}


def test_fetch_rates_ignores_a_page_without_a_table(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rates, "fetch_page", lambda url=rates.PRICING_URL: "maintenance")
    assert fetch_rates(store, NOW) is RATES


def test_refresh_rates_fetches_once_a_day(store: Path, page: list[str]) -> None:
    refresh_rates(store, NOW)
    refresh_rates(store, NOW + REFRESH_EVERY - 1)
    assert len(page) == 1
    refresh_rates(store, NOW + REFRESH_EVERY)
    assert len(page) == 2


def test_refresh_rates_retries_sooner_after_a_failure(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[float] = []

    def fail(url: str = rates.PRICING_URL) -> str:
        calls.append(1)
        raise OSError("no network")

    monkeypatch.setattr(rates, "fetch_page", fail)
    refresh_rates(store, NOW)
    refresh_rates(store, NOW + RETRY_AFTER - 1)
    refresh_rates(store, NOW + RETRY_AFTER)
    assert len(calls) == 2


def test_refresh_rates_returns_the_stored_table_between_fetches(
    store: Path, page: list[str]
) -> None:
    refresh_rates(store, NOW)
    assert refresh_rates(store, NOW + 60) == PAGE_RATES
    assert len(page) == 1


def test_a_corrupt_store_is_ignored(store: Path, offline: None) -> None:
    store.parent.mkdir(parents=True)
    store.write_text("{not json")
    assert load_rates(store) is RATES
    assert fetch_rates(store, NOW) is RATES
    store.write_text(json.dumps({"rates": {"x": "not a rate"}}))
    assert load_rates(store) is RATES
    store.write_text(json.dumps([1, 2]))
    assert load_rates(store) is RATES


def _fail(url: str = rates.PRICING_URL) -> str:
    raise OSError("no network")


# ----- diagnostics ---------------------------------------------------------------------


def test_compare_rates_in_sync() -> None:
    assert compare_rates(dict(RATES)) == Diff()
    assert compare_rates(dict(RATES)).in_sync


def test_compare_rates_reports_added_changed_and_removed() -> None:
    published = dict(RATES)
    del published["opus-4"]
    published["opus-5-5"] = Rate(3, 15, 4, 6, 0.15)
    published["opus-6"] = Rate(1, 2, 3, 4, 5)
    diff = compare_rates(published)
    added, changed = {"opus-6": Rate(1, 2, 3, 4, 5)}, {"opus-5-5": Rate(3, 15, 4, 6, 0.15)}
    assert diff == Diff(added, changed, ["opus-4"])
    assert diff.summary["added"] == {"opus-6": asdict(Rate(1, 2, 3, 4, 5))}
    assert not diff.in_sync


def test_describe_store_before_and_after_a_fetch(store: Path, page: list[str]) -> None:
    empty = describe_store(store, NOW)
    assert (empty["read_at"], empty["age"], empty["models"]) == (None, None, sorted(RATES))
    fetch_rates(store, NOW)
    found = describe_store(store, NOW + 7200)
    assert (found["age"], found["models"]) == (2.0, sorted(PAGE_RATES))
    assert found["read_at"] is not None
    assert found["against_builtin"]["in_sync"] is False
    assert found["against_builtin"]["added"] == {}
