"""s26: a presentation starts the environment; "presentation ready" needs it up and answering."""

from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, gates, handover, presentation, sandbox, system
from agile_team import config as cfg
from agile_team.config import Environment
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState, StoryStatus, Verdict
from agile_team.presentation import Check, Need, Recipe, Trial
from agile_team.roles import Handoff
from agile_team.sandbox import NotUp, Order, PortBusy, Preparer, Start

from .conftest import FakeQuery, FakeRunner, present
from .fake_system import FAKE_REPO, FIRST_CHILD_PID, START_CLOCK, Done, FakeSystem, Hang

PORT = 8799
URL = f"http://127.0.0.1:{PORT}/"
PROBE_URL = URL + "api/snapshot"
DASHBOARD = Environment(
    "ui",
    "web",
    prepare="serve --host {host} --port {port} --repo {sandbox}/presentation/workspace",
    url=URL,
    probe="api/snapshot",
)
LEADER = FIRST_CHILD_PID  # the pid the first spawned child gets, and its group
STARTED_5S_AGO = Done(0, "00:05\n")


# ----- fakes ----------------------------------------------------------------


class Probe:
    """A probe that answers true from its ``up_on``-th call on (never when ``None``)."""

    def __init__(self, up_on: int | None = 1):
        self.up_on = up_on
        self.urls: list[str] = []

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        return self.up_on is not None and len(self.urls) >= self.up_on


def preparer(probe: Any = None, *, busy: bool = False, **kw: Any) -> Preparer:
    return Preparer(probe=probe or Probe(), listening=lambda _h, _p: busy, **kw)


@pytest.fixture
def config(configured: Path) -> cfg.Config:
    c = cfg.load(configured)
    c.environments = [DASHBOARD]
    return c


def pid_file(config: cfg.Config) -> Path:
    return config.run_dir / "customer/ui.pid"


def log_file(config: cfg.Config) -> Path:
    return config.run_dir / "customer/ui.log"


def story_of(step: str = "e2e", story_id: str = "s4", **kw: Any) -> StoryState:
    kw.setdefault("sprint", 1)
    return StoryState(story_id, "A story", step, **kw)


def killpgs(fake: FakeSystem) -> list[tuple[int, int]]:
    return [(group, sig) for name, group, sig in fake.signals if name == "killpg"]


def stale_service(fake: FakeSystem, config: cfg.Config, pid: int = LEADER) -> None:
    """A pid file naming a running group that leads its own session, started just before it."""
    fake.reply(("ps",), STARTED_5S_AGO)
    fake.groups[pid] = pid
    fake.put(pid_file(config), str(pid))


# ----- config ---------------------------------------------------------------


def test_environment_probe_defaults_to_empty_and_is_the_last_field() -> None:
    assert Environment("a", "web").probe == ""
    assert list(Environment.__dataclass_fields__)[-1] == "probe"


def test_probe_is_read_from_the_toml(configured: Path) -> None:
    toml = system.read_text(configured / ".agile-team.toml")
    toml += '\n[[environment]]\nname = "ui"\nkind = "web"\nurl = "http://h/"\nprobe = "api/x"\n'
    system.write_text(configured / ".agile-team.toml", toml)
    assert cfg.load(configured).environment("ui").probe == "api/x"


# ----- L1 / L2: placeholders ------------------------------------------------


def test_constants() -> None:
    assert sandbox.PROBE_ATTEMPTS == 120
    assert sandbox.PROBE_EVERY_S == 0.25
    assert sandbox.PROBE_TIMEOUT_S == 2
    assert sandbox.STOP_WAIT_S == 10
    assert sandbox.LOG_TAIL_LINES == 20
    assert sandbox.DEFAULT_PORTS == {"http": 80, "https": 443}


def bare(environment: Environment, repo: Path, root: Path) -> sandbox.Prepared:
    return sandbox.Prepared(environment, sandbox.ENVIRONMENT_KINDS["web"], repo, root, root)


def test_expand_makes_repo_and_sandbox_absolute() -> None:
    p = bare(DASHBOARD, Path("."), Path(".team/run/customer/ui"))
    repo, box = p.expand("{repo}|{sandbox}").split("|")
    assert repo == str(FAKE_REPO)
    assert box == str(FAKE_REPO / ".team/run/customer/ui")


@pytest.mark.parametrize(
    ("url", "host", "port"),
    [
        ("http://127.0.0.1:8799/", "127.0.0.1", "8799"),
        ("http://h/", "h", "80"),
        ("https://h/x", "h", "443"),
        ("", "", ""),
    ],
)
def test_expand_fills_host_and_port_from_the_url(url: str, host: str, port: str) -> None:
    p = bare(Environment("ui", "web", url=url), Path("."), Path("."))
    assert p.expand("{host}:{port}") == f"{host}:{port}"


