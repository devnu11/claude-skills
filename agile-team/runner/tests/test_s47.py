"""s47: a waiting run names what it waits on, and an answer wakes it (W1-W6)."""

import asyncio

import pytest
from agile_team import halt, system
from agile_team.dispatch import halt_note
from agile_team.po_tools import PoRun, Start
from agile_team.relay import WAITING_HEAD, Note
from agile_team.router import Router
from agile_team.state import RunStatus

from .fake_system import FakeSystem
from .pipeline_helpers import Script, add_story, build, handover_events


def q(rt, text="?", stories=()):
    return rt.relay.post(Note("question", text, list(stories)))


# ----- Relay.waits / waiting (W2, W3) -------------------------------------------


def test_no_open_question_means_no_waits(make_runtime) -> None:
    rt = make_runtime()
    assert rt.relay.waits() == [] and rt.relay.waiting() == ""


def test_one_question_names_its_story(make_runtime) -> None:
    rt = make_runtime()
    q(rt, stories=["s40"])
    assert rt.relay.waits() == ["s40 waits on m1"]


def test_stories_and_ids_come_in_outbox_order(make_runtime) -> None:
    rt = make_runtime()
    q(rt, stories=["s40"])
    q(rt, stories=["s40", "s41"])
    assert rt.relay.waits() == ["s40 waits on m1, m2", "s41 waits on m2"]


def test_questions_naming_no_story_come_last(make_runtime) -> None:
    rt = make_runtime()
    q(rt)
    q(rt, stories=["s1"])
    q(rt)
    assert rt.relay.waits() == ["s1 waits on m2", "the run waits on m1, m3"]


def test_answered_questions_are_excluded(make_runtime) -> None:
    rt = make_runtime()
    q(rt, stories=["s1"])
    q(rt, stories=["s1"])
    rt.relay.answer("m1", "a")
    assert rt.relay.waits() == ["s1 waits on m2"]


def test_a_story_named_twice_is_listed_once(make_runtime) -> None:
    rt = make_runtime()
    q(rt, stories=["s1", "s1"])
    assert rt.relay.waits() == ["s1 waits on m1"]


def test_waiting_joins_the_lines(make_runtime) -> None:
    rt = make_runtime()
    q(rt, stories=["s40"])
    q(rt)
    assert rt.relay.waiting() == "waiting on answers: s40 waits on m1; the run waits on m2"
    assert WAITING_HEAD == "waiting on answers: "


# ----- the router shows the wait (W3, W4) ---------------------------------------


def waiting_rt(make_runtime):
    rt = make_runtime()
    add_story(rt, "s1", "implement")
    q(rt, "Which DB?", ["s1"])
    rt.state.delivered = []
    rt.record_checkout()  # s61: else the first tick records it and saves once more
    return rt


def test_the_wait_is_shown_then_cleared(make_runtime, fake: FakeSystem) -> None:
    rt = waiting_rt(make_runtime)
    seen = []

    def sleep() -> None:
        seen.append((rt.state.status, rt.state.status_reason))
        rt.relay.answer("m1", "sqlite")

    fake.on_sleep = [sleep]
    status = rt.state.status
    asyncio.run(Router(rt).advance())
    assert seen == [(status, "waiting on answers: s1 waits on m1")]
    assert rt.state.status is status and rt.state.status_reason is None


def test_the_reason_is_saved_and_a_new_question_updates_it(make_runtime, fake: FakeSystem) -> None:
    import json

    rt = waiting_rt(make_runtime)
    seen = []

    def poll(action) -> None:
        saved = json.loads(system.read_text(rt.config.run_dir / "state.json"))
        seen.append((rt.state.status_reason, saved["status_reason"]))
        action()

    fake.on_sleep = [
        lambda: poll(lambda: None),
        lambda: poll(lambda: q(rt, "Colour?", ["s1"])),
        lambda: poll(lambda: rt.relay.answer("m1", "a")),
    ]
    asyncio.run(Router(rt).advance())
    first = "waiting on answers: s1 waits on m1"
    second = "waiting on answers: s1 waits on m1, m2"
    assert seen == [(first, first), (first, first), (second, second)]


def test_an_unchanged_reason_is_not_saved_again(make_runtime, fake: FakeSystem) -> None:
    rt = waiting_rt(make_runtime)
    saves = []
    real = rt.save
    rt.save = lambda: (saves.append(1), real())[1]
    fake.on_sleep = [lambda: None, lambda: None, lambda: rt.relay.answer("m1", "a")]
    asyncio.run(Router(rt).advance())
    assert len(fake.slept) == 3
    assert len(saves) <= 2  # one to show, one to clear; never one per poll


def test_end_wait_leaves_other_reasons_alone(make_runtime) -> None:
    rt = make_runtime()
    rt.state.mark(RunStatus.RUNNING, "something else")
    Router(rt)._end_wait()
    assert rt.state.status_reason == "something else"


def test_end_wait_clears_a_waiting_reason(make_runtime) -> None:
    rt = make_runtime()
    rt.state.mark(RunStatus.RUNNING, WAITING_HEAD + "s1 waits on m1")
    Router(rt)._end_wait()
    assert rt.state.status_reason is None and rt.state.status is RunStatus.RUNNING


# ----- the halt note (W5) -------------------------------------------------------


def test_a_halt_with_an_open_question_says_what_it_waits_on(make_runtime) -> None:
    rt = make_runtime()
    q(rt, stories=["s1"])
    found = halt.Halt(halt.HaltKind.SIGTERM, "stopped")
    rt.halt_run(found)
    note = rt.relay.messages()[-1].text
    assert note == halt_note(found, None) + "; waiting on answers: s1 waits on m1"
    assert "waiting on answers" not in (rt.state.status_reason or "")


def test_a_halt_without_a_question_is_unchanged(make_runtime) -> None:
    rt = make_runtime()
    found = halt.Halt(halt.HaltKind.SIGTERM, "stopped")
    rt.halt_run(found)
    assert rt.relay.messages()[-1].text == halt_note(found, None)


# ----- driver level: no PO session, an answer wakes the run (W1) ----------------


def test_an_answer_wakes_the_run_when_no_po_session_runs(make_runtime, fake: FakeSystem) -> None:
    async def ask(rt) -> None:
        q(rt, "Which DB?", ["s1"])

    script = Script(po=[ask])
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt)
    run = PoRun(rt, Start("go"))
    fake.on_sleep = [lambda: rt.relay.answer("m1", "sqlite")]
    asyncio.run(run.run())
    assert fake.slept == [5.0]
    assert 'The human answered m1 ("Which DB?"): sqlite' in script.po_prompts[1]
    assert ["human_message"] in [e.data["triggers"] for e in handover_events(rt)]
    assert any(s.step != "design" or s.status.value == "done" for s in rt.state.stories.values())


@pytest.mark.parametrize("reason", [None, "other"])
def test_status_is_untouched_by_the_wait_line(make_runtime, reason) -> None:
    rt = make_runtime()
    q(rt, stories=["s1"])
    rt.state.mark(RunStatus.RUNNING, reason)
    Router(rt)._show_wait()
    assert rt.state.status is RunStatus.RUNNING
    assert rt.state.status_reason == "waiting on answers: s1 waits on m1"
