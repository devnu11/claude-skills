"""s23 Part 1: renewing the PO's session at sprint start and when a story is done."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import po_session, po_tools
from agile_team import state as state_mod
from agile_team.dispatch import StepResult, collect
from agile_team.events import EventKind
from agile_team.po_session import (
    CARRY_HEAD,
    COMPACT_PROMPT,
    HANDOFF_FILE,
    HANDOFF_PROMPT,
    RenewPath,
)
from agile_team.po_tools import PoRun, PoTurn, Start, Tools
from agile_team.relay import Note
from claude_agent_sdk import ResultError, SystemMessage

from .conftest import result_message
from .pipeline_helpers import PO_ROLE, Script, add_story, build, drive
from .test_halt import limit_error

BOUNDARY = SystemMessage(
    "compact_boundary", {"compact_metadata": {"trigger": "manual", "pre_tokens": 180000}}
)


class PoFake:
    """A PO-only fake query: records prompts and resumes, can compact or write a handoff."""

    def __init__(self, boundary: bool = True, handoff: str | None = "Next: s2.", raises=None):
        self.boundary, self.handoff, self.raises = boundary, handoff, raises
        self.rt: Any = None
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        self.calls.append((prompt, options.resume))
        return self._gen(prompt, options.resume)

    async def _gen(self, prompt: str, resume: str | None) -> AsyncIterator[Any]:
        if self.raises and prompt.startswith("/compact"):
            raise self.raises
        if prompt.startswith("/compact") and self.boundary:
            yield BOUNDARY
        if prompt == HANDOFF_PROMPT and self.handoff is not None:
            path = self.rt.config.repo / HANDOFF_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.handoff)
        yield result_message("ok", session=resume or f"fresh-{len(self.calls)}")

    @property
    def prompts(self) -> list[str]:
        return [p for p, _ in self.calls]

    @property
    def resumes(self) -> list[str | None]:
        return [r for _, r in self.calls]


def setup(make_runtime, **kw):
    fake = PoFake(**kw)
    rt = make_runtime(fake)
    fake.rt = rt
    rt.state.po_session = "old"
    rt.state.delivered = []
    return rt, fake, PoRun(rt, Start("t"))


def renew(run: PoRun, prompt: str = "HANDOVER", resume: str | None = "old") -> PoTurn:
    return asyncio.run(run._renewed(PoTurn(prompt, resume)))


def events(rt, kind: EventKind = EventKind.PO_SESSION) -> list[Any]:
    return [e for e in rt.events.events() if e.kind == kind]


# ----- texts and helpers ------------------------------------------------------------


def test_constants_have_the_documented_values() -> None:
    assert HANDOFF_FILE == ".team/po/handoff.md"
    assert COMPACT_PROMPT.startswith("/compact ")
    assert po_session.KEEP in COMPACT_PROMPT and po_session.KEEP in HANDOFF_PROMPT
    assert HANDOFF_FILE in HANDOFF_PROMPT
    assert [p.value for p in RenewPath] == ["compact", "handoff", "kept"]


def test_carry_over_is_empty_without_open_questions(make_runtime) -> None:
    rt = make_runtime()
    assert po_session.carry_over(rt.relay) == ""


def test_carry_over_lists_each_open_question(make_runtime) -> None:
    rt = make_runtime()
    rt.relay.post(Note("question", "Which DB?", ["s2", "s3"]))
    rt.relay.post(Note("question", "Colour?", []))
    answered = rt.relay.post(Note("question", "Done already?", ["s1"]))
    rt.relay.answer(answered.id, "yes")
    text = po_session.carry_over(rt.relay)
    assert text == "\n".join(
        [CARRY_HEAD, "- m1 (blocks s2, s3): Which DB?", "- m2 (blocks nothing): Colour?"]
    )


def test_with_carry_over_joins_non_empty_parts(make_runtime) -> None:
    rt = make_runtime()
    assert po_session.with_carry_over(rt.relay, "PROMPT") == "PROMPT"
    rt.relay.post(Note("question", "Q?", ["s1"]))
    out = po_session.with_carry_over(rt.relay, "PROMPT")
    assert out == po_session.carry_over(rt.relay) + "\n\nPROMPT"


def test_read_and_clear_handoff(tmp_path) -> None:
    assert po_session.read_handoff(tmp_path) == ""
    po_session.clear_handoff(tmp_path)  # missing file is fine
    path = tmp_path / HANDOFF_FILE
    path.parent.mkdir(parents=True)
    path.write_text("  keep s2\n\n")
    assert po_session.read_handoff(tmp_path) == "keep s2"
    po_session.clear_handoff(tmp_path)
    assert not path.exists()


def test_fresh_lead_formats_file_handoff_and_status() -> None:
    lead = po_session.fresh_lead("H", "S")
    assert lead == po_session.FRESH_LEAD.format(file=HANDOFF_FILE, handoff="H", status="S")
    assert lead.startswith("You are continuing this run in a fresh session.")


# ----- P1 boundaries ----------------------------------------------------------------


def test_start_sprint_queues_a_boundary(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1")
    rt.state.sprint = 0
    asyncio.run(Tools(rt).start_sprint({"goal": "g", "stories": ["s1"]}))
    assert rt.state.po_renew_due == ["sprint 1 start"]
    assert state_mod.load(rt.config.run_dir).po_renew_due == ["sprint 1 start"]


def test_refused_start_sprint_queues_nothing(make_runtime) -> None:
    rt = make_runtime()
    asyncio.run(Tools(rt).start_sprint({"goal": "g", "stories": []}))
    assert rt.state.po_renew_due == []


def test_done_story_queues_one_boundary_even_if_logged_twice(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    story = add_story(rt)
    drive(rt)
    assert story.id not in rt.state.scribe_due
    reasons = [r for e in events(rt) for r in e.data["reasons"]] + rt.state.po_renew_due
    assert reasons.count("s1 done") == 1


# ----- P3 no renewal ----------------------------------------------------------------


def test_nothing_due_runs_no_extra_query(make_runtime) -> None:
    rt, fake, run = setup(make_runtime)
    turn = PoTurn("HANDOVER", "old")
    assert asyncio.run(run._renewed(turn)) is turn
    assert fake.calls == [] and events(rt) == []


def test_due_but_already_fresh_clears_and_skips_the_query(make_runtime) -> None:
    rt, fake, run = setup(make_runtime)
    rt.state.po_renew_due = ["sprint 1 start"]
    turn = PoTurn("KICKOFF", None)
    assert asyncio.run(run._renewed(turn)) is turn
    assert fake.calls == [] and rt.state.po_renew_due == []
    assert state_mod.load(rt.config.run_dir).po_renew_due == []


# ----- P4 compact path --------------------------------------------------------------


def test_compact_path_sends_compact_then_the_turn_on_the_same_session(make_runtime) -> None:
    rt, fake, run = setup(make_runtime)
    rt.state.po_renew_due = ["sprint 1 start", "s1 done"]
    rt.relay.post(Note("question", "Which DB?", ["s2"]))
    turn = renew(run)
    assert fake.calls == [(COMPACT_PROMPT, "old")]
    assert turn.resume == rt.state.po_session == "old"
    assert turn.prompt == po_session.carry_over(rt.relay) + "\n\nHANDOVER"
    assert "- m1 (blocks s2): Which DB?" in turn.prompt
    (event,) = events(rt)
    assert (event.role, event.story) == (PO_ROLE, None)
    assert event.data == {
        "path": "compact",
        "reasons": ["sprint 1 start", "s1 done"],
        "pre_tokens": 180000,
    }
    assert rt.state.po_renew_due == [] and rt.state.po_renew_path == "compact"


def test_compact_query_is_a_ledgered_po_entry(make_runtime) -> None:
    rt, _, run = setup(make_runtime)
    rt.state.po_renew_due = ["s1 done"]
    renew(run)
    (entry,) = rt.ledger.entries()
    assert (entry.role, entry.turns) == (PO_ROLE, 1) and entry.tokens.total() > 0


def test_no_carry_over_heading_without_questions(make_runtime) -> None:
    rt, _, run = setup(make_runtime)
    rt.state.po_renew_due = ["s1 done"]
    assert renew(run).prompt == "HANDOVER"


# ----- P5-P7 fallback ---------------------------------------------------------------


def test_missing_boundary_falls_back_to_the_handoff_file(make_runtime) -> None:
    rt, fake, run = setup(make_runtime, boundary=False)
    rt.state.po_renew_due = ["s1 done"]
    rt.relay.post(Note("question", "Which DB?", ["s2"]))
    turn = renew(run, "HANDOVER TEXT")
    assert fake.prompts == [COMPACT_PROMPT, HANDOFF_PROMPT]
    assert fake.resumes == ["old", "old"]
    assert rt.state.po_renew_path == "handoff" and rt.state.po_renew_due == []
    assert turn.resume is None
    assert turn.prompt.startswith(po_tools.first_prompt(rt, Start(rt.state.task)))
    order = [
        turn.prompt.index(part)
        for part in ("Mode:", "Next: s2.", "story_status:", CARRY_HEAD, "HANDOVER TEXT")
    ]
    assert order == sorted(order)
    (event,) = events(rt)
    assert event.data == {"path": "handoff", "reasons": ["s1 done"], "pre_tokens": None}


def test_fresh_prompt_holds_the_story_status_json(make_runtime) -> None:
    rt, _, run = setup(make_runtime, boundary=False)
    add_story(rt, "s1")
    rt.state.po_renew_due = ["s1 done"]
    prompt = renew(run).prompt
    status = json.dumps(po_tools.story_status_data(rt), indent=1)
    assert status in prompt and '"s1"' in status


def test_the_next_turn_saves_the_fresh_session_id(make_runtime) -> None:
    rt, fake, run = setup(make_runtime, boundary=False)
    rt.state.po_renew_due = ["s1 done"]
    turn = renew(run)
    asyncio.run(run._turn(turn))
    assert rt.state.po_session == f"fresh-{len(fake.calls)}"
    assert state_mod.load(rt.config.run_dir).po_session == rt.state.po_session


def test_later_boundaries_skip_the_compact_attempt(make_runtime) -> None:
    rt, fake, run = setup(make_runtime, boundary=False)
    rt.state.po_renew_due = ["s1 done"]
    renew(run)
    fake.calls.clear()
    rt.state.po_renew_due = ["s2 done"]
    renew(run, resume="fresh-2")
    assert fake.prompts == [HANDOFF_PROMPT]


def test_saved_handoff_path_is_used_from_the_start(make_runtime) -> None:
    rt, fake, run = setup(make_runtime)
    rt.state.po_renew_path = "handoff"
    rt.state.po_renew_due = ["s1 done"]
    renew(run)
    assert fake.prompts == [HANDOFF_PROMPT]


# ----- P6 kept ----------------------------------------------------------------------


def test_stale_handoff_is_deleted_and_a_silent_po_keeps_its_session(make_runtime) -> None:
    rt, _, run = setup(make_runtime, boundary=False, handoff=None)
    stale = rt.config.repo / HANDOFF_FILE
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("STALE")
    rt.state.po_renew_due = ["s1 done"]
    rt.relay.post(Note("question", "Which DB?", ["s2"]))
    turn = renew(run)
    assert not stale.exists()
    assert turn.resume == "old"
    assert turn.prompt == po_session.carry_over(rt.relay) + "\n\nHANDOVER"
    (event,) = events(rt)
    assert event.data["path"] == "kept"
    assert rt.state.po_renew_due == []


def test_blank_handoff_counts_as_kept(make_runtime) -> None:
    rt, _, run = setup(make_runtime, boundary=False, handoff="  \n")
    rt.state.po_renew_due = ["s1 done"]
    assert renew(run).resume == "old"
    assert events(rt)[0].data["path"] == "kept"


# ----- P9 never drop ----------------------------------------------------------------


@pytest.mark.parametrize("boundary,handoff", [(True, "x"), (False, "x"), (False, None)])
def test_open_questions_survive_every_path(make_runtime, boundary, handoff) -> None:
    rt, _, run = setup(make_runtime, boundary=boundary, handoff=handoff)
    rt.state.po_renew_due = ["s1 done"]
    rt.relay.post(Note("question", "Which DB?", ["s2"]))
    assert "- m1 (blocks s2): Which DB?" in renew(run, "HUMAN SAID: hi").prompt
    assert "HUMAN SAID: hi" in renew(run, "HUMAN SAID: hi").prompt


def test_renewal_does_not_touch_delivered(make_runtime) -> None:
    rt, _, run = setup(make_runtime)
    rt.state.delivered = []
    answered = rt.relay.post(Note("question", "Q?", ["s1"]))
    rt.relay.answer(answered.id, "yes")
    rt.state.po_renew_due = ["s1 done"]
    renew(run)
    assert rt.state.delivered == []


# ----- P10 errors -------------------------------------------------------------------


def test_a_limit_in_the_renewal_query_keeps_the_reasons(make_runtime) -> None:
    rt, _, run = setup(make_runtime, raises=limit_error())
    rt.state.po_renew_due = ["s1 done"]
    with pytest.raises(ResultError):
        renew(run)
    assert rt.state.po_renew_due == ["s1 done"]
    assert state_mod.load(rt.config.run_dir).po_renew_due == ["s1 done"]


# ----- end to end -------------------------------------------------------------------


def test_one_run_renews_before_the_hand_over(make_runtime) -> None:
    fake = PoFake()
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    fake.rt = script.rt = rt
    script.answers_compact = False
    original = script._gen

    async def routed(role: str):
        gen = fake._gen(script.calls[-1][1], None) if role == PO_ROLE else original(role)
        async for message in gen:
            yield message

    script._gen = routed
    add_story(rt)
    rt.state.po_session = None
    drive(rt)
    prompts = script.po_prompts
    assert prompts[1] == COMPACT_PROMPT
    assert "Sprint 1 is complete" in prompts[2]
    (event,) = events(rt)
    assert event.data["path"] == "compact" and event.data["reasons"] == ["s1 done"]
    assert rt.state.po_renew_due == []


# ----- C1 collect -------------------------------------------------------------------


def run_collect(*messages: Any) -> StepResult:
    async def query(*, prompt: str, options: Any) -> AsyncIterator[Any]:
        for message in messages:
            yield message

    plan = SimpleNamespace(prompt="p", options=None)
    return asyncio.run(collect(query, plan))


def test_collect_reads_pre_tokens_from_the_boundary() -> None:
    result = run_collect(BOUNDARY, result_message("ok"))
    assert result.compacted_from == 180000 and result.text == "ok"


def test_collect_without_a_boundary_is_none() -> None:
    assert run_collect(result_message("ok")).compacted_from is None
    other = SystemMessage("init", {"compact_metadata": {"pre_tokens": 5}})
    assert run_collect(other, result_message("ok")).compacted_from is None


def test_collect_boundary_without_metadata_is_zero() -> None:
    assert (
        run_collect(SystemMessage("compact_boundary", {}), result_message("x")).compacted_from == 0
    )


def test_collect_uses_the_first_boundary() -> None:
    second = SystemMessage("compact_boundary", {"compact_metadata": {"pre_tokens": 7}})
    assert run_collect(BOUNDARY, second, result_message("x")).compacted_from == 180000


def test_collect_without_a_result_keeps_the_boundary_none_safe() -> None:
    result = run_collect(BOUNDARY)
    assert result.cost == 0.0