def test_address_probe_url_and_service_files(scratch: Path) -> None:
    root = scratch / "customer" / "ui"
    p = bare(DASHBOARD, scratch, root)
    assert p.address() == ("127.0.0.1", 8799)
    assert p.probe_url() == PROBE_URL
    assert p.pid_file() == scratch / "customer/ui.pid"
    assert p.log_file() == scratch / "customer/ui.log"
    assert bare(Environment("ui", "web", url=URL), scratch, root).probe_url() == URL


def test_make_pipeline_wires_the_trial(configured: Path) -> None:
    config = cfg.load(configured)
    live = cli.make_pipeline(config).checks.liveness
    assert isinstance(live.__self__, Trial) and live.__self__.config is config  # type: ignore[attr-defined]
    out = live(story_of())
    assert out.verdict is Verdict.PASS and out.reason == "presentation ready"


# ----- L3: liveness is data -------------------------------------------------


def test_only_web_is_a_service() -> None:
    assert presentation.PRESENTATIONS["web"] == Recipe(Need.WORKSPACE, Check.SERVICE)
    assert Check.FILES.value == "files" and Check.SERVICE.value == "service"
    assert Recipe(Need.GUIDE_ONLY).check is Check.FILES


def test_service_check_matches_background_start() -> None:
    for kind, recipe in presentation.PRESENTATIONS.items():
        background = sandbox.ENVIRONMENT_KINDS[kind].start is Start.BACKGROUND
        assert (recipe.check is Check.SERVICE) is background


def test_recipe_of_reads_the_environment(config: cfg.Config) -> None:
    config.environments = [Environment("cli", "package"), DASHBOARD]
    assert presentation.recipe_of(config, story_of(environment="ui")).check is Check.SERVICE
    assert presentation.recipe_of(config, story_of()).check is Check.FILES
    config.environments = []
    assert presentation.recipe_of(config, story_of()) == Recipe(Need.GUIDE_ONLY)


def test_presented_source(config: cfg.Config) -> None:
    assert presentation.presented_source(config, None) is None
    assert presentation.presented_source(config, story_of()) is None
    source = present(config, "s4")
    assert presentation.presented_source(config, story_of()) == source


# ----- L4 / L5: start and probe ---------------------------------------------


def test_prepare_starts_the_service_and_waits_for_the_probe(
    config: cfg.Config, fake: FakeSystem, monkeypatch
) -> None:
    fake.reply(("serve",), Hang("up\n"))
    probe = Probe(up_on=3)
    seen_copy: list[bool] = []
    spawn = system.spawn_logged

    def spying(command: system.ShellCommand, log: Path) -> system.Process:
        seen_copy.append(
            system.exists(config.run_dir / "customer/ui/presentation/workspace/todo.txt")
        )
        return spawn(command, log)

    monkeypatch.setattr(system, "spawn_logged", spying)
    p = preparer(probe).prepare(config, Order(DASHBOARD, present(config, "s4")))
    assert probe.urls == [PROBE_URL] * 3 and fake.slept == [sandbox.PROBE_EVERY_S] * 2
    assert seen_copy == [True]
    (command,) = fake.commands
    assert "--host 127.0.0.1 --port 8799" in command.text
    assert f"--repo {p.root}/presentation/workspace" in command.text
    assert (command.cwd, command.env) == (config.repo, p.env)
    assert p.process.pid == LEADER
    assert system.read_text(pid_file(config)) == str(system.pgid(LEADER))
    assert system.is_file(log_file(config))


def test_prepare_with_a_relative_repo_still_gives_absolute_paths(
    config: cfg.Config, fake: FakeSystem
) -> None:
    config.repo = Path(".")
    preparer().prepare(config, Order(DASHBOARD))
    command = fake.commands[0].text
    assert "--repo ." not in command and f"--repo {FAKE_REPO}" in command


def test_prepare_runs_a_service_with_pid_and_log(config: cfg.Config, fake: FakeSystem) -> None:
    """L6: the child's output reaches the log, and stop() removes the pid file."""
    fake.reply(("echo",), Hang("hello\n"))
    d = Environment("ui", "web", prepare="echo hello; exec sleep 60", url=URL)
    config.environments = [d]
    p = preparer().prepare(config, Order(d))
    assert p.process.poll() is None
    assert system.read_text(pid_file(config)) == str(system.pgid(p.process.pid))
    assert system.read_text(log_file(config)) == "hello\n"
    p.stop()
    assert not system.exists(pid_file(config))
    assert system.read_text(log_file(config)) == "hello\n"


