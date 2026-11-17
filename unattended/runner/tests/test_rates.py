from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
from unattended import rates
from unattended.pricing import RATES, Rate
from unattended.rates import (
    BEGIN,
    END,
    Diff,
    compare_rates,
    format_key,
    format_price,
    parse_rates,
    render_rates,
    write_rates,
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


def test_parse_rates_reads_each_model_row_once() -> None:
    found = parse_rates(PAGE)
    assert list(found) == ["opus-5-5", "mythos-5-2", "opus-4", "haiku-5-5"]
    assert found["opus-5-5"] == Rate(4, 20, 5, 8, 0.20)
    assert found["opus-4"] == Rate(15, 75, 18.75, 30, 1.50)


def test_parse_rates_keeps_haikus_small_prompt_row() -> None:
    assert parse_rates(PAGE)["haiku-5-5"] == Rate(0.10, 0.50, 0.125, 0.20, 0.01)


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


def test_parsed_keys_are_the_tables_keys() -> None:
    assert set(parse_rates(PAGE)) <= set(RATES)


def test_compare_rates_in_sync() -> None:
    assert compare_rates(dict(RATES)) == Diff()
    assert compare_rates(dict(RATES)).in_sync


def test_compare_rates_reports_added_changed_and_removed() -> None:
    published = dict(RATES)
    del published["opus-4"]
    published["opus-5-5"] = Rate(3, 15, 4, 6, 0.15)
    published["opus-6"] = Rate(1, 2, 3, 4, 5)
    diff = compare_rates(published)
    assert diff == Diff(
        {"opus-6": Rate(1, 2, 3, 4, 5)}, {"opus-5-5": Rate(3, 15, 4, 6, 0.15)}, ["opus-4"]
    )
    assert diff.summary["added"] == {"opus-6": asdict(Rate(1, 2, 3, 4, 5))}
    assert not diff.in_sync


@pytest.mark.parametrize(
    ("usd", "text"), [(4.0, "4"), (0.2, "0.2"), (18.75, "18.75"), (0.125, "0.125")]
)
def test_format_price(usd: float, text: str) -> None:
    assert format_price(usd) == text


def test_render_rates_is_valid_python_in_the_files_layout() -> None:
    block = render_rates({"opus-5-5": Rate(4, 20, 5, 8, 0.2)}, "2026-11-17")
    assert block.startswith(BEGIN) and block.endswith(END)
    scope: dict[str, object] = {"Rate": Rate}
    exec(block, scope)
    assert scope["RATES"] == {"opus-5-5": Rate(4, 20, 5, 8, 0.2)}
    assert scope["RATES_READ"] == "2026-11-17"


def test_write_rates_replaces_only_the_block(tmp_path: Path) -> None:
    source = f"head\n{BEGIN} note\nRATES = old\n{END}\ntail\n"
    path = tmp_path / "pricing.py"
    path.write_text(source)
    write_rates(path, {"opus-5-5": Rate(4, 20, 5, 8, 0.2)})
    written = path.read_text()
    assert written.startswith("head\n") and written.endswith(f"{END}\ntail\n")
    assert '"opus-5-5": Rate(4, 20, 5, 8, 0.2),' in written
    assert "RATES = old" not in written


def test_the_real_table_round_trips_through_render(tmp_path: Path) -> None:
    source = Path(rates.__file__).with_name("pricing.py")
    copy = tmp_path / "pricing.py"
    copy.write_text(source.read_text())
    write_rates(copy, dict(RATES))
    scope: dict[str, object] = {}
    exec(copy.read_text(), scope)
    rewritten: dict[str, object] = scope["RATES"]  # type: ignore[assignment]
    assert {k: asdict(v) for k, v in rewritten.items()} == {k: asdict(v) for k, v in RATES.items()}  # type: ignore[call-overload]
