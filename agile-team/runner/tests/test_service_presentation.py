"""s26: a presentation starts the delivery; "presentation ready" needs it up and answering."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, gates, handover, presentation, sandbox
from agile_team import config as cfg
from agile_team.config import Delivery
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState, StoryStatus, Verdict
from agile_team.presentation import Check, Need, Recipe, Trial
from agile_team.roles import Handoff
from agile_team.sandbox import NotUp, Order, PortBusy, Preparer, Start

from .conftest import FakeQuery, FakeRunner, present

PORT = 8799
URL = f"http://127.0.0.1:{PORT}/"
PROBE_URL = URL + "api/snapshot"
DASHBOARD = Delivery(
    "ui",
    "web",
    prepare="serve --host {host} --port {port} --repo {sandbox}/presentation/workspace",
    url=URL,
    probe="api/snapshot",
)


# ----- fakes ----------------------------------------------------------------


class FakeProcess:
    """A stand-in for ``Popen`` whose exit code the test chooses."""

    def __init__(self, returncode: int | None = None):
        self.pid = 4_000_001
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


class FakePopen:
    """Records the launch; may write ``output`` into the log the runner handed over."""

    def __init__(self, process: FakeProcess | None = None, output: bytes = b""):
        self.process = process or FakeProcess()
        self.output = output
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.seen: list[Any] = []

    def __call__(self, command: str, **kw: Any) -> FakeProcess:
        self.calls.append((command, kw))
        if kw.get("stdout") is not None and self.output:
            kw["stdout"].write(self.output)
            kw["stdout"].flush()
        return self.process


class Probe:
    """A probe that answers true from its ``up_on``-th call on (never when ``None``)."""

    def __init__(self, up_on: int | None = 1):
        self.up_on = up_on
        self.urls: list[str] = []

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        return self.up_on is not None and len(self.urls) >= self.up_on


def preparer(popen: Any = None, probe: Any = None, *, busy: bool = False, **kw: Any) -> Preparer:
    sleeps: list[float] = []
    made = Preparer(
        popen=popen or FakePopen(),
        probe=probe or Probe(),
        listening=lambda _h, _p: busy,
        sleep=sleeps.append,
        **kw,
    )
    made.slept = sleeps  # type: ignore[attr-defined]
    return made


@pytest.fixture
def config(configured: Path) -> cfg.Config:
    c = cfg.load(configured)
    c.deliveries = [DASHBOARD]
    return c


@pytest.fixture
def stopped(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replace group signalling so a fake pid never reaches a real process."""
    sent: list[int] = []
    monkeypatch.setattr(sandbox, "_signal_group", lambda _proc, sig: sent.append(sig))
    return sent


def pid_file(config: cfg.Config) -> Path:
    return config.run_dir / "customer/ui.pid"


def log_file(config: cfg.Config) -> Path:
    return config.run_dir / "customer/ui.log"


def story_of(step: str = "e2e", story_id: str = "s4", **kw: Any) -> StoryState:
    kw.setdefault("sprint", 1)
    return StoryState(story_id, "A story", step, **kw)


# ----- config ---------------------------------------------------------------


def test_delivery_probe_defaults_to_empty_and_is_the_last_field() -> None:
    assert Delivery("a", "web").probe == ""
    assert list(Delivery.__dataclass_fields__)[-1] == "probe"


def test_probe_is_read_from_the_toml(configured: Path) -> None:
    toml = (configured / ".agile-team.toml").read_text()
    toml += '\n[[delivery]]\nname = "ui"\nkind = "web"\nurl = "http://h/"\nprobe = "api/x"\n'
    (configured / ".agile-team.toml").write_text(toml)
    assert cfg.load(configured).delivery("ui").probe == "api/x"


# ----- L1 / L2: placeholders ------------------------------------------------


def test_constants() -> None:
    assert sandbox.PROBE_ATTEMPTS == 120
    assert sandbox.PROBE_EVERY_S == 0.25
    assert sandbox.PROBE_TIMEOUT_S == 2
    assert sandbox.STOP_WAIT_S == 10
    assert sandbox.LOG_TAIL_LINES == 20
    assert sandbox.DEFAULT_PORTS == {"http": 80, "https": 443}


