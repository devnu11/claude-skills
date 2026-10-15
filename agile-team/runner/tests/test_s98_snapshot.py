"""``[dashboard] collapse_under_s`` and the snapshot's ``tools`` section (s98, TC15, TC18)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import tool_calls as tc
from agile_team.dashboard import snapshot

from .clock import about
from .test_snapshot import FIXTURE_TEXT, build, make_config, write_jsonl


def test_collapse_under_s_defaults_to_a_tenth(scratch: Path) -> None:
    assert cfg.from_raw(scratch, {}).dashboard.collapse_under_s == 0.1


@pytest.mark.parametrize("value", [0, 0.0, 2, 0.25])
def test_a_non_negative_number_is_accepted(scratch: Path, value: float) -> None:
    raw = {"dashboard": {"collapse_under_s": value}}
    assert cfg.from_raw(scratch, raw).dashboard.collapse_under_s == value


@pytest.mark.parametrize("value", [True, False, "1", -1, -0.1, None])
def test_a_bad_collapse_under_s_is_refused(scratch: Path, value: Any) -> None:
    with pytest.raises(cfg.ConfigError) as err:
        cfg.from_raw(scratch, {"dashboard": {"collapse_under_s": value}})
    assert str(err.value) == cfg.DASHBOARD_COLLAPSE
    assert cfg.DASHBOARD_COLLAPSE == (
        "[dashboard] collapse_under_s must be a number of seconds, 0 or more"
    )


def span(seconds: float, at: float, tool: str = "Read", role: str = "developer") -> dict[str, Any]:
    return {
        "role": role, "story": "s1", "step": "implement", "opened_at": 1.0,
        "tool": tool, "seconds": seconds, "at": at,
    }  # fmt: skip


def test_the_snapshot_has_tools_after_steps(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    keys = list(build(config, scratch))
    assert keys.index("tools") == keys.index("steps") + 1
    assert build(config, scratch)["tools"] == []


def test_the_snapshot_gathers_spans_under_the_configured_limit(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    rows = [span(0.01, 1.0), span(0.02, 2.0, "Bash"), span(5.0, 3.0)]
    write_jsonl(config.run_dir / tc.TOOLS, rows)
    (group,) = build(config, scratch)["tools"]
    assert group["misc"] == {"count": 2, "seconds": about(0.03), "tools": {"Read": 1, "Bash": 1}}
    assert [c["seconds"] for c in group["calls"]] == [5.0]


def test_a_zero_limit_ships_every_call(scratch: Path) -> None:
    config = make_config(scratch / "repo", dashboard={"collapse_under_s": 0})
    write_jsonl(config.run_dir / tc.TOOLS, [span(0.01, 1.0), span(0.02, 2.0)])
    (group,) = build(config, scratch)["tools"]
    assert group["misc"]["count"] == 0 and len(group["calls"]) == 2


def test_tools_jsonl_is_watched() -> None:
    assert tc.TOOLS in snapshot.RUN_FILES


def test_the_tools_file_is_read_by_its_tail() -> None:
    assert snapshot.TOOLS_TAIL_BYTES == 4_194_304


def test_the_fixture_has_tools_in_the_group_shape() -> None:
    fixture = json.loads(FIXTURE_TEXT)
    assert list(fixture).index("tools") == list(fixture).index("steps") + 1
    for group in fixture["tools"]:
        assert {"role", "story", "step", "opened_at", "calls", "misc"} <= set(group)
        assert set(group["misc"]) == {"count", "seconds", "tools"}
