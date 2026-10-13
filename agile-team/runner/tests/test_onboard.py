"""init phase A: detection, config writing, reconfigure, gitignore, charter."""

import json
import tomllib
from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import onboard, system

from .fake_system import FAKE_HEAD, Done, FakeSystem

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
def test_detect_fixture_repos(repo: Path, marker, content, preset, kind) -> None:
    system.write_text(repo / marker, content)
    assert onboard.detect(repo, PRESETS) == preset
    assert onboard.suggest_kind(repo, PRESETS[preset]) == kind


def test_detect_nothing(repo: Path) -> None:
    assert onboard.detect(repo, PRESETS) is None


def test_presets_validate(repo: Path) -> None:
    for name, preset in PRESETS.items():
        data = onboard.build_config(preset, onboard.Answers(name, preset["environment_kind"]))
        known = cfg.Known(set(), {"package"})
        assert cfg.validate(cfg.from_raw(repo, data), known) == []


def test_build_config_web_and_script() -> None:
    web = onboard.build_config(PRESETS["node"], onboard.Answers("node", "web", url="http://x"))
    assert web["environment"][0]["url"] == "http://x"
    script = onboard.build_config(PRESETS["python"], onboard.Answers("python", "script"))
    assert script["environment"][0]["bin"] == ["venv/bin"]


def test_merge_keep() -> None:
    merged = onboard.merge_keep(
        {"a": {"x": 1}, "b": 2, "l": [1]}, {"a": {"x": 9, "y": 3}, "l": [2]}
    )
    assert merged == {"a": {"x": 1, "y": 3}, "b": 2, "l": [1]}


def test_gitignore_lines() -> None:
    assert onboard.gitignore_lines("committed") == [onboard.RUN_IGNORE]
    assert "!.team/roles/" in onboard.gitignore_lines("ignored")


def test_ensure_lines(repo: Path) -> None:
    f = repo / ".gitignore"
    system.write_text(f, "node_modules")
    onboard.ensure_lines(f, [".team/run/"])
    onboard.ensure_lines(f, [".team/run/"])
    assert system.read_text(f) == "node_modules\n# agile-team\n.team/run/\n"
    new = repo / "new"
    onboard.ensure_lines(new, ["a"])
    assert system.read_text(new) == "# agile-team\na\n"


def changes(fake: FakeSystem, status: str = "?? .agile-team.toml\0") -> None:
    """Script git: ``status`` shows ``status``; no path is ignored; commits succeed."""
    fake.reply(("git", "status"), Done(0, status))
    fake.reply(("git", "check-ignore"), Done(1))


def git_calls(fake: FakeSystem, word: str) -> list[tuple[str, ...]]:
    return [c.argv for c in fake.commands if word in c.argv]


def test_onboard_writes_and_commits(repo: Path, fake: FakeSystem) -> None:
    system.write_text(repo / "pyproject.toml", "[project]\nname='x'\n")
    changes(fake)
    sha = onboard.onboard(repo, onboard.Answers("python", "package", budget_usd=5))
    assert sha == FAKE_HEAD
    (commit,) = git_calls(fake, "commit")
    assert onboard.COMMIT_MESSAGE in commit[-1]
    assert system.is_file(repo / onboard.CHARTER)
    assert system.is_file(repo / ".team/roles/_shared.md")
    assert system.is_file(repo / ".team/roles/architect.md")
    assert cfg.load(repo).team.budget_usd == 5
    (add,) = git_calls(fake, "add")
    assert {cfg.CONFIG_NAME, ".gitignore", onboard.CHARTER, ".team/roles"} <= set(add)
    with pytest.raises(FileExistsError):
        onboard.onboard(repo, onboard.Answers("python", "package"))


def test_reconfigure_keeps_edits(repo: Path, fake: FakeSystem) -> None:
    changes(fake)
    onboard.onboard(repo, onboard.Answers("python", "package"))
    path = repo / cfg.CONFIG_NAME
    data = tomllib.loads(system.read_text(path))
    data["toolchain"]["test"] = "make test"
    del data["gates"]["round_cap"]
    import tomli_w

    system.write_text(path, tomli_w.dumps(data))
    system.write_text(repo / onboard.CHARTER, "my charter")
    onboard.onboard(repo, onboard.Answers("python", "package", budget_usd=99, mode=RECONFIGURE))
    c = cfg.load(repo)
    assert c.toolchain.commands["test"] == "make test"
    assert c.gates.round_cap == 3
    assert c.team.budget_usd == 20.0  # existing value kept
    assert system.read_text(repo / onboard.CHARTER) == "my charter"


def test_reconfigure_no_change(repo: Path, fake: FakeSystem) -> None:
    changes(fake)
    onboard.onboard(repo, onboard.Answers("python", "package"))
    changes(fake, status="")
    assert onboard.onboard(repo, onboard.Answers("python", "package", mode=RECONFIGURE)) is None


def test_ignored_artifacts_keep_roles_tracked(repo: Path, fake: FakeSystem) -> None:
    changes(fake)
    onboard.onboard(repo, onboard.Answers("python", "package", artifacts="ignored"))
    assert "!.team/roles/" in system.read_text(repo / ".gitignore")
    (add,) = git_calls(fake, "add")
    assert onboard.CHARTER in add and ".team/roles" in add


def test_unknown_preset(repo: Path) -> None:
    with pytest.raises(ValueError, match="unknown preset"):
        onboard.onboard(repo, onboard.Answers("cobol", "package"))
