"""s109 end to end: charts group by model family; tooltips list the exact versions (node harness)."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

NOT_RECORDED = "version not recorded"


def _run(body: str, view: dict | None = None) -> dict:
    """Run `body` in the page with `view` (default: the fixture) bound; it fills `out`."""
    driver = f"const view = {json.dumps(view or dashboard_node.fixture())};\nconst out = {{}};\n(async () => {{\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def test_family_and_version_tables() -> None:
    """MF1, MF4: aliases and exact ids share a family; odd names stay themselves."""
    out = _run("""
    const models = ["opus", "claude-opus-5-5", "claude-3-5-sonnet-20241022", "sonnet[1m]", "haiku", "qwen3-coder", "opusplan", "unknown", "runner", null];
    out.family = models.map(familyOf);
    out.version = ["opus", "sonnet[1m]", "unknown", null, "claude-opus-5-5", "qwen3-coder"].map(versionOf);
    """)
    assert out["family"] == [
        "opus",
        "opus",
        "sonnet",
        "sonnet",
        "haiku",
        "qwen3-coder",
        "opusplan",
        "unknown",
        "runner",
        "unknown",
    ]
    assert out["version"] == [NOT_RECORDED] * 4 + ["claude-opus-5-5", "qwen3-coder"]


def test_time_by_model_alias_and_exact_id_make_one_row() -> None:
    """AC3 pin: `sonnet` (not recorded) + `claude-sonnet-5-5` = one row; an unknown model is its own row."""
    out = _run("""
    const step = (model, rec, s) => ({ role: "developer", story: "s1", model, recorded_model: rec, ended_at: 2, seconds: s, clock: "awake" });
    const v = { steps: [step("sonnet", null, 100), step("claude-sonnet-5-5", "claude-sonnet-5-5", 50), step("qwen3-coder", "qwen3-coder", 7)], events: [], roles: [] };
    const rows = timeBy(timePieces(v), "model");
    out.keys = Object.keys(rows).sort();
    out.sonnet = rows.sonnet.seconds; out.qwen = rows["qwen3-coder"].seconds;
    out.line = versionsLine(UNITS.time, rows.sonnet);
    out.qwenLine = versionsLine(UNITS.time, rows["qwen3-coder"]);
    """)
    assert out["keys"] == ["qwen3-coder", "sonnet"]
    assert (out["sonnet"], out["qwen"]) == (150, 7)
    first = out["line"].split("</span> ")[1]
    assert first.index(NOT_RECORDED) < first.index("claude-sonnet-5-5")  # larger share first
    assert out["qwenLine"].count("·") == 0


def test_tokens_and_spend_by_model_sum_one_row() -> None:
    """Ledger lines `opus` + `claude-opus-5-5` give one `opus` row with summed tokens and cost."""
    out = _run("""
    const line = (model, c) => ({ role: "x", story: "s1", model, cost_usd: c, turns: 0, tokens: { input: 10, output: 5, cache_read: 0, cache_creation: 0 } });
    const rows = totalsBy([line("opus", 1), line("claude-opus-5-5", 2)], "model");
    out.keys = Object.keys(rows); out.cost = rows.opus.cost; out.input = rows.opus.input;
    out.versions = Object.keys(rows.opus.versions).sort();
    out.line = versionsLine(UNITS.usd, rows.opus);
    const byRole = totalsBy([line("opus", 1), line("claude-opus-5-5", 2)], "role");
    out.roleLine = versionsLine(UNITS.usd, { ...byRole.x, versions: undefined });
    """)
    assert out["keys"] == ["opus"]
    assert (out["cost"], out["input"]) == (3, 20)
    assert out["versions"] == sorted([NOT_RECORDED, "claude-opus-5-5"])
    assert "claude-opus-5-5 67%" in out["line"] and f"{NOT_RECORDED} 33%" in out["line"]
    assert out["roleLine"] == ""


def test_role_grouping_has_no_versions_line_and_runner_row_none() -> None:
    """Only the Model grouping adds the line; the runner row has no versions."""
    out = _run("""
    ui.unit = "time"; ui.group = "role"; out.role = barRows(view).map((r) => r.more);
    ui.group = "story"; out.story = barRows(view).map((r) => r.more);
    ui.group = "model"; const rows = barRows(view);
    out.runner = rows.filter((r) => r.role === "runner").map((r) => r.more);
    out.keys = rows.map((r) => r.role);
    """)
    assert set(out["role"]) == {""} and set(out["story"]) == {""}
    assert out["runner"] in ([], [""])
    assert len(out["keys"]) == len(set(out["keys"]))
    assert not {"claude-opus-5-5", "claude-sonnet-5-5"} & set(out["keys"])


def test_po_turns_count_under_the_family_as_not_recorded() -> None:
    """PO configured `opus`: its turns land in `opus` with version not recorded."""
    out = _run("""
    const v = { steps: [], roles: [{ name: "product-owner", model: "opus", provider: "anthropic" }], events: [{ kind: "po-turn", data: {} }] };
    const rows = timeBy(timePieces(v), "model");
    out.keys = Object.keys(rows); out.versions = Object.keys(rows.opus?.versions ?? {});
    """)
    assert out["keys"] == ["opus"] and out["versions"] == [NOT_RECORDED]


def test_flow_box_shows_family_and_local_keeps_provider() -> None:
    """MF7: a role on `claude-sonnet-5-5` shows `sonnet`; a local `qwen3-coder` keeps its provider."""
    out = _run("""
    const v = JSON.parse(JSON.stringify(view));
    v.roles.find((r) => r.name === "unit-tester").model = "claude-sonnet-5-5";
    const dev = v.roles.find((r) => r.name === "architect");
    dev.model = "qwen3-coder"; dev.provider = "ollama";
    ui.scope = "run"; out.src = flowSource(v);
    """)
    src = out["src"]
    assert "claude-sonnet-5-5" not in src
    assert "sonnet" in src and "qwen3-coder · ollama" in src
