"""s64/s94/s135 end to end: `story new` accepts only drafts naming configured [[environment]]s."""

from __future__ import annotations

from pathlib import Path

import tomli_w
from agile_team import cli, system
from agile_team import config as config_mod

from ..conftest import PY_CONFIG


def draft(repo: Path, *environments: str) -> str:
    items = "".join(
        f'  - id: AC{n}\n    text: "criterion {n}"\n    environment: {name}\n'
        for n, name in enumerate(environments, 1)
    )
    text = f'---\ntitle: "t"\nacceptance:\n{items}---\n\nAs a user, I want it.\n'
    system.write_text(repo / "draft.md", text)
    return str(repo / "draft.md")


def new(repo: Path, *environments: str) -> int:
    path = draft(repo, *environments)
    return cli.main(["--repo", str(repo), "story", "new", path, "--approved-by", "none"])


def queued(repo: Path) -> list[str]:
    folder = repo / ".team" / "run" / "liaison" / "stories"
    return [p.name for p in system.list_dir(folder)] if system.is_dir(folder) else []


def test_prose_environment_refused_with_names_and_nothing_saved(configured, capsys) -> None:
    """AC1: a prose environment is refused, valid names listed, nothing queued."""
    assert new(configured, "runner (guard)") != 0
    err = capsys.readouterr().err
    assert "not a configured [[environment]]" in err
    assert err.rstrip().endswith("use one of: cli")
    assert queued(configured) == []


def test_exact_name_accepted_and_case_refused(configured, capsys) -> None:
    """AC3: exact name queues; 'CLI' and 'cli ' are refused."""
    for bad in ("CLI", '"cli "'):
        assert new(configured, bad) != 0
    assert queued(configured) == []
    assert new(configured, "cli") == 0
    assert len(queued(configured)) == 1


def test_missing_environment_refused(configured, capsys) -> None:
    """s94 AC: an AC with no environment is refused."""
    assert new(configured) != 0
    assert queued(configured) == []


def test_no_environments_configured_says_so(configured, capsys) -> None:
    """AC4: refusal names no list when none are configured."""
    bare = {k: v for k, v in PY_CONFIG.items() if k != "environment"}
    system.write_text(configured / config_mod.CONFIG_NAME, tomli_w.dumps(bare))
    assert new(configured, "cli") != 0
    err = capsys.readouterr().err
    assert "configures no" in err and "use one of" not in err