def test_the_log_is_truncated_at_each_start(config: cfg.Config, fake: FakeSystem) -> None:
    fake.reply(("echo", "first"), Done(0, "first\n"))
    fake.reply(("echo", "second"), Done(0, "second\n"))
    d = Environment("ui", "web", url=URL, prepare="echo first")
    config.environments = [d]
    made = preparer()
    made.prepare(config, Order(d))
    d.prepare = "echo second"
    made.prepare(config, Order(d))
    text = system.read_text(log_file(config))
    assert "second" in text and "first" not in text


def test_service_files_sit_beside_the_sandbox_not_inside_it(
    config: cfg.Config, fake: FakeSystem
) -> None:
    p = preparer().prepare(config, Order(DASHBOARD))
    assert p.root == config.run_dir / "customer/ui"
    assert pid_file(config).parent == p.root.parent
    inside = [Path(name) for name in fake.files if name.startswith(f"{p.root}/")]
    assert not [f for f in inside if f.suffix in {".pid", ".log"}]


def test_background_environment_without_a_command_is_still_probed(
    config: cfg.Config, fake: FakeSystem
) -> None:
    d = Environment("ui", "web", url=URL, probe="api/snapshot")
    probe = Probe()
    p = preparer(probe).prepare(config, Order(d))
    assert fake.commands == [] and p.process is None and probe.urls == [PROBE_URL]


def test_background_environment_without_a_command_that_never_answers_is_not_up(
    config: cfg.Config,
) -> None:
    d = Environment("ui", "web", url=URL, probe="api/snapshot")
    with pytest.raises(NotUp, match="did not answer"):
        preparer(Probe(None), attempts=2).prepare(config, Order(d))


def test_exited_process_fails_at_once_with_the_output(config: cfg.Config, fake: FakeSystem) -> None:
    fake.reply(("serve",), Done(1, "first\nagile-team dashboard: .agile-team.toml not found\n"))
    probe = Probe(None)
    with pytest.raises(NotUp) as info:
        preparer(probe).prepare(config, Order(DASHBOARD))
    assert len(probe.urls) == 1
    text = str(info.value)
    assert text.startswith(
        "acceptance environment 'ui' did not start: the start command exited with code 1 "
        f"before {PROBE_URL} answered. Last output:\n"
    )
    assert "agile-team dashboard: .agile-team.toml not found" in text
    assert not system.exists(pid_file(config))


def test_a_service_that_never_answers_is_stopped_and_reported(
    config: cfg.Config, fake: FakeSystem
) -> None:
    fake.reply(("serve",), Hang("warming up\n"))
    probe = Probe(None)
    with pytest.raises(NotUp) as info:
        preparer(probe, attempts=3).prepare(config, Order(DASHBOARD))
    assert len(probe.urls) == 3
    assert str(info.value).startswith(
        f"acceptance environment 'ui' did not answer {PROBE_URL} within 0.75s. Last output:\n"
    )
    assert "warming up" in str(info.value)
    assert killpgs(fake)[0] == (LEADER, signal.SIGTERM)
    assert not system.exists(pid_file(config))


def test_a_hung_service_is_reported_as_not_answering_not_as_killed(
    config: cfg.Config, fake: FakeSystem
) -> None:
    """The runner's own SIGTERM must not turn a timeout into 'exited with code -15'."""
    fake.reply(("exec",), Hang())
    d = Environment("ui", "web", prepare="exec sleep 60", url=URL, probe="api/snapshot")
    with pytest.raises(NotUp) as info:
        preparer(Probe(None), attempts=2).prepare(config, Order(d))
    assert str(info.value).startswith(
        f"acceptance environment 'ui' did not answer {PROBE_URL} within 0.5s."
    )
    assert "exited with code" not in str(info.value)
    assert killpgs(fake) == [(LEADER, signal.SIGTERM)]


def test_empty_log_reads_no_output(config: cfg.Config, fake: FakeSystem) -> None:
    fake.reply(("serve",), Done(2))
    with pytest.raises(NotUp, match=r"Last output:\n\(no output\)"):
        preparer(Probe(None)).prepare(config, Order(DASHBOARD))


def test_only_the_last_twenty_log_lines_are_quoted(config: cfg.Config, fake: FakeSystem) -> None:
    fake.reply(("serve",), Done(3, "".join(f"line{i:02d}\n" for i in range(30))))
    with pytest.raises(NotUp) as info:
        preparer(Probe(None)).prepare(config, Order(DASHBOARD))
    text = str(info.value)
    assert "line29" in text and "line10" in text
    assert "line09" not in text and "line00" not in text


def test_foreground_kinds_are_unchanged(configured: Path, fake: FakeSystem) -> None:
    fake.reply(("exit",), Done(3))
    d = Environment("cli", "package", prepare="exit 3")
    probe = Probe()
    with pytest.raises(sandbox.SandboxError, match="prepare"):
        preparer(probe=probe).prepare(cfg.load(configured), Order(d))
    assert probe.urls == []


