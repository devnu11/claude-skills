# ruff: noqa: E501  (embedded JavaScript lines)
"""Run the dashboard page's functions under node, without a browser (s44, U2).

``run_page(driver, now)`` stubs the browser globals, freezes the page's clock
(``Date.now``) at ``now`` seconds (default: the fixture's ``generated_at``),
appends the page's inline script and a driver snippet, runs ``node`` and
returns the JSON the driver logs.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path
from typing import Any

from . import clock

NODE_TIMEOUT_S = 30
FIXTURE = "fixtures/snapshot.json"

PRELUDE = """\
globalThis.AGILE_TEAM_NO_BOOT = true;
globalThis.location = { search: "", protocol: "http:", hash: "" };
// Top-level wiring calls $(...).addEventListener, so lookups return an inert element.
const inert = () => new Proxy(function () {}, { get: (_, k) => (k === "style" ? {} : inert()), apply: () => inert() });
globalThis.document = {
  title: "", addEventListener() {},
  querySelector: inert, querySelectorAll: () => [], getElementById: inert,
  documentElement: {},
};
globalThis.window = globalThis;
globalThis.isSecureContext = true;
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
globalThis.matchMedia = () => ({ matches: false });
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)); },
};
globalThis.made = [];
globalThis.Notification = class { static permission = "default"; constructor(...a) { globalThis.made.push(a); } };
globalThis.fetched = [];
globalThis.fetch = (url) => { globalThis.fetched.push(String(url)); return Promise.reject(new Error("no network")); };
"""


class PageParts(HTMLParser):
    """Collects element ids and inline script bodies."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.scripts: list[str] = []
        self.script_srcs: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"] or "")
        if tag == "script":
            self._in_script = True
            self.scripts.append("")
            if attributes.get("src"):
                self.script_srcs.append(attributes["src"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.scripts[-1] += data


def dashboard_file(name: str) -> str:
    """Text of a file packaged with the dashboard."""
    return resources.files("agile_team.dashboard").joinpath(name).read_text(encoding="utf-8")


def fixture() -> dict[str, Any]:
    """The snapshot contract fixture, parsed."""
    return json.loads(dashboard_file(FIXTURE))


def page_script() -> str:
    """The page's inline scripts, joined."""
    parsed = PageParts()
    parsed.feed(dashboard_file("index.html"))
    return "\n".join(parsed.scripts)


def run_page(driver: str, now: float | None = None) -> Any:
    """Run `driver` after the page's script under node, the page's clock frozen at `now`."""
    pinned = fixture()["generated_at"] if now is None else now
    source = PRELUDE + clock.page_clock(pinned) + page_script() + "\n" + driver
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.js"
        path.write_text(source, encoding="utf-8")
        done = subprocess.run(
            ["node", str(path)], capture_output=True, text=True, timeout=NODE_TIMEOUT_S
        )
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)
