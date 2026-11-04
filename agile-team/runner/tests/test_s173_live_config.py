"""s173: runtime and scheduler wiring of the live config, and its hand-over (ADR-0094)."""

from __future__ import annotations

import asyncio
import copy

from agile_team import handover
from agile_team.config_reload import ConfigChange
from agile_team.events import EventKind
from agile_team.handover import Scope, Trigger

from .test_config_reload import SHA, config_text, configs, watched, with_env
from .test_s159_scheduler import scheduler

BAD = ConfigChange(SHA, "bad", [], "boom: broken")
GOOD = ConfigChange(SHA, "ok", ["environment"], "")


def bad_runtime(make_runtime, head: str = "bad"):
    rt = watched(make_runtime, {"bad": "[team\n", "ok": with_env("cli", "house-rules")}, "b1")
    rt.git.head = head  # type: ignore[attr-defined]
    return rt


# ---------- Runtime.update_config ----------


def test_update_config_takes_a_new_blob_s173(make_runtime) -> None:
    rt = bad_runtime(make_runtime, "ok")
    change = rt.update_config()
    assert change is not None and change.sections == ["environment"]
    assert "house-rules" in [e.name for e in rt.config.environments]


def test_update_config_reads_nothing_in_a_story_view_s173(make_runtime) -> None:
    rt = bad_runtime(make_runtime, "ok")
    rt.worktree_of = "s1"
    assert rt.update_config() is None
    assert configs(rt) == [] and rt.git.calls == []  # type: ignore[attr-defined]


def test_update_config_waits_while_the_main_lock_is_held_s173(make_runtime) -> None:
    async def scenario() -> None:
        rt = bad_runtime(make_runtime, "ok")
        rt.main_lock = asyncio.Lock()
        async with rt.main_lock:
            assert rt.update_config() is None
            assert configs(rt) == []
        assert rt.update_config() is not None

    asyncio.run(scenario())


def test_a_view_made_before_the_swap_keeps_its_config_s173(make_runtime) -> None:
    rt = bad_runtime(make_runtime, "ok")
    before = copy.copy(rt)
    old = (before.config, before.pipeline, before.book, before.shell)
    rt.update_config()
    assert (before.config, before.pipeline, before.book, before.shell) == old
    after = copy.copy(rt)
    assert after.config is rt.config and after.config is not before.config
    assert [e.name for e in before.config.environments] == ["cli"]


def test_the_default_live_parts_keep_book_providers_and_shell_s173(make_runtime) -> None:
    rt = bad_runtime(make_runtime, "ok")
    book, providers, shell = rt.book, rt.providers, rt.shell
    rt.update_config()
    assert (rt.book, rt.providers, rt.shell) == (book, providers, shell)


def test_the_story_intake_reads_the_new_environments_s173(make_runtime) -> None:
    rt = bad_runtime(make_runtime, "ok")
    rt.update_config()
    assert "house-rules" in {e.name for e in rt.config.environments}


# ---------- Scheduler ----------


def fake_update(rt, change: ConfigChange | None):
    calls: list[int] = []
    rt.update_config = lambda: calls.append(1) or change  # type: ignore[method-assign]
    return calls


def test_a_tick_takes_the_config_before_the_queues_s173(make_runtime) -> None:
    rt, s = scheduler(make_runtime)
    order: list[str] = []
    rt.update_config = lambda: order.append("config")  # type: ignore[method-assign]
    s.router.apply_queues = lambda: order.append("queues")  # type: ignore[method-assign]
    s.tick()
    assert order[:2] == ["config", "queues"]


def test_a_tick_does_not_check_while_a_step_holds_the_main_checkout_s173(make_runtime) -> None:
    async def scenario() -> None:
        rt, s = scheduler(make_runtime)
        calls = fake_update(rt, None)
        async with s.main_lock:
            s.tick()
        assert calls == []

    asyncio.run(scenario())


def test_a_refused_config_found_in_a_tick_is_queued_for_the_po_s173(make_runtime) -> None:
    rt, s = scheduler(make_runtime)
    fake_update(rt, BAD)
    queued: list = []
    s.queue_pass = queued.append  # type: ignore[method-assign]
    s.tick()
    (found,) = queued
    assert found.kinds == [Trigger.CONFIG_INVALID] and found.stories == []
    assert "boom: broken" in "\n".join(found.lines)


def test_a_taken_config_in_a_tick_queues_nothing_s173(make_runtime) -> None:
    rt, s = scheduler(make_runtime)
    fake_update(rt, GOOD)
    queued: list = []
    s.queue_pass = queued.append  # type: ignore[method-assign]
    s.tick()
    assert queued == []


