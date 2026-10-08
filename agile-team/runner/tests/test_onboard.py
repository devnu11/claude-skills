"""init phase A: detection, config writing, reconfigure, gitignore, charter."""

import json
import tomllib
from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import onboard

from .conftest import git

PRESETS = onboard.load_presets()
RECONFIGURE = onboard.WriteMode.RECONFIGURE


@pytest.mark.parametrize(
    ("marker", "content", "preset", "kind"),
    [
        ("pyproject.toml", "[project]\nname='x'\n", "python", "package"),
        ("package.json", json.dumps({"dependencies": {"left-pad": "1"}}), "node", "package"),
        ("package.json", json.dumps({"devDependencies": {"vite": "5"}}), "node", "web"),
        ("Cargo.toml", "[package]\nname='x'\n", "rust", "package"),
    ],
)
def test_detect_fixture_repos(tmp_path: Path, marker, content, preset, kind) -> None:
    (tmp_path / marker).write_text(content)
    assert onboard.detect(tmp_path, PRESETS) == preset
    assert onboard.suggest_kind(tmp_path, PRESETS[preset]) == kind


def test_detect_nothing(tmp_path: Path) -> None:
    assert onboard.detect(tmp_path, PRESETS) is None


def test_presets_validate(tmp_path: Path) -> None:
    for name, preset in PRESETS.items():
        data = onboard.build_config(preset, onboard.Answers(name, preset["delivery"]))
        known = cfg.Known(set(), {"package"})
        assert cfg.validate(cfg.from_raw(tmp_path, data), known) == []


def test_build_config_web_and_script() -> None:
    web = onboard.build_config(PRESETS["node"], onboard.Answers("node", "web", url="http://x"))
    assert web["delivery"][0]["url"] == "http://x"
    script = onboard.build_config(PRESETS["python"], onboard.Answers("python", "script"))
    assert script["delivery"][0]["bin"] == ["venv/bin"]


def test_merge_keep() -> None:
    merged = onboard.merge_keep(
        {"a": {"x": 1}, "b": 2, "l": [1]}, {"a": {"x": 9, "y": 3}, "l": [2]}
    )
    assert merged == {"a": {"x": 1, "y": 3}, "b": 2, "l": [1]}


def test_gitignore_lines() -> None:
    assert onboard.gitignore_lines("committed") == [onboard.RUN_IGNORE]
    assert "!.team/roles/" in onboard.gitignore_lines("ignored")


def test_ensure_lines(tmp_path: Path) -> None:
    f = tmp_path / ".gitignore"
    f.write_text("node_modules")
    onboard.ensure_lines(f, [".team/run/"])
    onboard.ensure_lines(f, [".team/run/"])
    assert f.read_text() == "node_modules\n# agile-team\n.team/run/\n"
    new = tmp_path / "new"
    onboard.ensure_lines(new, ["a"])
    assert new.read_text() == "# agile-team\na\n"


def test_onboard_writes_and_commits(repo: Path) -> None:
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "py")
    sha = onboard.onboard(repo, onboard.Answers("python", "package", budget_usd=5))
    assert sha
    assert git(repo, "log", "-1", "--format=%s").strip() == onboard.COMMIT_MESSAGE
    assert (repo / onboard.CHARTER).is_file()
    assert (repo / ".team/roles/_shared.md").is_file() and (
        repo / ".team/roles/architect.md"
    ).is_file()
    assert cfg.load(repo).team.budget_usd == 5
    assert git(repo, "status", "--porcelain") == ""
    with pytest.raises(FileExistsError):
        onboard.onboard(repo, onboard.Answers("python", "package"))


def test_reconfigure_keeps_edits(repo: Path) -> None:
    onboard.onboard(repo, onboard.Answers("python", "package"))
    path = repo / cfg.CONFIG_NAME
    data = tomllib.loads(path.read_text())
    data["toolchain"]["test"] = "make test"
    del data["gates"]["round_cap"]
    import tomli_w

    path.write_text(tomli_w.dumps(data))
    (repo / onboard.CHARTER).write_text("my charter")
    git(repo, "commit", "-qam", "edit")
    onboard.onboard(repo, onboard.Answers("python", "package", budget_usd=99, mode=RECONFIGURE))
    c = cfg.load(repo)
    assert c.toolchain.commands["test"] == "make test"
    assert c.gates.round_cap == 3
    assert c.team.budget_usd == 20.0  # existing value kept
    assert (repo / onboard.CHARTER).read_text() == "my charter"


def test_reconfigure_no_change(repo: Path) -> None:
    onboard.onboard(repo, onboard.Answers("python", "package"))
    assert onboard.onboard(repo, onboard.Answers("python", "package", mode=RECONFIGURE)) is None


def test_ignored_artifacts_keep_roles_tracked(repo: Path) -> None:
    onboard.onboard(repo, onboard.Answers("python", "package", artifacts="ignored"))
    tracked = git(repo, "ls-files").split()
    assert onboard.CHARTER in tracked and ".team/roles/developer.md" in tracked


def test_unknown_preset(repo: Path) -> None:
    with pytest.raises(ValueError, match="unknown preset"):
        onboard.onboard(repo, onboard.Answers("cobol", "package"))
