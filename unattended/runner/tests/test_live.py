"""Live smoke tests: one tiny prompt job against the real model, per auth mode.

Skipped unless ``UNATTENDED_LIVE=1``, because they spend money (about a cent
each, on Haiku, capped at ``MAX_COST``). Each runs in a scratch ``HOME``, so
neither touches the real home directory:

- ``api-key`` reads the key file named by ``UNATTENDED_LIVE_KEY_FILE`` (mode 600);
- ``login`` uses ``CLAUDE_CODE_OAUTH_TOKEN`` (from ``claude setup-token``),
  since a scratch ``HOME`` has no saved login.

The run makes one Bash tool step, so the step hooks, the ledger, the
transcript and the prefix fingerprint are all checked against the real CLI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from unattended.auth import ENV_VAR, Auth, AuthSetup
from unattended.ledger import read_calls
from unattended.limits import Bounds, OutcomeKind
from unattended.prompt_job import PromptJob
from unattended.store import EVENTS_FILE, OUTPUT_FILE, Job, JobKind, Spec
from unattended.transcript import Transcript
from unattended.watch import RunWatch

from .conftest import MakeJob

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("UNATTENDED_LIVE") != "1", reason="set UNATTENDED_LIVE=1"),
]
MAX_COST = 0.10
PROMPT = "Use the Bash tool to run `echo pong`, then reply with its output and nothing else."
LOGIN_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
KEY_FILE = "UNATTENDED_LIVE_KEY_FILE"


@pytest.fixture
def scratch_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def setup_for(auth: Auth, home: Path, monkeypatch: pytest.MonkeyPatch) -> AuthSetup:
    """The auth under test, or a skip naming what it needs."""
    if auth is Auth.LOGIN:
        if not os.environ.get(LOGIN_TOKEN):
            pytest.skip(f"set {LOGIN_TOKEN} (claude setup-token)")
        monkeypatch.delenv(ENV_VAR, raising=False)
        return AuthSetup(auth, None, home)
    if not os.environ.get(KEY_FILE):
        pytest.skip(f"set {KEY_FILE} to a mode-600 API key file")
    return AuthSetup(auth, Path(os.environ[KEY_FILE]), home)


def live_job(make_job: MakeJob, workdir: Path, auth: Auth) -> Job:
    spec = Spec(JobKind.PROMPT, str(workdir), prompt=PROMPT, model="haiku", auth=auth,
                allowed_tools=["Bash(echo:*)"], setting_sources=[])  # fmt: skip
    job = make_job(spec)
    job.update(lambda st: setattr(st, "bounds", Bounds(max_cost=MAX_COST)))
    return job


def event_names(job: Job) -> list[str]:
    return [json.loads(line)["event"] for line in job.path(EVENTS_FILE).read_text().splitlines()]


@pytest.mark.parametrize("auth", list(Auth))
def test_a_prompt_job_runs_a_tool_step_end_to_end(
    auth: Auth, make_job: MakeJob, workdir: Path, scratch_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    setup = setup_for(auth, scratch_home, monkeypatch)
    assert setup.problems(os.environ) == []
    job = live_job(make_job, workdir, auth)
    outcome = PromptJob(job, setup.env()).run_once(RunWatch(job))
    assert outcome.kind is OutcomeKind.DONE, outcome.reason
    assert "pong" in job.path(OUTPUT_FILE).read_text()
    assert 0 < outcome.metrics.cost <= MAX_COST
    assert read_calls(job), "the ledger has no API responses"
    assert '"name": "Bash"' in Transcript(job, 1).path.read_text()
    assert "prefix" in event_names(job)
