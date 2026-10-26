"""s186 end to end: an environment's prepare command sees no runner venv, only its own tools."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w
from agile_team import config as config_mod
from agile_team.sandbox import Order, Preparer

from ..conftest import PY_CONFIG, git

PREPARE = (
    "cd {sandbox} && uv venv -q .venv > uv.out 2>&1 && uv pip list >> uv.out 2>&1; "
    'echo "VENV=[$VIRTUAL_ENV]" > seen.txt; echo "PATH=$PATH" >> seen.txt; '
    ".venv/bin/python -c 'import sys; print(sys.prefix)' >> seen.txt"
)


def make_config(configured: Path) -> config_mod.Config:
    """A repo with a ``package`` environment whose prepare reports what it sees."""
    cfg = dict(PY_CONFIG)
    cfg["environment"] = [{"name": "pkg", "kind": "package", "prepare": PREPARE, "bin": ["bin"]}]
    (configured / config_mod.CONFIG_NAME).write_text(tomli_w.dumps(cfg))
    git(configured, "commit", "-qam", "package environment")
    return config_mod.load(configured)


def test_prepare_sees_its_own_venv_not_the_runners(
    configured: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_venv = "/nonexistent/runner-venv"
    monkeypatch.setenv("VIRTUAL_ENV", runner_venv)
    monkeypatch.setenv("PATH", f"{runner_venv}/bin:/usr/bin:/bin:/opt/homebrew/bin")
    config = make_config(configured)
    prepared = Preparer().prepare(config, Order(config.environments[0]))
    seen = (prepared.root / "seen.txt").read_text()
    assert "VENV=[]" in seen
    assert "runner-venv" not in seen
    assert f"PATH={prepared.root / 'bin'}:" in seen
    assert str(prepared.root / ".venv") in seen
    uv_out = (prepared.root / "uv.out").read_text()
    assert "does not match" not in uv_out
    assert "runner-venv" not in uv_out
