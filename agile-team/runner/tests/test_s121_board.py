"""s121: the Board holds the current sprint only; the empty Requirements tab says why.

Static checks of the page source, the snapshot key and the fixture. Behaviour checks
(rendering under node) live in the e2e suite.
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from agile_team import system
from agile_team.dashboard import snapshot

from .test_snapshot import FIXTURE_TEXT, build, make_config

PAGE = system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))
EMPTY_LINE = (
    "No requirement files yet. They live in <code>${esc(dir)}/REQ-NNN.md</code>; "
    "story s1 introduces them."
)


def function_body(name: str) -> str:
    """Source of the page function `name`, up to the next top-level closing brace."""
    start = PAGE.index(f"function {name}(")
    return PAGE[start : PAGE.index("\n}\n", start)]


def test_board_has_no_backlog_column() -> None:
    body = function_body("boardColumns")
    assert '"backlog"' not in body
    assert '"Backlog"' not in body


def test_board_columns_are_pipeline_steps_then_done() -> None:
    body = function_body("boardColumns")
    assert "view.pipeline" in body
    assert '"done", "Done"' in body


def test_board_membership_is_current_sprint_not_cancelled() -> None:
    body = PAGE[PAGE.index("onBoard") :]
    assert "s.sprint === view.run.sprint" in body
    assert 'status !== "cancelled"' in body
    assert "onBoard(view" in function_body("boardColumns")


def test_dead_backlog_column_css_is_gone() -> None:
    assert not re.search(r"\.col\.backlog", PAGE)


def test_badge_comes_from_board_columns() -> None:
    assert "boardColumns(view)" in function_body("boardStories")
    assert "boardStories(view).length" in function_body("renderTabs")
    assert "view.stories.length" not in function_body("renderTabs")


def test_empty_requirements_message_is_the_humans_line() -> None:
    assert "REQ_EMPTY" not in PAGE
    assert EMPTY_LINE in function_body("reqEmpty")
    assert "docs/requirements" in function_body("reqEmpty")
    assert "view.run.requirements_dir" in function_body("reqEmpty")


def test_empty_requirements_renders_through_req_empty() -> None:
    assert "reqEmpty(view)" in function_body("renderRequirements")


def test_snapshot_run_carries_requirements_dir_from_docs_dir(scratch: Path) -> None:
    team = {"docs_dir": "handbook", "budget_usd": 20.0, "manager_every_pct": 25}
    config = make_config(scratch / "repo", team=team)
    assert build(config, scratch)["run"]["requirements_dir"] == "handbook/requirements"


def test_snapshot_requirements_dir_is_the_last_run_key(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    assert list(build(config, scratch)["run"])[-1] == "requirements_dir"
    assert snapshot.REQUIREMENTS_DIR  # imported from config


def test_fixture_run_has_requirements_dir_after_backlog() -> None:
    run: dict[str, Any] = json.loads(FIXTURE_TEXT)["run"]
    keys = list(run)
    assert run["requirements_dir"] == "docs/requirements"
    assert keys.index("requirements_dir") == keys.index("backlog") + 1