def test_a_step_that_committed_the_bad_config_gets_it_in_its_report_s173(make_runtime) -> None:
    rt, s = scheduler(make_runtime)
    fake_update(rt, BAD)
    report = s.add_config_change({"status": "done", "commit": SHA})
    assert report["config"] == BAD.data and report["status"] == "done"


def test_a_bad_config_from_another_commit_is_queued_not_reported_s173(make_runtime) -> None:
    rt, s = scheduler(make_runtime)
    fake_update(rt, BAD)
    queued: list = []
    s.queue_pass = queued.append  # type: ignore[method-assign]
    report = s.add_config_change({"status": "done", "commit": "other"})
    assert "config" not in report and len(queued) == 1


def test_a_taken_config_leaves_the_report_unchanged_s173(make_runtime) -> None:
    rt, s = scheduler(make_runtime)
    fake_update(rt, GOOD)
    report = {"status": "done", "commit": SHA}
    assert s.add_config_change(report) == report


def test_no_change_leaves_the_report_unchanged_s173(make_runtime) -> None:
    rt, s = scheduler(make_runtime)
    fake_update(rt, None)
    assert s.add_config_change({"status": "done"}) == {"status": "done"}


def test_no_check_is_made_while_queues_may_not_apply_s173(make_runtime) -> None:
    async def scenario() -> None:
        rt, s = scheduler(make_runtime)
        calls = fake_update(rt, BAD)
        async with s.main_lock:
            assert s.add_config_change({"status": "done", "commit": SHA}) == {
                "status": "done",
                "commit": SHA,
            }
        assert calls == []

    asyncio.run(scenario())


def test_a_dispatch_exception_makes_no_config_check_s173(make_runtime) -> None:
    from agile_team.router import Work

    from .test_s159_scheduler import story

    async def scenario() -> None:
        rt, s = scheduler(make_runtime)
        calls = fake_update(rt, None)

        async def boom(work):
            raise RuntimeError("x")

        s.dispatch = boom  # type: ignore[method-assign]
        await s.run_work(Work("developer-cli", story("s1"), "b", None))  # type: ignore[arg-type]
        assert calls == []

    asyncio.run(scenario())


# ---------- hand-over ----------


def test_config_invalid_is_a_quiet_story_scope_trigger_s173() -> None:
    assert Trigger.CONFIG_INVALID == "config_invalid"
    assert Trigger.CONFIG_INVALID in handover.UNHELD
    assert Trigger.CONFIG_INVALID not in handover.RUN_WIDE
    assert handover.SCOPES[Trigger.CONFIG_INVALID] is Scope.STORY


def test_a_report_with_a_config_error_triggers_config_invalid_s173() -> None:
    assert handover.triggers({"status": "done", "config": BAD.data}) == [Trigger.CONFIG_INVALID]


def test_a_taken_config_triggers_nothing_s173() -> None:
    assert handover.triggers({"status": "done", "config": GOOD.data}) == []


def test_the_hand_over_names_the_short_sha_and_the_error_s173() -> None:
    (line,) = handover.report_lines({"config": BAD.data}, None)
    assert SHA[:8] in line and SHA[:9] not in line and "boom: broken" in line
    assert "Nothing is held" in line


def test_a_config_error_holds_nothing_s173() -> None:
    assert handover.hold_reason({"config": BAD.data}) is None


def test_the_config_event_kind_is_config_s173() -> None:
    assert EventKind.CONFIG == "config"


def test_config_text_helper_is_valid_toml_s173() -> None:
    assert "environment" in config_text()


# ---------- cli ----------


def test_build_live_config_returns_the_parts_s173(configured, key_home) -> None:
    from agile_team import cli
    from agile_team import config as config_mod

    config = config_mod.load(configured)
    live = cli.build_live_config(cli.Place(configured, key_home), config)
    assert live.config is config and live.pipeline is not None and live.book is not None


def test_build_live_config_lists_every_problem_s173(configured, key_home) -> None:
    import pytest
    from agile_team import cli
    from agile_team import config as config_mod

    config = config_mod.load(configured)
    config.team.budget_usd = -1
    with pytest.raises(config_mod.ConfigError, match="budget_usd"):
        cli.build_live_config(cli.Place(configured, key_home), config)


def test_make_runtime_sets_the_blob_and_the_live_builder_s173(configured, key_home) -> None:
    from agile_team import cli

    from .conftest import FakeQuery

    rt = cli.make_runtime(cli.Place(configured, key_home), FakeQuery())
    assert rt.live_for is not None and rt.config_blob is not None