def test_not_up_and_port_busy_are_sandbox_errors() -> None:
    assert issubclass(NotUp, sandbox.SandboxError) and issubclass(PortBusy, sandbox.SandboxError)
    assert not issubclass(NotUp, PortBusy) and not issubclass(PortBusy, NotUp)


# ----- L8: port conflict ----------------------------------------------------


def test_a_busy_port_is_refused_before_anything_starts(
    config: cfg.Config, fake: FakeSystem
) -> None:
    with pytest.raises(PortBusy) as info:
        preparer(busy=True).prepare(config, Order(DASHBOARD))
    assert str(info.value) == (
        "acceptance environment 'ui' cannot start: 127.0.0.1:8799 is already in use by a process "
        "the runner did not start; stop it or change the environment's url"
    )
    assert fake.commands == []


def test_the_default_port_check_reads_the_listening_ports(
    config: cfg.Config, fake: FakeSystem
) -> None:
    fake.listening.add(("127.0.0.1", PORT))
    with pytest.raises(PortBusy):
        Preparer(probe=Probe()).prepare(config, Order(DASHBOARD))
    assert fake.commands == []


def test_port_in_use_sees_a_listening_address(fake: FakeSystem) -> None:
    fake.listening.add(("127.0.0.1", PORT))
    assert sandbox.port_in_use("127.0.0.1", PORT) is True
    fake.listening.clear()
    assert sandbox.port_in_use("127.0.0.1", PORT) is False


# ----- L5: http_answers -----------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "ctype", "answers"),
    [
        (200, b'{"a": 1}', "application/json", True),
        (200, b"<html></html>", "text/html", True),
        (200, b"not json", "application/json", False),
        (500, b'{"a": 1}', "application/json", False),
        (404, b"no", "text/plain", False),
        (204, b"", "text/plain", False),
        (201, b"{}", "application/json", False),
    ],
)
def test_http_answers(
    fake: FakeSystem, status: int, body: bytes, ctype: str, answers: bool
) -> None:
    fake.web[URL] = system.HttpReply(status, ctype, body)
    assert sandbox.http_answers(URL) is answers


def test_http_answers_asks_with_the_probe_timeout(fake: FakeSystem, monkeypatch) -> None:
    asked: list[tuple[str, float]] = []

    def get(url: str, timeout: float) -> system.HttpReply:
        asked.append((url, timeout))
        return system.HttpReply(200, "text/html", b"")

    monkeypatch.setattr(system, "http_get", get)
    assert sandbox.http_answers(URL)
    assert asked == [(URL, sandbox.PROBE_TIMEOUT_S)]


def test_http_answers_is_false_when_nothing_listens() -> None:
    assert sandbox.http_answers(URL) is False


@pytest.mark.parametrize("error", [OSError("boom"), ValueError("unknown url type")])
def test_http_answers_is_false_for_a_failed_or_bad_url(fake: FakeSystem, error) -> None:
    fake.web["not a url"] = error
    assert sandbox.http_answers("not a url") is False


# ----- L7: stale services ---------------------------------------------------


def test_a_stale_group_that_ignores_sigterm_is_killed(config: cfg.Config, fake: FakeSystem) -> None:
    stale_service(fake, config)
    fake.survivors.add(LEADER)
    sandbox.stop_stale(config.run_dir / "customer/ui")
    assert killpgs(fake) == [(LEADER, signal.SIGTERM), (LEADER, signal.SIGKILL)]
    assert fake.clock >= START_CLOCK + sandbox.STOP_WAIT_S
    assert not system.exists(pid_file(config))


def test_stop_stale_ends_a_leftover_service(config: cfg.Config, fake: FakeSystem) -> None:
    stale_service(fake, config)
    sandbox.stop_stale(config.run_dir / "customer/ui")
    assert killpgs(fake) == [(LEADER, signal.SIGTERM)]
    assert LEADER not in fake.groups
    assert not system.exists(pid_file(config))


def test_stop_stale_with_a_dead_pid_just_removes_the_file(
    config: cfg.Config, fake: FakeSystem
) -> None:
    fake.put(pid_file(config), str(LEADER))
    sandbox.stop_stale(config.run_dir / "customer/ui")
    assert fake.signals == []
    assert not system.exists(pid_file(config))


def test_stop_stale_without_a_pid_file_does_nothing(config: cfg.Config, fake: FakeSystem) -> None:
    sandbox.stop_stale(config.run_dir / "customer/ui")
    assert fake.signals == []


