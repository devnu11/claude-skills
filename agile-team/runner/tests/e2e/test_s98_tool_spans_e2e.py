"""s98 end to end: a real Pulse records tool calls to tools.jsonl; the dashboard groups them."""

from __future__ import annotations

import json
import time
from pathlib import Path

from agile_team import live
from agile_team.dashboard import tool_groups
from agile_team.providers import Billing
from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage


def _assistant(*uses: ToolUseBlock) -> AssistantMessage:
    return AssistantMessage(content=list(uses), model="m")


def _results(*pairs: tuple[str, str, bool]) -> UserMessage:
    return UserMessage(
        content=[ToolResultBlock(tool_use_id=i, content=c, is_error=e) for i, c, e in pairs]
    )


def _run(run_dir: Path, role: str) -> list[dict]:
    pulse = live.Pulse(run_dir, 20.0)
    meter = pulse.open(live.Who(role, "s98", "developer", "m", Billing.FREE))
    secret = "GH_TOKEN=abc123 curl x"
    pulse.take(
        meter,
        _assistant(
            ToolUseBlock("a", "Bash", {"command": secret, "description": "fetch it"}),
            ToolUseBlock("b", "Read", {"file_path": "/x/y.py"}),
            ToolUseBlock("c", "mcp__team__run_role", {"role": "developer"}),
            ToolUseBlock("d", "Bash", {"command": "sleep 99"}),
        ),
    )
    time.sleep(0.05)
    pulse.take(meter, _results(("a", "ok", False), ("b", "Command timed out after 2m", True)))
    pulse.close(meter)
    lines = (run_dir / "tools.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_spans_written_with_labels_masking_and_unfinished(tmp_path: Path) -> None:
    """AC1-AC3: one span per call, labels, masked detail, open calls unfinished."""
    rows = {r["tool_use_id"]: r for r in _run(tmp_path, "developer")}
    assert set(rows) == {"a", "b", "c", "d"}
    assert rows["a"]["label"] == "Dev: fetch it" and rows["a"]["status"] == "ok"
    assert "abc123" not in json.dumps(rows["a"]) and "GH_TOKEN=***" in rows["a"]["detail"]
    assert rows["b"]["label"] == "Dev: Read" and rows["b"]["status"] == "timeout"
    assert rows["c"]["label"] == "po.run_role" and rows["c"]["status"] == "unfinished"
    assert rows["d"]["status"] == "unfinished" and rows["a"]["seconds"] >= 0.04


def test_dashboard_gathers_negligible_calls_keeping_totals(tmp_path: Path) -> None:
    """AC6: a high limit gathers all into misc; a zero limit gathers none; totals agree."""
    rows = _run(tmp_path, "developer")
    total = sum(r["seconds"] for r in rows)
    everything = tool_groups.groups(rows, 1000.0)[0]
    assert everything["calls"] == [] and everything["misc"]["count"] == 4
    assert abs(everything["misc"]["seconds"] - total) < 1e-6
    none = tool_groups.groups(rows, 0.0)[0]
    assert none["misc"]["count"] == 0 and len(none["calls"]) == 4
