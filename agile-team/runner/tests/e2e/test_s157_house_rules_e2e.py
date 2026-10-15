"""s157 end to end: the repo's own `.agile-team.toml` runs the real house-rules in the team's gates.

A scratch git repo gets the real house-rules project (symlinked), the real toolchain, file
commands and role sections from the repo's `.agile-team.toml`. Only the ruff links are dropped,
because the scratch repo has no Python project to run ruff in.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from agile_team import commands, config, fullcheck, guard, owners, roles

REPO = Path(__file__).resolve().parents[4]
BAD = "agile-team/runner/agile_team/bad.py"
WARN = "unattended/runner/unattended/warn.py"
BASELINE = ".house-rules-baseline.json"
ACCEPT = "uv run --frozen --quiet --project house-rules/runner house-rules baseline --accept-new"
PYTHON_ROLES = [
    "developer",
    "developer-cli",
    "developer-api",
    "developer-db",
    "developer-gui",
    "unit-tester",
    "integration-tester",
    "devops",
]
FAILING = '"""m."""\nprint("x")\n'
CLEAN = '"""m."""\n'
WARNING_ONLY = '"""m."""\n\n\ndef read(x, y, z):\n    """d."""\n    return x\n'
EXCLUDE = 'exclude = ["house-rules/**", "**/.venv/**", ".team/run/**"]\n'


def real_raw() -> dict:
    """The repo's own `.agile-team.toml`, parsed."""
    return tomllib.loads((REPO / ".agile-team.toml").read_text())


def git(repo: Path, *args: str) -> str:
    """Run git in the scratch repo; return its output."""
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=True).stdout


def without_ruff(command: str) -> str:
    """The command with its ruff links dropped (the scratch repo has no ruff project)."""
    links = re.split(r"\s*(?:&&|;)\s*", command)
    return " && ".join(link for link in links if " ruff " not in link)


def write(repo: Path, rel: str, text: str) -> None:
    """Write a file in the scratch repo."""
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A scratch git repo with the real house-rules project and an empty baseline."""
    git(tmp_path, "init", "-q")
    (tmp_path / "house-rules").symlink_to(REPO / "house-rules")
    write(tmp_path, ".house-rules.toml", EXCLUDE)
    write(tmp_path, BAD, CLEAN)
    write(tmp_path, WARN, CLEAN)
    write(tmp_path, BASELINE, json.dumps({"version": 1, "entries": {}}))
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


@pytest.fixture
def conf(repo: Path) -> config.Config:
    """The real config, with ruff dropped from the commands this test runs."""
    raw = real_raw()
    tool = raw["toolchain"]
    tool["static"] = without_ruff(tool["static"])
    tool["files"]["fix"] = without_ruff(tool["files"]["fix"])
    tool["files"]["lint_files"] = without_ruff(tool["files"]["lint_files"])
    return config.from_raw(repo, raw)


def run(repo: Path, command: str) -> tuple[int, str]:
    """Run a command the way the runner does (sh, repo root)."""
    return commands.shell_runner(repo)(command)


def stop_lint(repo: Path, conf: config.Config, files: list[str]) -> list[tuple[int, str]]:
    """The stop hook's lint step: every fix, then every lint_files run."""
    tool = conf.toolchain
    for fix in tool.file_runs(config.FileCommand.FIX, files):
        run(repo, fix)
    return [run(repo, c) for c in tool.file_runs(config.FileCommand.LINT, files)]


def test_ac1_new_failure_in_both_roots_names_file_line_and_rule(repo, conf) -> None:
    """AC1: a new failing finding refuses the stop, in each targeted root."""
    write(repo, BAD, FAILING)
    write(repo, "unattended/runner/unattended/bad2.py", FAILING)
    ran = stop_lint(repo, conf, [BAD, "unattended/runner/unattended/bad2.py"])
    assert len(ran) == 2
    assert all(code != 0 for code, _ in ran)
    text = "\n".join(out for _, out in ran)
    assert f"{BAD}:2: fail global-scope" in text
    assert "unattended/runner/unattended/bad2.py:2: fail global-scope" in text


def test_ac1_warnings_do_not_refuse(repo, conf) -> None:
    """AC1: a warning-only file passes the stop."""
    write(repo, WARN, WARNING_ONLY)
    [(code, out)] = stop_lint(repo, conf, [WARN])
    assert code == 0, out
    assert "warn parameters" in out