def test_stop_stale_never_signals_a_process_that_is_not_a_group_leader(
    config: cfg.Config, fake: FakeSystem
) -> None:
    fake.reply(("ps",), STARTED_5S_AGO)
    fake.groups[LEADER] = fake.pgrp()  # a child in the runner's own group
    fake.put(pid_file(config), str(LEADER))
    sandbox.stop_stale(config.run_dir / "customer/ui")
    assert fake.signals == []
    assert LEADER in fake.groups
    assert not system.exists(pid_file(config))


def test_prepare_replaces_a_stale_service_before_starting(
    config: cfg.Config, fake: FakeSystem
) -> None:
    stale_service(fake, config, pid=LEADER + 50)
    p = preparer().prepare(config, Order(DASHBOARD))
    assert (LEADER + 50) not in fake.groups
    assert p.process is not None


# ----- L9: teardown ---------------------------------------------------------


def test_stop_deletes_the_pid_file_and_is_safe_twice(scratch: Path) -> None:
    root = scratch / "customer" / "ui"
    system.make_dirs(root)
    p = bare(DASHBOARD, scratch, root)
    system.write_text(p.pid_file(), "123")
    p.stop()
    p.stop()
    assert not system.exists(p.pid_file())


def test_stop_with_a_started_process_ends_the_group_and_the_file(
    config: cfg.Config, fake: FakeSystem
) -> None:
    fake.reply(("exec",), Hang())
    d = Environment("ui", "web", prepare="exec sleep 60", url=URL)
    config.environments = [d]
    p = preparer().prepare(config, Order(d))
    p.stop()
    assert p.process.poll() is not None and not system.exists(pid_file(config))


# ----- L10: Trial and the gate ----------------------------------------------


class Fakes:
    """A prepare function that records orders and returns or raises on demand."""

    def __init__(self, config: cfg.Config, raises: Exception | None = None):
        self.config, self.raises = config, raises
        self.orders: list[Order] = []
        self.stops = 0

    def __call__(self, config: cfg.Config, order: Order) -> sandbox.Prepared:
        self.orders.append(order)
        if self.raises:
            raise self.raises
        p = bare(order.environment, config.repo, config.run_dir / "customer/ui")
        p.stop = self._stop  # type: ignore[method-assign]
        return p

    def _stop(self) -> None:
        self.stops += 1


def trial(config: cfg.Config, raises: Exception | None = None) -> tuple[Trial, Fakes]:
    fake = Fakes(config, raises)
    return Trial(config, prepare=fake), fake


def test_trial_passes_stops_the_service_and_names_the_probe(config: cfg.Config) -> None:
    source = present(config, "s4")
    t, fake = trial(config)
    out = t.liveness(story_of())
    assert out.verdict is Verdict.PASS
    assert out.reason == f"presentation ready; {PROBE_URL} answered"
    assert fake.stops == 1
    assert fake.orders == [Order(DASHBOARD, source)]


def test_trial_without_a_presentation_dir_orders_none(config: cfg.Config) -> None:
    t, fake = trial(config)
    t.liveness(story_of())
    assert fake.orders[0].presentation is None


def test_trial_uses_the_stories_own_environment(config: cfg.Config) -> None:
    config.environments = [Environment("cli", "package"), DASHBOARD]
    t, fake = trial(config)
    t.liveness(story_of(environment="ui"))
    assert fake.orders[0].environment.name == "ui"


def test_trial_bounces_a_service_that_is_not_up(config: cfg.Config) -> None:
    t, _ = trial(config, NotUp("acceptance environment 'ui' did not start: boom"))
    out = t.liveness(story_of())
    assert out.verdict is Verdict.BOUNCE
    assert (
        out.reason
        == "story s4 presentation is not up: acceptance environment 'ui' did not start: boom"
    )


def test_trial_holds_on_a_busy_port(config: cfg.Config) -> None:
    t, _ = trial(config, PortBusy("acceptance environment 'ui' cannot start: busy"))
    out = t.liveness(story_of())
    assert out.verdict is Verdict.HOLD
    assert (
        out.reason
        == "story s4 presentation is not up: acceptance environment 'ui' cannot start: busy"
    )


def test_trial_lets_other_sandbox_errors_propagate(config: cfg.Config) -> None:
    t, _ = trial(config, sandbox.SandboxError("kind"))
    with pytest.raises(sandbox.SandboxError, match="kind"):
        t.liveness(story_of())


def test_trial_verdicts_are_data() -> None:
    assert {NotUp: Verdict.BOUNCE, PortBusy: Verdict.HOLD} == presentation.TRIAL_VERDICTS


def test_trial_never_prepares_a_file_only_environment(config: cfg.Config) -> None:
    config.environments = [Environment("cli", "package")]
    t, fake = trial(config)
    out = t.liveness(story_of())
    assert (out.verdict, out.reason) == (Verdict.PASS, "presentation ready")
    assert fake.orders == []


