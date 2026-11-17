"""Keep the rate table current from the published pricing page, in band.

The page at ``PRICING_URL`` is served as Markdown; its first table lists each
model's USD per million tokens: base input, 5-minute cache writes, 1-hour cache
writes, cache hits, output. A copy of that table lives in a JSON store under the
user's home (``resolve_store``). Existing calls refresh it: each run start and each
``cost`` query call ``refresh_rates``, which fetches at most once per
``REFRESH_EVERY`` (``RETRY_AFTER`` after a failure) and keeps the stored table
when the page can't be read. A run whose cost drifted from its estimate calls
``fetch_rates``, which ignores the throttle. ``pricing.RATES`` is the fallback
when nothing is stored. Nobody has to run anything to stay current.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .pricing import RATES, Rate, Rates

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
TIMEOUT = 10.0
HEADERS = {"User-Agent": "unattended-rates/1 (+https://github.com/devnu11/claude-skills)",
           "Accept": "text/markdown"}  # fmt: skip
REFRESH_EVERY = 24 * 3600.0
RETRY_AFTER = 3600.0
STORE = Path(".claude/unattended/rates.json")
# `| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>1</sup> | $40 / MTok |`
ROW = re.compile(r"^\|\s*Claude\s+(?P<name>[^|]+?)\s*\|(?P<cells>(?:[^|]*\|){5})\s*$", re.MULTILINE)
PRICE = re.compile(r"\$(?P<usd>[0-9.]+)\s*/\s*MTok")
TIERED = re.compile(r"\(for prompts over")  # Haiku 5.5's second row; the first one is kept
NOTES = re.compile(r"[(\[<].*")  # a note, link or footnote after the name ends it
COLUMNS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
FETCH_ERRORS = (OSError, ValueError, UnicodeDecodeError)


# ----- the page ------------------------------------------------------------------------


def fetch_page(url: str = PRICING_URL) -> str:
    """The pricing page as Markdown; the site answers 403 to Python's default user agent."""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


def parse_rates(markdown: str) -> Rates:
    """Every model row of the page's pricing table, keyed as ``pricing.RATES`` is."""
    found: Rates = {}
    for match in ROW.finditer(markdown):
        if TIERED.search(match["name"]):
            continue
        rate = parse_row(match["cells"])
        if rate:
            found.setdefault(format_key(match["name"]), rate)
    return found


def parse_row(cells: str) -> Rate | None:
    """A ``Rate`` from a row's five price cells, or None when a cell is not a price."""
    prices = [PRICE.search(cell) for cell in cells.strip("|").split("|")]
    if len(prices) != len(COLUMNS) or not all(prices):
        return None
    return Rate(**{name: float(p["usd"]) for name, p in zip(COLUMNS, prices, strict=True)})  # type: ignore[index]


def format_key(name: str) -> str:
    """``Claude Opus 5.5 (…)`` to ``opus-5-5``, as ``pricing.RATES`` is keyed."""
    plain = NOTES.sub("", name).strip().lower()
    return plain.replace(".", "-").replace(" ", "-")


# ----- the store -----------------------------------------------------------------------


def resolve_store(home: Path) -> Path:
    """Where the fetched table is kept: ``~/.claude/unattended/rates.json``."""
    return home / STORE


def read_store(path: Path) -> dict[str, Any]:
    """The store's JSON, or an empty dict when it is missing or unreadable."""
    try:
        data = json.loads(path.read_text())
    except FETCH_ERRORS:
        return {}
    return data if isinstance(data, dict) else {}


def parse_stored(data: dict[str, Any]) -> Rates | None:
    """The table in a store's JSON, or None when it holds none."""
    try:
        rates = {key: Rate(**fields) for key, fields in data.get("rates", {}).items()}
    except (TypeError, AttributeError):
        return None
    return rates or None


def write_store(path: Path, data: dict[str, Any]) -> None:
    """Write the store atomically, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def load_rates(path: Path) -> Rates:
    """The stored table, else the built-in one. Never fetches."""
    return parse_stored(read_store(path)) or RATES


def refresh_rates(path: Path, now: float) -> Rates:
    """The current table, fetched afresh when the last check is old enough."""
    data = read_store(path)
    wait = REFRESH_EVERY if data.get("read_at") == data.get("checked_at") else RETRY_AFTER
    if now - float(data.get("checked_at", 0.0)) < wait:
        return parse_stored(data) or RATES
    return fetch_rates(path, now)


def fetch_rates(path: Path, now: float) -> Rates:
    """Fetch the page and store its table now; on any failure keep what is stored."""
    data = read_store(path)
    try:
        rates = parse_rates(fetch_page())
    except FETCH_ERRORS:
        rates = {}
    if rates:
        data |= {
            "read_at": now,
            "source": PRICING_URL,
            "rates": {k: asdict(v) for k, v in rates.items()},
        }
    write_store(path, data | {"checked_at": now})
    return rates or parse_stored(data) or RATES


# ----- diagnostics ---------------------------------------------------------------------


@dataclass(frozen=True)
class Diff:
    """What one table has that another lacks, and the other way round."""

    added: dict[str, Rate] = field(default_factory=dict)
    changed: dict[str, Rate] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not (self.added or self.changed or self.removed)

    @property
    def summary(self) -> dict[str, object]:
        added = {k: asdict(v) for k, v in self.added.items()}
        changed = {k: asdict(v) for k, v in self.changed.items()}
        removed = self.removed
        return {"in_sync": self.in_sync, "added": added, "changed": changed, "removed": removed}


def compare_rates(published: Rates, current: Rates = RATES) -> Diff:
    """``published`` against ``current``."""
    added = {k: v for k, v in published.items() if k not in current}
    changed = {k: v for k, v in published.items() if k in current and current[k] != v}
    return Diff(added, changed, sorted(set(current) - set(published)))


def describe_store(path: Path, now: float) -> dict[str, Any]:
    """The store's state for ``unattended rates``: when it was read, and how it differs."""
    data = read_store(path)
    stored = parse_stored(data)
    return {
        "file": str(path),
        "read_at": format_iso(data.get("read_at")),
        "checked_at": format_iso(data.get("checked_at")),
        "age": None if "read_at" not in data else round((now - data["read_at"]) / 3600, 1),
        "models": sorted(stored or RATES),
        "against_builtin": compare_rates(stored or RATES).summary,
    }


def format_iso(epoch: Any) -> str | None:
    return None if epoch is None else time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch))
