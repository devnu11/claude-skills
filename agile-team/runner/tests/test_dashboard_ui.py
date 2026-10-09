"""Static checks of the dashboard page (s5, rules U1-U14), stdlib only."""

from __future__ import annotations

import re
import shutil
import subprocess
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path

import pytest

MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"
URL_RE = re.compile(r"https?://[^\"'\s)]+")


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


def _resource():  # type: ignore[no-untyped-def]
    return resources.files("agile_team.dashboard").joinpath("index.html")


@pytest.fixture(scope="module")
def page() -> str:
    return _resource().read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parts(page: str) -> PageParts:
    parsed = PageParts()
    parsed.feed(page)
    return parsed


@pytest.fixture(scope="module")
def script(parts: PageParts) -> str:
    return "\n".join(parts.scripts)


# ----- 1. packaged ---------------------------------------------------------------


def test_index_is_packaged() -> None:
    assert _resource().is_file()


# ----- 2. routes, boot, reconnect (U1, U2) -------------------------------------


@pytest.mark.parametrize(
    "needle",
    ['fetch("api/snapshot")', 'new EventSource("api/stream")', "EventSource.CLOSED"],
)
def test_script_uses_snapshot_and_stream(script: str, needle: str) -> None:
    assert needle in script


def test_reconnect_backoff_is_scheduled(script: str) -> None:
    assert "setTimeout(connectLive" in script
    assert "reconnecting…" in script


# ----- 3. one element per tab --------------------------------------------------


@pytest.mark.parametrize(
    "element_id",
    [
        "tab-flow", "tab-board", "tab-tokens", "tab-questions", "tab-requirements",
        "tabs", "flow", "timeline", "board", "spend", "mix",
        "q-open", "q-raised", "matrix", "reqs",
    ],
)  # fmt: skip
def test_page_has_element(parts: PageParts, element_id: str) -> None:
    assert element_id in parts.ids


# ----- 4. pinned Mermaid only (U6, U14) ----------------------------------------


def test_outside_urls_are_only_the_pinned_mermaid_module(page: str) -> None:
    outside = [u for u in URL_RE.findall(page) if not u.startswith("http://www.w3.org/")]
    assert outside
    assert set(outside) == {MERMAID_URL}


def test_mermaid_version_is_pinned(page: str) -> None:
    versions = set(re.findall(r"mermaid@([^/\"'\s]+)", page))
    assert versions == {"11.4.1"}


def test_no_external_script_tag(parts: PageParts) -> None:
    assert parts.script_srcs == []


def test_mermaid_is_loaded_lazily_with_strict_security(script: str) -> None:
    assert re.search(r"\bimport\(", script)
    assert "startOnLoad" in script
    assert "securityLevel" in script
    assert "strict" in script


# ----- 5. themes (U13) -----------------------------------------------------------


@pytest.mark.parametrize("needle", ["prefers-color-scheme: dark", "data-theme"])
def test_theme_hooks(page: str, needle: str) -> None:
    assert needle in page


# ----- 6. empty-state copy (U4, U5) --------------------------------------------


def test_requirements_empty_state_copy(page: str) -> None:
    assert "No requirements yet" in page


def test_empty_rows_use_empty_paragraph(page: str) -> None:
    assert 'class="empty"' in page


def test_snapshot_is_normalized_before_render(script: str) -> None:
    assert re.search(r"\bnormalize\(", script)
    assert "manager_every_pct" in script


# ----- Flow is Mermaid (U6-U8) -------------------------------------------------


@pytest.mark.parametrize("name", ["flowSource", "mmdText", "renderFlowTab", "safely"])
def test_new_functions_exist(script: str, name: str) -> None:
    assert re.search(rf"function\s+{name}\s*\(|{name}\s*=", script)


@pytest.mark.parametrize(
    "needle",
    ["flowchart TB", "linkStyle", "classDef active", "classDef idle", "#quot;", "#lt;", "#gt;"],
)
def test_flow_source_vocabulary(script: str, needle: str) -> None:
    assert needle in script


def test_flow_failure_fallback_copy(script: str) -> None:
    assert "Flowchart unavailable" in script


@pytest.mark.parametrize(
    "removed",
    ["ringPositions", "PULSE_PATH", "flowEdges", "edgePath", "message in flight"],
)
def test_hand_drawn_ring_is_gone(page: str, removed: str) -> None:
    assert removed not in page


# ----- Tokens grouping (U11) and questions (U12) ------------------------------


@pytest.mark.parametrize("needle", ["data-group", "aria-pressed"])
def test_tokens_group_control(page: str, needle: str) -> None:
    assert needle in page


def test_grouping_without_story_label(script: str) -> None:
    assert "(no story)" in script


def test_questions_say_who_raised_them(script: str) -> None:
    assert "raised by" in script


# ----- 7. JS syntax (optional) -------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_inline_scripts_parse(parts: PageParts, tmp_path: Path) -> None:
    assert parts.scripts
    for number, body in enumerate(parts.scripts):
        target = tmp_path / f"x{number}.js"
        target.write_text(body, encoding="utf-8")
        done = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