def test_trial_never_prepares_without_a_environment(config: cfg.Config) -> None:
    config.environments = []
    t, fake = trial(config)
    assert t.liveness(story_of()).verdict is Verdict.PASS and fake.orders == []


def test_trial_default_prepare_is_a_preparers(config: cfg.Config) -> None:
    assert Trial(config).prepare.__self__.__class__ is Preparer  # type: ignore[attr-defined]


# ----- gates ----------------------------------------------------------------


STEPS = list(cfg.PIPELINE_STEPS)
MISSING = "story s4 has no presentation: .team/run/presentation/s4/PRESENTATION.md is missing"


def gate_pipeline(files=None, live=None, steps=STEPS) -> tuple[gates.Pipeline, list[str]]:
    calls: list[str] = []
    made = gates.Checks({"test": "T", "coverage": "C"}, 95.0, FakeRunner())
    made.presentation = files or (lambda _s: None)

    def liveness(story: StoryState) -> gates.Outcome:
        calls.append(story.id)
        return live(story) if live else gates.Outcome(Verdict.PASS, "presentation ready")

    made.liveness = liveness
    return gates.Pipeline(list(steps), 3, made), calls


def test_default_liveness_always_passes() -> None:
    made = gates.Checks({}, 95.0, FakeRunner())
    out = made.liveness(story_of())
    assert (out.verdict, out.reason) == (Verdict.PASS, gates.READY)
    assert gates.READY == "presentation ready"


def test_missing_files_bounce_without_starting_anything() -> None:
    p, calls = gate_pipeline(files=lambda _s: MISSING)
    out = p.checks.presented(story_of())
    assert (out.verdict, out.reason) == (Verdict.BOUNCE, MISSING) and calls == []


def test_complete_files_then_the_liveness_outcome_decides() -> None:
    live = gates.Outcome(Verdict.PASS, "presentation ready; u answered")
    p, calls = gate_pipeline(live=lambda _s: live)
    assert p.checks.presented(story_of()) is live and calls == ["s4"]


def test_e2e_done_with_a_service_that_is_not_up_bounces_to_e2e_and_counts_a_round() -> None:
    reason = "story s4 presentation is not up: acceptance environment 'dashboard' did not start: x"
    p, _ = gate_pipeline(live=lambda _s: gates.Outcome(Verdict.BOUNCE, reason))
    s = story_of("e2e")
    out = p.evaluate(s, Handoff("done"))
    assert (out.verdict, out.bounce_to, out.reason) == (Verdict.BOUNCE, "e2e", reason)
    p.advance(s, out)
    assert (s.step, s.rounds) == ("e2e", 1)


def test_e2e_done_on_a_busy_port_holds_without_a_round() -> None:
    p, _ = gate_pipeline(live=lambda _s: gates.Outcome(Verdict.HOLD, "port busy"))
    s = story_of("e2e")
    out = p.evaluate(s, Handoff("done"))
    assert out.verdict is Verdict.HOLD and out.reason == "port busy"
    p.advance(s, out)
    assert (s.step, s.rounds) == ("e2e", 0)


def test_e2e_done_with_a_live_service_goes_to_acceptance() -> None:
    p, calls = gate_pipeline()
    s = story_of("e2e")
    out = p.evaluate(s, Handoff("done"))
    p.advance(s, out)
    assert out.verdict is Verdict.PASS and s.step == "acceptance" and calls == ["s4"]


def test_liveness_is_not_consulted_without_an_acceptance_step() -> None:
    steps = [x for x in STEPS if x != "acceptance"]
    p, calls = gate_pipeline(live=lambda _s: gates.Outcome(Verdict.BOUNCE, "x"), steps=steps)
    assert p.evaluate(story_of("e2e"), Handoff("done")).verdict is Verdict.PASS
    assert calls == []


def test_liveness_is_not_consulted_at_other_steps_or_for_changes_requested() -> None:
    p, calls = gate_pipeline(live=lambda _s: gates.Outcome(Verdict.BOUNCE, "x"))
    assert p.evaluate(story_of("review"), Handoff("done")).verdict is Verdict.PASS
    p.evaluate(story_of("e2e"), Handoff("changes_requested", next_role="developer-cli"))
    assert calls == []


def test_return_to_e2e_builds_the_return_outcome() -> None:
    p, _ = gate_pipeline()
    out = p.return_to_e2e("it is down")
    assert (out.verdict, out.bounce_to) == (Verdict.RETURN, "e2e")
    assert out.reason == "it is down; run the integration-tester on it"
    steps = [x for x in STEPS if x != "e2e"]
    assert gate_pipeline(steps=steps)[0].return_to_e2e("it is down") is None


