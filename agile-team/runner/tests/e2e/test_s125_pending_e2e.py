"""s125 end to end: the step's changed lines from real git (P10) and the hidden-at-0 Pending caption (AC6)."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from agile_team import pending_tests, test_reports
from agile_team.git_ops import Git

from .. import dashboard_node
from ..conftest import git, set_git_identity

BASE_TEXT = "".join(f"line {n}\n" for n in range(1, 7))


def _repo(tmp_path: Path, config: tuple[str, str] | None) -> tuple[Path, str]:
    """A repo with a committed base: tests, a file with a space in its name, and a doomed file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    set_git_identity(repo)
    if config:
        git(repo, "config", *config)
    for name in ("test_old.py", "test with space.py", "test_gone.py", "test_pure.py"):
        (repo / name).write_text(BASE_TEXT)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def _change(repo: Path) -> None:
    (repo / "test_old.py").write_text(BASE_TEXT + "def test_added(): ...\n")  # added line 7
    (repo / "test with space.py").write_text(BASE_TEXT.replace("line 3", "edited 3"))
    (repo / "test_pure.py").write_text(
        "".join(f"line {n}\n" for n in (1, 2, 3, 5, 6))
    )  # line 4 deleted
    (repo / "test_gone.py").unlink()
    (repo / "test_new.py").write_text("def test_n(): ...\n")  # untracked


CONFIGS = [None, ("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true")]


@pytest.mark.parametrize("config", CONFIGS, ids=["plain", "noprefix", "mnemonic"])
def test_changed_lines_parse_real_git_output(
    tmp_path: Path, config: tuple[str, str] | None
) -> None:
    """P10/D1/D5: added, edited, deleted-line, untracked, deleted and spaced paths, whatever the diff config."""
    repo, base = _repo(tmp_path, config)
    _change(repo)
    changed = test_reports.ChangedFor(Git(repo))(base)
    assert set(changed) == {"test_old.py", "test with space.py", "test_pure.py", "test_new.py"}
    assert [list(r) for r in changed["test_old.py"]] == [[7]]
    assert [list(r) for r in changed["test with space.py"]] == [[3]]
    assert [list(r) for r in changed["test_pure.py"]] == [
        [3, 4]
    ]  # git says +3,0: the neighbours of the cut
    assert changed["test_new.py"] == (pending_tests.WHOLE,)  # untracked files count whole
    assert "test_gone.py" not in changed  # a deleted file owns no lines


# ---------------------------------------------------------------- AC6


pytestmark_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

CAPTION = """
const base = view.heartbeat.stages[0];
const variants = {
  zero: { ...base.tests, pending: 0 },
  gone: (({ pending, ...rest }) => rest)(base.tests),
  three: base.tests,
};
out.captions = {}; out.html = {};
for (const [name, tests] of Object.entries(variants)) {
  view.heartbeat.stages[0] = { ...base, tests };
  out.captions[name] = testsCaption(tests);
  ui.scope = "run";
  out.html[name] = flowHtml(flowModel(view));
}
"""


def _run() -> dict:
    snap = json.dumps(dashboard_node.fixture())
    driver = f"const view = {snap};\nconst out = {{}};\n(async () => {{\n{CAPTION}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


@pytestmark_node
def test_pending_caption_is_hidden_at_zero_and_without_the_key() -> None:
    """AC6: no `Pending` at 0 or with the key removed; the bar and `% complete` match the keyless row."""
    out = _run()
    assert out["captions"]["three"].endswith(" · 3 Pending")
    for name in ("zero", "gone"):
        assert "Pending" not in out["captions"][name]
        assert "Pending" not in out["html"][name]
    assert out["captions"]["zero"] == out["captions"]["gone"]
    assert out["html"]["zero"] == out["html"]["gone"]
    assert "complete" in out["html"]["gone"]
