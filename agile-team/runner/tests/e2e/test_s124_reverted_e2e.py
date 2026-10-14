"""s124 end to end: the "reverted (n×)" pill on Board and Backlog; real git for revert_all."""
# ruff: noqa: E501, RUF001, RUF002

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from agile_team import state as state_mod
from agile_team.git_ops import Git, GitError
from agile_team.revert_log import RevertEntry
from agile_team.state import RunState, StoryState

from ..test_snapshot import build, make_config
from .test_s121_board_e2e import BOARD_BODY, _run

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

EDITS = """
view.run.sprint = 2;
const base = view.stories[0];
const mk = (id, reverts) => ({ ...base, id, sprint: 2, status: "active", step: "design", title: "t" + id, held: null, hold: null, reverts, wait: null });
view.stories = [mk("a", 1), mk("b", 0), mk("c", 3)];
view.requirements = [];
"""


@needs_node
def test_board_cards_show_the_revert_count_and_none_when_zero() -> None:
    """AC2: card a reads reverted (1×), c reads (3×); b shows no pill."""
    out = _run(
        BOARD_BODY + "\nout.cards = els['#board'].innerHTML.split('class=\"story ').slice(1);",
        EDITS,
    )
    a, b, c = out["cards"][:3]
    assert "reverted (1×)" in a and "reverted (3×)" in c
    assert "reverted" not in b


@needs_node
def test_backlog_rows_show_the_revert_count_and_none_when_zero() -> None:
    """AC2: backlogRow carries the pill for a reverted story only."""
    out = _run(
        EDITS
        + """
    out.rows = view.stories.map((s) => backlogRow(s, null, 3, view));
    """
    )
    a, b, c = out["rows"]
    assert "reverted (1×)" in a and "reverted (3×)" in c
    assert "reverted" not in b


def test_snapshot_counts_a_story_reverts(tmp_path: Path) -> None:
    """AC2: one RevertEntry gives "reverts": 1 in the snapshot."""
    config = make_config(tmp_path / "repo")
    entry = RevertEntry("2026-01-01", 1, "why", ["abc"], "def")
    story = StoryState("s1", "One", "design", commit="abc", sprint=1, reverted=[entry])
    state_mod.save(config.run_dir, RunState(stories={"s1": story}, sprint=1))
    (got,) = build(config, tmp_path)["stories"]
    assert got["reverts"] == 1


# ---------------------------------------------------------------- real git


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _commit(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _commit(tmp_path, "base.txt", "base\n", "base")
    return tmp_path


def test_revert_all_undoes_one_story_in_one_commit_and_keeps_the_other(repo: Path) -> None:
    """AC2: feat + fixup! around another story's commit; one new commit, only s1 undone."""
    s1a = _commit(repo, "one.txt", "one\n", "feat(s1): one")
    _commit(repo, "two.txt", "two\n", "feat(s2): two")
    s1b = _commit(repo, "one.txt", "one\nmore\n", "fixup! feat(s1): one")
    git, before = Git(repo), _git(repo, "rev-parse", "HEAD")
    log = git.log_from(s1a)
    assert [s for s, _ in log][0::2] == [s1a, s1b] and len(log) == 3
    new = git.revert_all([s1b, s1a], "revert(s1): One")
    assert _git(repo, "rev-list", "--count", f"{before}..HEAD") == "1"
    assert _git(repo, "rev-parse", "HEAD") == new
    assert not (repo / "one.txt").exists() and (repo / "two.txt").read_text() == "two\n"
    assert _git(repo, "log", "-1", "--format=%s") == "revert(s1): One"


@pytest.mark.parametrize("both", [False, True])
def test_a_conflicting_revert_aborts_and_leaves_the_tree_clean(repo: Path, both: bool) -> None:
    """AC2: a later edit of the same lines: GitError names the path, HEAD unchanged, tree clean."""
    first = _commit(repo, "f.txt", "a\n", "feat(s1): a")
    second = _commit(repo, "g.txt", "x\n", "feat(s1): x")
    _commit(repo, "f.txt", "changed later\n", "feat(s2): edit")
    git, before = Git(repo), _git(repo, "rev-parse", "HEAD")
    shas = [second, first] if both else [first]
    with pytest.raises(GitError, match=r"f\.txt"):
        git.revert_all(shas, "revert(s1): One")
    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "status", "--porcelain") == ""