def test_unpresented_never_runs_the_trial() -> None:
    p, calls = gate_pipeline(files=lambda _s: MISSING)
    out = p.unpresented(story_of("acceptance"))
    assert (
        out.verdict is Verdict.RETURN
        and out.reason == f"{MISSING}; run the integration-tester on it"
    )
    p2, calls2 = gate_pipeline()
    assert p2.unpresented(story_of("acceptance")) is None
    assert calls == [] and calls2 == []


# ----- L11: the Proxy step --------------------------------------------------


def run(rt, role, story="s1"):
    return asyncio.run(rt.run_role(StepRequest(role, "go", story)))


def open_acceptance(rt) -> StoryState:
    rt.state.stories["s1"] = StoryState("s1", "Add todo", "acceptance", sprint=1, rounds=1)
    present(rt.config, "s1")
    return rt.state.stories["s1"]


def failing_prepare(exc: Exception, calls: list[Any] | None = None):
    def prepare(config, order):
        if calls is not None:
            calls.append(order)
        raise exc

    return prepare


def test_a_service_that_is_not_up_returns_the_story_to_e2e_without_a_round(make_runtime) -> None:
    q, calls = FakeQuery(), []
    exc = NotUp(
        "acceptance environment 'cli' did not start: the start command exited with code 1 ..."
    )
    rt = make_runtime(q, prepare_fn=failing_prepare(exc, calls))
    s = open_acceptance(rt)
    report = run(rt, "customer-proxy")
    assert (report["status"], report["role"]) == ("returned", "customer-proxy")
    assert report["reason"] == f"{exc}; run the integration-tester on it"
    assert report["gate"]["verdict"] == "return" and report["gate"]["now_at"] == "e2e"
    assert (s.step, s.rounds, s.status) == ("e2e", 1, StoryStatus.ACTIVE)
    assert q.calls == [] and rt.ledger.total() == 0 and len(calls) == 1
    [event] = [e for e in rt.events.events() if e.kind == "gate"]
    assert event.data["verdict"] == "return" and event.story == "s1"


def test_the_return_is_saved(make_runtime) -> None:
    from agile_team import state as state_mod

    rt = make_runtime(prepare_fn=failing_prepare(NotUp("down")))
    open_acceptance(rt)
    run(rt, "customer-proxy")
    assert state_mod.load(rt.config.run_dir).stories["s1"].step == "e2e"


def test_a_service_that_is_not_up_with_no_e2e_step_is_refused(make_runtime) -> None:
    rt = make_runtime(prepare_fn=failing_prepare(NotUp("down")))
    rt.pipeline.steps = [x for x in rt.pipeline.steps if x != "e2e"]
    s = open_acceptance(rt)
    report = run(rt, "customer-proxy")
    assert report["status"] == "refused" and "down" in report["reason"]
    assert s.step == "acceptance"


def test_a_busy_port_is_refused_not_returned(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q, prepare_fn=failing_prepare(PortBusy("port busy")))
    s = open_acceptance(rt)
    report = run(rt, "customer-proxy")
    assert report["status"] == "refused" and "port busy" in report["reason"]
    assert (s.step, s.rounds) == ("acceptance", 1) and q.calls == []


def test_other_sandbox_errors_are_refused(make_runtime) -> None:
    rt = make_runtime(prepare_fn=failing_prepare(sandbox.SandboxError("bad kind")))
    open_acceptance(rt)
    assert run(rt, "customer-proxy")["status"] == "refused"


def prepared_probe(rt, stops: list[int]):
    def prepare(config, order):
        p = bare(order.environment, config.repo, config.run_dir / "customer/cli")
        p.stop = lambda: stops.append(1)  # type: ignore[method-assign]
        return p

    return prepare


class Exploding:
    def __call__(self, *, prompt: str, options):
        async def gen():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        return gen()


def test_the_service_is_stopped_when_the_proxy_query_crashes(make_runtime) -> None:
    stops: list[int] = []
    rt = make_runtime(Exploding(), prepare_fn=lambda c, o: prepared_probe(rt, stops)(c, o))
    open_acceptance(rt)
    with pytest.raises(RuntimeError, match="boom"):
        run(rt, "customer-proxy")
    assert stops


def test_the_service_is_stopped_after_a_normal_proxy_step(make_runtime) -> None:
    stops: list[int] = []
    rt = make_runtime(FakeQuery(), prepare_fn=lambda c, o: prepared_probe(rt, stops)(c, o))
    open_acceptance(rt)
    assert run(rt, "customer-proxy")["status"] == "done"
    assert stops


