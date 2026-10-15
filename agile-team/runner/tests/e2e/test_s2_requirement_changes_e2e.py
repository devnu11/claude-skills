"""s2 end to end: real git reads the trailers back, and ``requirements log`` prints them."""

from __future__ import annotations

import json
from pathlib import Path

import tomli_w
from agile_team import cli
from agile_team import config as config_mod
from agile_team.git_ops import Authored, Git

from ..conftest import PY_CONFIG, git

FOLDER = "docs/requirements"
CHANGED = "Requirement-Changed: REQ-003: tighten the limit"
ADDED = "Requirement-Changed: REQ-001: new requirement"


def step_commit(repo: Path, name: str, trailers: tuple[str, ...]) -> str:
    """Write ``name`` in the requirements folder and commit it the way a step does."""
    path = repo / FOLDER / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {path.stem}\n---\n{trailers}\n")
    authored = Authored("docs(arch): requirements", trailers=trailers)
    return Git(repo).commit_by([f"{FOLDER}/{name}"], authored)


def run_log(repo: Path, capsys) -> list[dict[str, str]]:
    assert cli.main(["--repo", str(repo), "requirements", "log"]) == 0
    return json.loads(capsys.readouterr().out)


def test_git_reads_both_trailers_back_and_keeps_the_co_author(configured):
    sha = step_commit(configured, "REQ-001.md", (ADDED, CHANGED))
    fmt = "--format=%(trailers:key=Requirement-Changed,valueonly)"
    out = git(configured, "log", "-1", fmt, sha)
    assert out.split("\n")[:2] == ["REQ-001: new requirement", "REQ-003: tighten the limit"]
    keys = git(configured, "log", "-1", "--format=%(trailers:only,keyonly)", sha)
    assert "Co-Authored-By" in keys


def test_requirements_log_prints_the_history_oldest_first(configured, capsys):
    first = step_commit(configured, "REQ-001.md", (ADDED,))
    second = step_commit(configured, "REQ-003.md", (CHANGED,))
    rows = run_log(configured, capsys)
    assert [(r["id"], r["reason"], r["sha"]) for r in rows] == [
        ("REQ-001", "new requirement", first),
        ("REQ-003", "tighten the limit", second),
    ]
    assert all(r["date"].startswith("20") for r in rows)


def test_requirements_log_is_an_empty_list_without_trailers(configured, capsys):
    assert run_log(configured, capsys) == []


def test_requirements_log_outside_a_repo_exits_one(tmp_path, capsys):
    (tmp_path / config_mod.CONFIG_NAME).write_text(tomli_w.dumps(PY_CONFIG))
    assert cli.main(["--repo", str(tmp_path), "requirements", "log"]) == 1
    assert "agile-team requirements log:" in capsys.readouterr().err
