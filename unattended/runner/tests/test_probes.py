"""Progress probes: parsing, the readers, and the process-group probes on real processes."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from unattended import probes
from unattended.probes import Context, Reading, Stamp
from unattended.store import LOG_FILE, JobKind

from .conftest import MakeJob, command_spec


@pytest.fixture
def ctx(make_job: MakeJob, workdir: Path) -> Context:
    return Context(make_job(command_spec(workdir, "true")), workdir, Stamp())


def read(text: str, ctx: Context) -> object:
    return probes.build(text, ctx)().value


# ----- parsing ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["output", "cpu", "children", "file:log.txt", "json:a.json:x,y.z", "json:C:/a.json:x",
     "command:git rev-parse HEAD", "command:echo a:b"],
)  # fmt: skip
def test_good_command_probes(text: str) -> None:
    assert probes.problem(text, JobKind.COMMAND) is None


@pytest.mark.parametrize(
    ("text", "job", "message"),
    [
        ("nope", JobKind.COMMAND, "unknown probe 'nope'"),
        ("spend", JobKind.COMMAND, "probe 'spend' does not apply to command jobs"),
        ("cpu", JobKind.PROMPT, "probe 'cpu' does not apply to prompt jobs"),
        ("output:x", JobKind.COMMAND, "probe 'output' takes no argument"),
        ("file", JobKind.PROMPT, "probe 'file' needs an argument"),
        ("json:a.json", JobKind.PROMPT, "probe 'json' needs PATH:KEY[,KEY…]"),
        ("json:a.json:", JobKind.PROMPT, "probe 'json' needs PATH:KEY[,KEY…]"),
        ("json::x", JobKind.PROMPT, "probe 'json' needs PATH:KEY[,KEY…]"),
    ],
)
def test_bad_probes(text: str, job: JobKind, message: str) -> None:
    found = probes.problems(["file:x", text], job)
    assert len(found) == 1 and found[0].startswith(message)


def test_defaults_by_job_kind() -> None:
    assert probes.chosen([], JobKind.COMMAND) == ["output", "cpu"]
    assert probes.chosen([], JobKind.PROMPT) == ["spend"]
    assert probes.chosen(["file:x"], JobKind.PROMPT) == ["file:x"]


# ----- readers ---------------------------------------------------------------------------


def test_output_reads_the_log(ctx: Context) -> None:
    assert read("output", ctx) is None
    ctx.job.path(LOG_FILE).write_text("one\n")
    first = read("output", ctx)
    ctx.job.path(LOG_FILE).write_text("one\ntwo\n")
    assert first is not None and read("output", ctx) != first


def test_spend_reads_the_stamp(ctx: Context) -> None:
    probe = probes.build("spend", ctx)
    ctx.spend.tick()
    assert probe() == Reading(1)


def test_file_is_relative_to_cwd(ctx: Context) -> None:
    assert read("file:ledger", ctx) is None
    (ctx.cwd / "ledger").write_text("x")
    assert read("file:ledger", ctx) is not None


def test_json_reads_dotted_keys(ctx: Context) -> None:
    beat = ctx.cwd / "beat.json"
    probe = probes.build("json:beat.json:step.turn,chore,gone.deeper", ctx)
    assert probe().value == (None, None, None)
    beat.write_text(json.dumps({"at": 1, "step": {"turn": 3}, "chore": "c", "gone": 5}))
    assert probe().value == (3, "c", None)
    beat.write_text("{torn")
    assert probe().value == (None, None, None)


def test_json_ignores_keys_it_was_not_given(ctx: Context) -> None:
    beat = ctx.cwd / "beat.json"
    probe = probes.build("json:beat.json:step.turn", ctx)
    beat.write_text(json.dumps({"at": 1, "step": {"turn": 3}}))
    first = probe()
    beat.write_text(json.dumps({"at": 2, "step": {"turn": 3}}))
    assert probe() == first


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("00:01:05", 65.0), ("1-02:00:00", 93600.0), ("0:01.50", 1.5), ("12:34", 754.0)],
)
def test_cpu_seconds(text: str, seconds: float) -> None:
    assert probes.cpu_seconds(text) == seconds


PS_LINES = """  10    10 00:00:02
  10    11 00:00:03
  20    20 00:01:00
 bad
"""


def test_the_group_is_read_from_ps(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probes, "list_processes", lambda: PS_LINES)
    assert read("cpu", ctx) is None
    ctx.pgid = 10
    assert read("cpu", ctx) == 5.0
    assert read("children", ctx) == frozenset({10, 11})
    ctx.pgid = 30
    assert (read("cpu", ctx), read("children", ctx)) == (None, None)


def test_command_output_is_the_reading(ctx: Context) -> None:
    probe = probes.build("command:cat head", ctx)
    (ctx.cwd / "head").write_text("abc")
    first = probe()
    assert first == probe() == Reading("abc")
    (ctx.cwd / "head").write_text("def")
    assert probe() != first


def test_a_silent_success_is_always_progress(ctx: Context) -> None:
    probe = probes.build("command:true", ctx)
    assert probe() != probe()


def test_a_failing_or_slow_command_reads_nothing(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert read("command:echo x; exit 1", ctx) is None
    monkeypatch.setattr(probes, "COMMAND_TIMEOUT", 0.1)
    assert read("command:sleep 5", ctx) is None


# ----- real processes (bounded) ----------------------------------------------------------


def group_of(command: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(["sh", "-c", command], start_new_session=True)


def test_cpu_moves_for_a_busy_group_and_not_for_a_sleeping_one(ctx: Context) -> None:
    groups = [group_of("while :; do :; done"), group_of("sleep 30 & wait")]

    def cpu() -> list[object]:
        return [probes.cpu_reading(Context(ctx.job, ctx.cwd, Stamp(), g.pid)).value for g in groups]

    try:
        before = cpu()
        time.sleep(2.2)
        after = cpu()
    finally:
        for proc in groups:
            os.killpg(proc.pid, 9)
            proc.wait()
    assert after[0] > before[0]
    assert after[1] == before[1]


def test_children_lists_the_group(ctx: Context) -> None:
    proc = group_of("sleep 30 & wait")
    try:
        time.sleep(0.2)
        ctx.pgid = proc.pid
        members = read("children", ctx)
    finally:
        os.killpg(proc.pid, 9)
        proc.wait()
    assert isinstance(members, frozenset) and proc.pid in members and len(members) == 2