@pytest.mark.parametrize("exc", [RuntimeError("planning broke"), sandbox.SandboxError("fit")])
def test_the_service_is_stopped_when_planning_fails_after_prepare(make_runtime, exc) -> None:
    stops: list[int] = []
    q = FakeQuery()
    rt = make_runtime(q, prepare_fn=lambda c, o: prepared_probe(rt, stops)(c, o))
    open_acceptance(rt)

    def broken(_plan) -> None:
        raise exc

    rt._fit_role_to_environment = broken  # type: ignore[method-assign]
    if isinstance(exc, sandbox.SandboxError):
        assert run(rt, "customer-proxy")["status"] == "refused"
    else:
        with pytest.raises(RuntimeError, match="planning broke"):
            run(rt, "customer-proxy")
    assert stops and q.calls == []


# ----- L12: the hold hand-over ----------------------------------------------


def held(status: str = "done", reason: str = "x") -> dict:
    gate = {"verdict": "hold", "reason": reason, "story_status": "active"}
    return {"status": status, "role": "integration-tester", "gate": gate}


def test_gate_hold_trigger_value_and_row() -> None:
    assert handover.Trigger.GATE_HOLD.value == "gate_hold"
    assert [r.trigger for r in handover.HANDOVERS].index(handover.Trigger.GATE_HOLD) == [
        r.trigger for r in handover.HANDOVERS
    ].index(handover.Trigger.STOPPED) + 1


def test_a_held_gate_hands_over_with_its_reason() -> None:
    assert handover.triggers(held()) == [handover.Trigger.GATE_HOLD]
    assert handover.report_lines(held(reason="port busy"), "s4") == [
        "s4: integration-tester's gate is on hold: port busy; fix it, then continue_story"
    ]
    assert handover.hold_reason(held()) == "gate_hold"


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_a_stopped_handoff_with_a_hold_gives_only_stopped(status: str) -> None:
    assert handover.triggers(held(status)) == [handover.Trigger.STOPPED]


@pytest.mark.parametrize(
    "report",
    [
        {"status": "done", "gate": {"verdict": "pass", "reason": ""}},
        {"status": "done", "gate": {"verdict": "bounce", "reason": "x"}},
        {"status": "done"},
    ],
)
def test_other_gates_do_not_hand_over_as_a_hold(report: dict) -> None:
    assert handover.Trigger.GATE_HOLD not in handover.triggers(report)


def test_gate_reason_field() -> None:
    assert handover.report_fields(held(reason="why"), "s4")["gate_reason"] == "why"
    assert handover.report_fields({}, "s4")["gate_reason"] == ""
    assert handover.report_fields({"gate": {"verdict": "pass"}}, "s4")["gate_reason"] == ""


def test_json_round_trip_of_a_report_still_matches() -> None:
    assert handover.triggers(json.loads(json.dumps(held()))) == [handover.Trigger.GATE_HOLD]


# ----- s105: a failed start names a broken seeded file ----------------------

BAD_NAME = "workspace/.agile-team.toml is broken: "


def seeded_dashboard(config: cfg.Config) -> Environment:
    system.make_dirs(config.repo / "seedsrc")
    system.write_text(config.repo / "seedsrc" / ".agile-team.toml", '[dashboard]\ntoken = "p"\n')
    return Environment("ui", "web", prepare="serve", url=URL, probe="api/snapshot", seed="seedsrc")


def test_broken_seeded_config_leads_the_not_up_reason(config: cfg.Config, fake: FakeSystem) -> None:
    d = seeded_dashboard(config)
    source = present(config, "s1")
    system.write_text(source / "workspace" / ".agile-team.toml", "[dashboard\n")
    fake.reply(("serve",), Done(1, "boom\n"))
    with pytest.raises(NotUp) as info:
        preparer(Probe(None)).prepare(config, Order(d, source))
    first, second = str(info.value).split("\n", 1)
    assert first.startswith(BAD_NAME) and first.endswith("a working one")
    assert second.startswith("acceptance environment 'ui' did not start: ")
    assert "Last output:\nboom" in second


def test_missing_seed_dir_is_named_in_the_not_up_reason(
    config: cfg.Config, fake: FakeSystem
) -> None:
    d = Environment("ui", "web", prepare="serve", url=URL, probe="api/snapshot", seed="gone")
    fake.reply(("serve",), Done(1, "boom\n"))
    with pytest.raises(NotUp) as info:
        preparer(Probe(None)).prepare(config, Order(d))
    expected = [
        "seed directory " + str(config.repo / "gone") + " is missing from the repo; restore it "
        "or remove `seed` from the acceptance environment in .agile-team.toml"
    ]
    assert str(info.value).split("\n")[0] == expected[0]


def test_good_seeded_config_leaves_the_reason_unchanged(
    config: cfg.Config, fake: FakeSystem
) -> None:
    d = seeded_dashboard(config)
    fake.reply(("serve",), Done(1, "boom\n"))
    with pytest.raises(NotUp) as info:
        preparer(Probe(None)).prepare(config, Order(d))
    assert str(info.value).startswith("acceptance environment 'ui' did not start: ")
