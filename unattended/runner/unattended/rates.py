"""Compare ``pricing.RATES`` with the published pricing page, and rewrite it.

The page at ``PRICING_URL`` is served as Markdown; its first table lists each
model's USD per million tokens: base input, 5-minute cache writes, 1-hour cache
writes, cache hits, output. ``unattended rates`` prints what differs; with
``--write FILE`` it rewrites the block between ``RATES-BEGIN`` and ``RATES-END``
in that file (normally ``pricing.py``). A daily workflow runs it and opens a PR
with the result; see ``reference/protocol.md``.
"""

from __future__ import annotations

import re
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .pricing import RATES, Rate

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
TIMEOUT = 30.0
HEADERS = {"User-Agent": "unattended-rates/1 (+https://github.com/devnu11/claude-skills)",
           "Accept": "text/markdown"}  # fmt: skip
BEGIN, END = "# RATES-BEGIN", "# RATES-END"
# `| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>1</sup> | $40 / MTok |`
ROW = re.compile(r"^\|\s*Claude\s+(?P<name>[^|]+?)\s*\|(?P<cells>(?:[^|]*\|){5})\s*$", re.MULTILINE)
PRICE = re.compile(r"\$(?P<usd>[0-9.]+)\s*/\s*MTok")
TIERED = re.compile(r"\(for prompts over")  # Haiku 5.5's second row; the first one is kept
NOTES = re.compile(r"[(\[<].*")  # a note, link or footnote after the name ends it
COLUMNS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
type Rates = dict[str, Rate]


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


@dataclass(frozen=True)
class Diff:
    """What the page has that the table lacks, and the other way round."""

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
    """The page against the table."""
    added = {k: v for k, v in published.items() if k not in current}
    changed = {k: v for k, v in published.items() if k in current and current[k] != v}
    return Diff(added, changed, sorted(set(current) - set(published)))


def render_rates(rates: Rates, read_on: str) -> str:
    """The source block between the markers, in the file's layout."""
    rows = "".join(f'    "{key}": {render_rate(rate)},\n' for key, rate in rates.items())
    head = f"{BEGIN} -- rewritten by `unattended rates --write`; keep the layout\n"
    return f'{head}RATES_READ = "{read_on}"\nRATES: dict[str, Rate] = {{\n{rows}}}\n{END}'


def render_rate(rate: Rate) -> str:
    return "Rate(" + ", ".join(format_price(p) for p in asdict(rate).values()) + ")"


def format_price(usd: float) -> str:
    """``4`` for whole dollars, else the shortest exact decimal."""
    return str(int(usd)) if usd == int(usd) else f"{usd:g}"


def write_rates(path: Path, rates: Rates) -> None:
    """Replace the block between the markers in ``path`` with ``rates``."""
    source = path.read_text()
    start, stop = source.index(BEGIN), source.index(END) + len(END)
    block = render_rates(rates, time.strftime("%Y-%m-%d"))
    path.write_text(source[:start] + block + source[stop:])