def test_ac1_baselined_and_stale_do_not_refuse(repo, conf) -> None:
    """AC1: a baselined finding and then a stale entry both pass the stop."""
    write(repo, BAD, FAILING)
    assert run(repo, ACCEPT)[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "baselined")
    assert stop_lint(repo, conf, [BAD])[0][0] == 0
    write(repo, BAD, CLEAN)
    # the entry is stale now; the stop's fix run must not trip on it either
    [(code, _)] = stop_lint(repo, conf, [BAD])
    assert code == 0


def test_ac2_new_finding_routes_to_the_files_owner_and_warnings_do_not(repo, conf) -> None:
    """AC2: `static` fails on a new finding; its fail line goes to the owner, warn lines nowhere."""
    write(repo, BAD, FAILING)
    write(repo, WARN, WARNING_ONLY)
    code, out = run(repo, conf.toolchain.commands["static"])
    assert code != 0
    found = owners.findings(out, owners.Source.LINT)
    assert {f.path for f in found} == {BAD}
    writers = (
        owners.Writer("implement", "developer-cli", ("agile-team/**",)),
        owners.Writer("tests", "unit-tester", ("unattended/**",)),
    )
    gate = owners.Owners(writers, "quality", frozenset({BAD, WARN}))
    split = owners.split(owners.placed(found, git(repo, "ls-files")), gate)
    assert [(f.role, [i.path for i in f.items]) for f in split.fixes] == [("developer-cli", [BAD])]


def test_ac2_static_is_one_of_the_quality_step_checks(conf) -> None:
    """AC2: the commands the gates route, and the quality step runs, include `static`."""
    from agile_team import gates

    assert "static" in gates.ROUTED_COMMANDS
    assert "house-rules" in conf.toolchain.commands["static"]


def test_ac3_boundary_checks_run_house_rules_and_fail_on_a_new_finding(repo, conf) -> None:
    """AC3: the sprint-start/end checks run `static` (exit judged); a new finding fails it."""
    assert ("static", fullcheck.Judge.EXIT) in fullcheck.TOOLCHAIN_CHECKS
    check = fullcheck.FullCheck("static", conf.toolchain.commands["static"])
    judging = fullcheck.Judging(commands.shell_runner(repo), 95)
    assert fullcheck.run_checks([check], judging).passed
    write(repo, BAD, FAILING)
    report = fullcheck.run_checks([check], judging)
    assert not report.passed
    assert f"{BAD}:2: fail global-scope" in report.reason()


def test_ac4_fixed_entry_leaves_the_baseline_in_the_step_commit(repo, conf) -> None:
    """AC4: fixing a baselined finding shrinks the baseline; a hand-added entry is thrown away."""
    write(repo, BAD, FAILING)
    assert run(repo, ACCEPT)[0] == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "baselined")
    before = json.loads((repo / BASELINE).read_text())["entries"]
    assert before
    write(repo, BAD, CLEAN)
    hand = json.loads((repo / BASELINE).read_text())
    hand["entries"]["x.py::f::verb-name"] = 1
    write(repo, BASELINE, json.dumps(hand))
    stop_lint(repo, conf, [BAD])
    after = json.loads((repo / BASELINE).read_text())["entries"]
    assert after == {}
    assert "x.py::f::verb-name" not in after


def test_ac4_baseline_cannot_grow_through_the_step(repo, conf) -> None:
    """AC4: a step that adds a finding leaves the baseline as HEAD's."""
    write(repo, BAD, FAILING)
    stop_lint(repo, conf, [BAD])
    assert json.loads((repo / BASELINE).read_text())["entries"] == {}


@pytest.mark.parametrize("role", PYTHON_ROLES)
def test_ac4_every_python_role_may_write_the_baseline(role, conf) -> None:
    """AC4: the role's resolved write list holds the baseline file."""
    book = roles.RoleBook.for_repo(REPO, conf.roles)
    write_globs = book.resolve(role).write
    assert BASELINE in write_globs
    assert guard.matches(BASELINE, [g for g in write_globs if not g.startswith("{")])


def test_ac5_a_repo_without_house_rules_runs_only_ruff() -> None:
    """AC5: the preset's own commands hold no house-rules; the lines are the repo's config."""
    preset = config.load_presets()["python"]
    assert "house-rules" not in json.dumps(preset)
    tool = real_raw()["toolchain"]
    assert "house-rules" in tool["static"]
    assert "house-rules" in tool["files"]["lint_files"]
    assert "house-rules" in tool["files"]["fix"]
