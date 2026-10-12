"""s75 end to end: DevOps stays exempt from the suite deny and its role file scopes its runs."""

from __future__ import annotations

from pathlib import Path

import agile_team

from .test_suite_denial_e2e import ask, reason

DEVOPS = Path(agile_team.__file__).parent / "roles" / "devops.md"


def test_devops_role_file_scopes_test_runs() -> None:
    text = " ".join(DEVOPS.read_text().split())
    assert "Run only what proves your change, normally one named test" in text
    assert "Never run the full suite or a coverage run" in text


def test_devops_is_still_exempt_from_the_deny(tmp_path: Path) -> None:
    assert reason(ask("devops", "pytest --cov=agile_team", tmp_path)) is None