def bare(delivery: Delivery, repo: Path, root: Path) -> sandbox.Prepared:
    return sandbox.Prepared(delivery, sandbox.DELIVERY_KINDS["web"], repo, root, root)


def test_expand_makes_repo_and_sandbox_absolute(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = bare(DASHBOARD, Path("."), Path(".team/run/customer/ui"))
    out = p.expand("{repo}|{sandbox}")
    repo, box = out.split("|")
    assert Path(repo).is_absolute() and Path(box).is_absolute()
    assert repo == str(tmp_path.resolve())
    assert box == str((tmp_path / ".team/run/customer/ui").resolve())


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
    p = bare(Delivery("ui", "web", url=url), Path("."), Path("."))
    assert p.expand("{host}:{port}") == f"{host}:{port}"


def test_address_probe_url_and_service_files(tmp_path: Path) -> None:
    root = tmp_path / "customer" / "ui"
    p = bare(DASHBOARD, tmp_path, root)
    assert p.address() == ("127.0.0.1", 8799)
    assert p.probe_url() == PROBE_URL
    assert p.pid_file() == tmp_path / "customer/ui.pid"
    assert p.log_file() == tmp_path / "customer/ui.log"
    assert bare(Delivery("ui", "web", url=URL), tmp_path, root).probe_url() == URL


def test_cli_resolves_the_repo_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(repo=".", home=str(tmp_path / "h"))
    assert cli.repo_of(args) == tmp_path.resolve()
    assert cli.Place.of(args).repo == tmp_path.resolve()
    assert cli.Place.of(args).repo.is_absolute()


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
        background = sandbox.DELIVERY_KINDS[kind].start is Start.BACKGROUND
        assert (recipe.check is Check.SERVICE) is background


def test_recipe_of_reads_the_delivery(config: cfg.Config) -> None:
    config.deliveries = [Delivery("cli", "package"), DASHBOARD]
    assert presentation.recipe_of(config, story_of(delivery="ui")).check is Check.SERVICE
    assert presentation.recipe_of(config, story_of()).check is Check.FILES
    config.deliveries = []
    assert presentation.recipe_of(config, story_of()) == Recipe(Need.GUIDE_ONLY)


def test_presented_source(config: cfg.Config) -> None:
    assert presentation.presented_source(config, None) is None
    assert presentation.presented_source(config, story_of()) is None
    source = present(config, "s4")
    assert presentation.presented_source(config, story_of()) == source


# ----- L4 / L5: start and probe ---------------------------------------------


def test_prepare_starts_the_service_and_waits_for_the_probe(config: cfg.Config) -> None:
    popen, probe = FakePopen(), Probe(up_on=3)
    made = preparer(popen, probe)
    seen_copy: list[bool] = []

    def spying(command: str, **kw: Any) -> FakeProcess:
        seen_copy.append((config.run_dir / "customer/ui/presentation/workspace/todo.txt").exists())
        return popen(command, **kw)

    made.popen = spying
    p = made.prepare(config, Order(DASHBOARD, present(config, "s4")))
    assert probe.urls == [PROBE_URL] * 3 and made.slept == [sandbox.PROBE_EVERY_S] * 2  # type: ignore[attr-defined]
    assert seen_copy == [True]
    command, kw = popen.calls[0]
    assert "--host 127.0.0.1 --port 8799" in command
    assert f"--repo {p.root}/presentation/workspace" in command
    assert kw["start_new_session"] is True and kw["shell"] is True
    assert kw["cwd"] == config.repo and kw["stderr"] == subprocess.STDOUT
    assert p.process is popen.process
    assert pid_file(config).is_file() and log_file(config).is_file()


def test_prepare_with_a_relative_repo_still_gives_absolute_paths(
    config: cfg.Config, monkeypatch
) -> None:
    monkeypatch.chdir(config.repo)
    config.repo = Path(".")
    popen = FakePopen()
    preparer(popen).prepare(config, Order(DASHBOARD))
    command = popen.calls[0][0]
    assert "--repo ." not in command and f"--repo {Path('.team').resolve().parent}" in command


def test_prepare_runs_a_real_service_with_pid_and_log(config: cfg.Config) -> None:
    d = Delivery("ui", "web", prepare="echo hello; exec sleep 60", url=URL)
    config.deliveries = [d]
    made = Preparer(probe=Probe(), listening=lambda _h, _p: False, sleep=lambda _s: None)
    p = made.prepare(config, Order(d))
    try:
        assert p.process.poll() is None
        assert pid_file(config).read_text().strip() == str(os.getpgid(p.process.pid))
    finally:
        p.stop()
    assert not pid_file(config).exists()
    assert "hello" in log_file(config).read_text()


def test_the_log_is_truncated_at_each_start(config: cfg.Config) -> None:
    d = Delivery("ui", "web", url=URL, prepare="echo first")
    config.deliveries = [d]
    made = Preparer(probe=Probe(), listening=lambda _h, _p: False, sleep=lambda _s: None)
    first = made.prepare(config, Order(d))
    first.process.wait()
    d.prepare = "echo second"
    second = made.prepare(config, Order(d))
    second.process.wait()
    text = log_file(config).read_text()
    assert "second" in text and "first" not in text


def test_service_files_sit_beside_the_sandbox_not_inside_it(config: cfg.Config) -> None:
    p = preparer().prepare(config, Order(DASHBOARD))
    assert p.root == config.run_dir / "customer/ui"
    assert pid_file(config).parent == p.root.parent
    assert not any(f.suffix in {".pid", ".log"} for f in p.root.rglob("*"))


def test_background_delivery_without_a_command_is_still_probed(config: cfg.Config) -> None:
    d = Delivery("ui", "web", url=URL, probe="api/snapshot")
    popen, probe = FakePopen(), Probe()
    p = preparer(popen, probe).prepare(config, Order(d))
    assert popen.calls == [] and p.process is None and probe.urls == [PROBE_URL]


def test_background_delivery_without_a_command_that_never_answers_is_not_up(
    config: cfg.Config,
) -> None:
    d = Delivery("ui", "web", url=URL, probe="api/snapshot")
    with pytest.raises(NotUp, match="did not answer"):
        preparer(probe=Probe(None), attempts=2).prepare(config, Order(d))


def test_exited_process_fails_at_once_with_the_output(config: cfg.Config, stopped) -> None:
    popen = FakePopen(FakeProcess(1), b"first\nagile-team dashboard: .agile-team.toml not found\n")
    probe = Probe(None)
    with pytest.raises(NotUp) as info:
        preparer(popen, probe).prepare(config, Order(DASHBOARD))
    assert len(probe.urls) == 1
    text = str(info.value)
    assert text.startswith(
        "delivery 'ui' did not start: the start command exited with code 1 "
        f"before {PROBE_URL} answered. Last output:\n"
    )
    assert "agile-team dashboard: .agile-team.toml not found" in text
    assert not pid_file(config).exists()


def test_a_service_that_never_answers_is_stopped_and_reported(config: cfg.Config, stopped) -> None:
    process = FakeProcess(None)
    popen = FakePopen(process, b"warming up\n")
    probe = Probe(None)
    made = preparer(popen, probe, attempts=3)
    with pytest.raises(NotUp) as info:
        made.prepare(config, Order(DASHBOARD))
    assert len(probe.urls) == 3
    assert str(info.value).startswith(
        f"delivery 'ui' did not answer {PROBE_URL} within 0.75s. Last output:\n"
    )
    assert "warming up" in str(info.value)
    assert stopped and stopped[0] == signal.SIGTERM
    assert not pid_file(config).exists()


def test_empty_log_reads_no_output(config: cfg.Config, stopped) -> None:
    with pytest.raises(NotUp, match=r"Last output:\n\(no output\)"):
        preparer(FakePopen(FakeProcess(2)), Probe(None)).prepare(config, Order(DASHBOARD))


def test_only_the_last_twenty_log_lines_are_quoted(config: cfg.Config, stopped) -> None:
    lines = b"".join(b"line%02d\n" % i for i in range(30))
    with pytest.raises(NotUp) as info:
        preparer(FakePopen(FakeProcess(3), lines), Probe(None)).prepare(config, Order(DASHBOARD))
    text = str(info.value)
    assert "line29" in text and "line10" in text
    assert "line09" not in text and "line00" not in text


def test_foreground_kinds_are_unchanged(configured: Path) -> None:
    d = Delivery("cli", "package", prepare="exit 3")
    probe = Probe()
    with pytest.raises(sandbox.SandboxError, match="prepare"):
        preparer(probe=probe).prepare(cfg.load(configured), Order(d))
    assert probe.urls == []


def test_not_up_and_port_busy_are_sandbox_errors() -> None:
    assert issubclass(NotUp, sandbox.SandboxError) and issubclass(PortBusy, sandbox.SandboxError)
    assert not issubclass(NotUp, PortBusy) and not issubclass(PortBusy, NotUp)


# ----- L8: port conflict ----------------------------------------------------


def test_a_busy_port_is_refused_before_anything_starts(config: cfg.Config) -> None:
    popen = FakePopen()
    with pytest.raises(PortBusy) as info:
        preparer(popen, busy=True).prepare(config, Order(DASHBOARD))
    assert str(info.value) == (
        "delivery 'ui' cannot start: 127.0.0.1:8799 is already in use by a process "
        "the runner did not start; stop it or change the delivery's url"
    )
    assert popen.calls == []


def test_port_in_use_sees_a_listening_socket() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert sandbox.port_in_use("127.0.0.1", port) is True
    assert sandbox.port_in_use("127.0.0.1", port) is False


# ----- L5: http_answers -----------------------------------------------------


def serve(status: int, body: bytes, ctype: str) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize(
    ("status", "body", "ctype", "answers"),
    [
        (200, b'{"a": 1}', "application/json", True),
        (200, b"<html></html>", "text/html", True),
        (200, b"not json", "application/json", False),
        (500, b'{"a": 1}', "application/json", False),
        (404, b"no", "text/plain", False),
    ],
)
def test_http_answers(status: int, body: bytes, ctype: str, answers: bool) -> None:
    server = serve(status, body, ctype)
    try:
        assert sandbox.http_answers(f"http://127.0.0.1:{server.server_port}/x") is answers
    finally:
        server.shutdown()
        server.server_close()


def test_http_answers_is_false_when_nothing_listens() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert sandbox.http_answers(f"http://127.0.0.1:{port}/") is False


def test_http_answers_is_false_for_a_bad_url() -> None:
    assert sandbox.http_answers("") is False
    assert sandbox.http_answers("not a url") is False


# ----- L7: stale services ---------------------------------------------------


def reaped(process: subprocess.Popen) -> subprocess.Popen:
    """Reap ``process`` in the background so a killed group does not linger as a zombie."""
    threading.Thread(target=process.wait, daemon=True).start()
    return process


def test_stop_stale_ends_a_leftover_service(tmp_path: Path) -> None:
    root = tmp_path / "customer" / "ui"
    root.mkdir(parents=True)
    proc = reaped(subprocess.Popen(["sleep", "60"], start_new_session=True))
    root.with_suffix(".pid").write_text(str(proc.pid))
    sandbox.stop_stale(root)
    assert proc.wait(timeout=5) != 0
    assert not root.with_suffix(".pid").exists()


def test_stop_stale_with_a_dead_pid_just_removes_the_file(tmp_path: Path) -> None:
    root = tmp_path / "customer" / "ui"
    root.mkdir(parents=True)
    done = subprocess.Popen(["true"])
    done.wait()
    root.with_suffix(".pid").write_text(str(done.pid))
    sandbox.stop_stale(root)
    assert not root.with_suffix(".pid").exists()


def test_stop_stale_without_a_pid_file_does_nothing(tmp_path: Path) -> None:
    sandbox.stop_stale(tmp_path / "customer" / "ui")


def test_stop_stale_never_signals_a_process_that_is_not_a_group_leader(tmp_path: Path) -> None:
    root = tmp_path / "customer" / "ui"
    root.mkdir(parents=True)
    other = reaped(subprocess.Popen(["sleep", "60"]))  # shares the test's group
    try:
        root.with_suffix(".pid").write_text(str(other.pid))
        sandbox.stop_stale(root)
        assert other.poll() is None
        assert not root.with_suffix(".pid").exists()
    finally:
        other.kill()


def test_prepare_replaces_a_stale_service_before_starting(config: cfg.Config) -> None:
    proc = reaped(subprocess.Popen(["sleep", "60"], start_new_session=True))
    pid_file(config).parent.mkdir(parents=True, exist_ok=True)
    pid_file(config).write_text(str(proc.pid))
    p = preparer().prepare(config, Order(DASHBOARD))
    assert proc.wait(timeout=5) != 0
    assert p.process is not None


# ----- L9: teardown ---------------------------------------------------------


def test_stop_deletes_the_pid_file_and_is_safe_twice(tmp_path: Path) -> None:
    root = tmp_path / "customer" / "ui"
    root.mkdir(parents=True)
    p = bare(DASHBOARD, tmp_path, root)
    p.pid_file().write_text("123")
    p.stop()
    p.stop()
    assert not p.pid_file().exists()


def test_stop_with_a_real_process_ends_the_group_and_the_file(config: cfg.Config) -> None:
    d = Delivery("ui", "web", prepare="exec sleep 60", url=URL)
    config.deliveries = [d]
    p = Preparer(probe=Probe(), listening=lambda _h, _p: False, sleep=lambda _s: None).prepare(
        config, Order(d)
    )
    p.stop()
    assert p.process.poll() is not None and not pid_file(config).exists()


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
        p = bare(order.delivery, config.repo, config.run_dir / "customer/ui")
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


def test_trial_uses_the_stories_own_delivery(config: cfg.Config) -> None:
    config.deliveries = [Delivery("cli", "package"), DASHBOARD]
    t, fake = trial(config)
    t.liveness(story_of(delivery="ui"))
    assert fake.orders[0].delivery.name == "ui"


def test_trial_bounces_a_service_that_is_not_up(config: cfg.Config) -> None:
    t, _ = trial(config, NotUp("delivery 'ui' did not start: boom"))
    out = t.liveness(story_of())
    assert out.verdict is Verdict.BOUNCE
    assert out.reason == "story s4 presentation is not up: delivery 'ui' did not start: boom"


def test_trial_holds_on_a_busy_port(config: cfg.Config) -> None:
    t, _ = trial(config, PortBusy("delivery 'ui' cannot start: busy"))
    out = t.liveness(story_of())
    assert out.verdict is Verdict.HOLD
    assert out.reason == "story s4 presentation is not up: delivery 'ui' cannot start: busy"


def test_trial_lets_other_sandbox_errors_propagate(config: cfg.Config) -> None:
    t, _ = trial(config, sandbox.SandboxError("kind"))
    with pytest.raises(sandbox.SandboxError, match="kind"):
        t.liveness(story_of())


def test_trial_verdicts_are_data() -> None:
    assert {NotUp: Verdict.BOUNCE, PortBusy: Verdict.HOLD} == presentation.TRIAL_VERDICTS


def test_trial_never_prepares_a_file_only_delivery(config: cfg.Config) -> None:
    config.deliveries = [Delivery("cli", "package")]
    t, fake = trial(config)
    out = t.liveness(story_of())
    assert (out.verdict, out.reason) == (Verdict.PASS, "presentation ready")
    assert fake.orders == []


def test_trial_never_prepares_without_a_delivery(config: cfg.Config) -> None:
    config.deliveries = []
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
    reason = "story s4 presentation is not up: delivery 'dashboard' did not start: x"
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
    exc = NotUp("delivery 'cli' did not start: the start command exited with code 1 ...")
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
        p = bare(order.delivery, config.repo, config.run_dir / "customer/cli")
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

    rt._fit_role_to_delivery = broken  # type: ignore[method-assign]
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
