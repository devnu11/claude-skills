"""s158 end to end: a real re-pin subprocess execs the pin with the global options first."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from agile_team import cli, repin

OLD, NEW = "a" * 40, "b" * 40
DRIVER = (
    "import sys\n"
    "from pathlib import Path\n"
    "from agile_team import repin\n"
    "repo, home = Path(sys.argv[1]), sys.argv[2] or None\n"
    "pin = repin.Pin(repo, repin.build_global_argv(repo, home))\n"
    f"pin.repin(repin.Marker('{OLD}', '{NEW}', 3, repin.Outcome.TRIAL))\n"
)


def script(path: Path, body: str) -> None:
    """Write an executable shell script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def build(tmp_path: Path, uv_code: int) -> tuple[Path, Path, dict[str, str]]:
    """A repo with a fake pin script, a fake pinned exe and a recording fake uv."""
    repo, bin_dir = tmp_path / "repo", tmp_path / "bin"
    run = repo / ".team/run"
    log = tmp_path / "calls.log"
    (repo / "agile-team/runner/scripts").mkdir(parents=True)
    (repo / "agile-team/runner/scripts/pin-runner.sh").write_text(
        f'echo "pin $@" >> {log}\n[ "$1" = "--rollback" ] || echo {NEW} > {run}/runner-pin.commit\n'
    )
    run.mkdir(parents=True)
    (run / "runner-pin.commit").write_text(OLD + "\n")
    script(run / "runner-pin/.venv/bin/agile-team", f'echo "exec $@" >> {log}\n')
    script(bin_dir / "uv", f'echo "uv $@" >> {log}\nexit {uv_code}\n')
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return repo, log, env


def drive(repo: Path, home: str, env: dict[str, str]) -> None:
    """Run the re-pin in its own process; the exec ends it."""
    subprocess.run([sys.executable, "-c", DRIVER, str(repo), home], env=env, check=True, timeout=60)


def calls(log: Path) -> list[list[str]]:
    """The recorded calls, split into words."""
    return [line.split() for line in log.read_text().splitlines()]


def test_a_passing_check_execs_the_pin_with_options_before_the_subcommand(tmp_path: Path) -> None:
    repo, log, env = build(tmp_path, 0)
    drive(repo, str(tmp_path / "keys"), env)
    uv, ex = calls(log)[1], calls(log)[2]
    assert uv[uv.index("agile-team") + 1 :] == [
        "--repo", str(repo), "--home", str(tmp_path / "keys"), "config", "check"
    ]  # fmt: skip
    assert ex[1:] == ["--repo", str(repo), "--home", str(tmp_path / "keys"), "start", "--resume"]
    ns = cli.build_parser().parse_args(ex[1:])
    assert (ns.command, ns.repo) == ("start", str(repo))
    marker = json.loads((repo / ".team/run/repin.json").read_text())
    assert marker["outcome"] == "trial"


def test_without_a_home_only_the_repo_goes_first(tmp_path: Path) -> None:
    repo, log, env = build(tmp_path, 0)
    drive(repo, "", env)
    ex = calls(log)[2]
    assert ex[1:] == ["--repo", str(repo), "start", "--resume"]
    cli.build_parser().parse_args(ex[1:])


def test_a_failed_check_rolls_back_and_resumes_the_old_pin(tmp_path: Path) -> None:
    repo, log, env = build(tmp_path, 2)
    drive(repo, "", env)
    done = calls(log)
    assert done[2][:2] == ["pin", "--rollback"]
    assert done[3][1:] == ["--repo", str(repo), "start", "--resume"]
    cli.build_parser().parse_args(done[3][1:])
    marker = json.loads((repo / ".team/run/repin.json").read_text())
    assert marker["outcome"] == "rolled_back"
    assert "config check exited 2" in marker["reason"]
    assert repin.MARKER_FILE == "repin.json"
