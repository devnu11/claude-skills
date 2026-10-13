"""s26 end to end: a `web` acceptance environment is started from its presentation and probed."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import tomli_w
from agile_team import config as config_mod
from agile_team import gates, presentation
from agile_team.gates import Verdict
from agile_team.sandbox import port_in_use

from ..conftest import PY_CONFIG, git, write_story

RUNNER = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def web(configured: Path):
    """A repo with a real `dashboard` acceptance environment on a free port, plus its trial."""
    port = free_port()
    cfg = dict(PY_CONFIG)
    cfg["environment"] = [
        {
            "name": "dashboard",
            "kind": "web",
            "prepare": f"uv run --directory {RUNNER} agile-team --repo "
            "{sandbox}/presentation/workspace dashboard --host {host} --port {port} --no-open",
            "url": f"http://127.0.0.1:{port}/",
            "probe": "api/snapshot",
        }
    ]
    (configured / config_mod.CONFIG_NAME).write_text(tomli_w.dumps(cfg))
    git(configured, "commit", "-qam", "web acceptance environment")
    config = config_mod.load(configured)
    write_story(config, "s1", "dashboard")
    story = gates.StoryState("s1", "Dash", "e2e", sprint=1)
    return config, story, port


def present_workspace(config, init: bool) -> Path:
    source = presentation.lay_out(config, gates.StoryState("s1", "Dash", "e2e"))
    (source / "PRESENTATION.md").write_text("Open the dashboard.\n")
    if not init:  # seeds opted out (seed = ""), so nothing plants a config
        (source / "workspace" / "note.txt").write_text("no config here\n")
    return source


def test_trial_starts_the_real_dashboard_probes_it_and_stops_it(web) -> None:
    """AC1/AC2/AC4: the dashboard answers /api/snapshot, then nothing listens."""
    config, story, port = web
    present_workspace(config, init=True)
    outcome = presentation.Trial(config).liveness(story)
    assert outcome.verdict is Verdict.PASS, outcome.reason
    assert outcome.reason == f"presentation ready; http://127.0.0.1:{port}/api/snapshot answered"
    assert not port_in_use("127.0.0.1", port)
    assert not list((config.run_dir / "customer").glob("*.pid"))


def test_trial_bounces_a_broken_workspace_with_the_dashboards_own_error(web) -> None:
    """AC2: no .agile-team.toml in the workspace; the reason quotes the real output."""
    config, story, port = web
    bare = replace(config.environments[0], seed="")
    config = replace(config, environments=[bare])
    present_workspace(config, init=False)
    outcome = presentation.Trial(config).liveness(story)
    assert outcome.verdict is Verdict.BOUNCE
    assert outcome.reason.startswith(
        "story s1 presentation is not up: acceptance environment 'dashboard' did not"
    )
    assert ".agile-team.toml not found" in outcome.reason
    assert not port_in_use("127.0.0.1", port)


def test_a_busy_port_holds_and_is_not_killed(web) -> None:
    """AC4: a foreign listener is reported clearly (HOLD) and left alone."""
    config, story, port = web
    present_workspace(config, init=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        outcome = presentation.Trial(config).liveness(story)
        assert outcome.verdict is Verdict.HOLD
        assert f"127.0.0.1:{port} is already in use" in outcome.reason
        assert port_in_use("127.0.0.1", port)


def test_a_stale_service_is_replaced_not_reused(web) -> None:
    """AC4: a service left by an earlier step is stopped before the next one starts."""
    config, story, _port = web
    present_workspace(config, init=True)
    root = config.run_dir / "customer"
    root.mkdir(parents=True, exist_ok=True)
    stale = subprocess.Popen(["sleep", "60"], start_new_session=True)
    (root / "dashboard.pid").write_text(str(stale.pid))
    try:
        outcome = presentation.Trial(config).liveness(story)
        assert outcome.verdict is Verdict.PASS, outcome.reason
        assert stale.wait(timeout=15) is not None
    finally:
        if stale.poll() is None:
            os.killpg(stale.pid, signal.SIGKILL)
