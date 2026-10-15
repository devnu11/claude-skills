"""Unit tests for ``chat``: the orchestrator with a scripted backend."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ProcessError
from group_chat.addressing import AddressError
from group_chat.backend import BackendError, ClaudeBackend
from group_chat.chat import GroupChat, Limits, PartialReplyError, find_handoff
from group_chat.roster import Roster
from group_chat.state import StateError, Store, Turn

from .conftest import FailingBackend, FakeBackend

pytestmark = pytest.mark.unit

NAMES = ("manager", "po", "liaison")


def make(roster: Roster, backend: FakeBackend, tmp_path: Path, **limits: Any) -> GroupChat:
    return GroupChat(roster, backend, Store(tmp_path / "chat"), Limits(**limits))


def test_only_the_addressed_role_answers(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"manager": ["Friday."]}
    chat = make(roster, backend, tmp_path)
    assert chat.send("@manager when?") == [Turn("manager", "Friday.")]
    assert len(backend.calls) == 1
    assert backend.calls[0].model is None


def test_each_role_sees_the_whole_thread(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"po": ["scope is fixed"]}
    chat = make(roster, backend, tmp_path)
    chat.send("@po scope?")
    chat.send("@manager does that work?")
    last = backend.calls[-1].prompt
    assert '<turn speaker="human">\n@po scope?\n</turn>' in last
    assert '<turn speaker="po">\nscope is fixed\n</turn>' in last
    assert last.endswith("Reply as @manager.")


def test_broadcast_answers_in_roster_order(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    replies = make(roster, backend, tmp_path).send("@all status?")
    assert [turn.speaker for turn in replies] == list(NAMES)


def test_sticky_addressee_persists_across_runs(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    make(roster, backend, tmp_path).send("@po first")
    replies = make(roster, backend, tmp_path).send("and then?")
    assert [turn.speaker for turn in replies] == ["po"]


def test_refused_message_is_not_recorded(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    chat = make(roster, backend, tmp_path)
    with pytest.raises(AddressError):
        chat.send("hello?")
    assert chat.store.load().turns == []


def test_handoff_passes_the_floor(roster: Roster, backend: FakeBackend, tmp_path: Path) -> None:
    backend.replies = {"manager": ["Not mine.\nHANDOFF: @po"]}
    replies = make(roster, backend, tmp_path).send("@manager scope?")
    assert [turn.speaker for turn in replies] == ["manager", "po"]


def test_handoff_limit_drops_extra_hops(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"], "po": ["HANDOFF: @manager"]}
    replies = make(roster, backend, tmp_path, max_handoffs=1).send("@manager ?")
    assert [turn.speaker for turn in replies] == ["manager", "po", "orchestrator"]
    assert "handoff to @manager dropped" in replies[-1].text


def test_decisions_from_replies_are_pinned(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"po": ["DECISION: ship Friday"]}
    chat = make(roster, backend, tmp_path)
    chat.send("@po QUESTION: ship date?")
    log = chat.store.load().log
    assert [e.text for e in log.decisions] == ["ship Friday"]
    assert [e.by for e in log.questions] == ["human"]


def test_compaction_folds_old_turns_into_summary(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.summary = "folded"
    chat = make(roster, backend, tmp_path, recent_tokens=1, keep_turns=2)
    chat.send("@po one")
    chat.send("@po two")
    state = chat.store.load()
    assert state.summary == "folded"
    assert [turn.text for turn in state.turns] == ["@po two", "po reply"]
    assert '<turn speaker="human">\n@po one\n</turn>' in backend.calls[-1].prompt


def test_no_compaction_under_budget(roster: Roster, backend: FakeBackend, tmp_path: Path) -> None:
    chat = make(roster, backend, tmp_path)
    chat.send("@po hi")
    assert chat.store.load().summary == ""
    assert len(backend.calls) == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HANDOFF: @po", "po"),
        ("x\nHANDOFF: @po\nHANDOFF: @liaison", "liaison"),
        ("HANDOFF: @manager", None),
        ("HANDOFF: @cto", None),
        ("please handoff: @po", None),
    ],
)
def test_handoff_of(text: str, expected: str | None) -> None:
    assert find_handoff(text, NAMES, "manager") == expected


def test_role_model_is_passed_to_backend(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    make(roster, backend, tmp_path).send("@po hi")
    assert backend.calls[0].model == "haiku"


def test_summary_model_is_used_for_compaction(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    make(roster, backend, tmp_path, recent_tokens=1, keep_turns=0, summary_model="opus").send(
        "@manager hi"
    )
    assert backend.calls[-1].model == "opus"


def test_human_handoff_line_does_not_route(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    replies = make(roster, backend, tmp_path).send("@manager hi\nHANDOFF: @po")
    assert [turn.speaker for turn in replies] == ["manager"]


def test_handoff_does_not_change_sticky_addressee(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"]}
    chat = make(roster, backend, tmp_path)
    chat.send("@manager x")
    assert chat.store.load().last_addressed == ("manager",)


def test_zero_handoffs_records_note(roster: Roster, backend: FakeBackend, tmp_path: Path) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"]}
    chat = make(roster, backend, tmp_path, max_handoffs=0)
    replies = chat.send("@manager x")
    assert [turn.speaker for turn in replies] == ["manager", "orchestrator"]
    assert chat.store.load().turns[-1].speaker == "orchestrator"


def test_unexpected_error_keeps_human_turn_and_releases_lock(
    roster: Roster, tmp_path: Path
) -> None:
    class Boom:
        def complete(self, system: str, prompt: str, model: str | None) -> str:
            raise RuntimeError("down")

    chat = GroupChat(roster, Boom(), Store(tmp_path / "chat"))
    with pytest.raises(RuntimeError):
        chat.send("@po hi")
    assert chat.store.load().turns == [Turn("human", "@po hi")]
    assert not chat.store.lockfile.exists()


def test_message_is_stripped(roster: Roster, backend: FakeBackend, tmp_path: Path) -> None:
    chat = make(roster, backend, tmp_path)
    chat.send("  @po hi  \n")
    assert chat.store.load().turns[0] == Turn("human", "@po hi")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  HANDOFF: @po  ", "po"),
        ("HANDOFF:@po", "po"),
        ("HANDOFF: @po\nmore text", "po"),
        ("HANDOFF: @po @liaison", "po"),
    ],
)
def test_handoff_of_spacing(text: str, expected: str | None) -> None:
    assert find_handoff(text, NAMES, "manager") == expected


def test_handoff_after_leading_mentions() -> None:
    assert find_handoff("@po HANDOFF: @liaison", NAMES, "manager") == "liaison"


def test_say_holds_the_lock_during_model_calls(roster: Roster, tmp_path: Path) -> None:
    store = Store(tmp_path / "chat")

    class Spy(FakeBackend):
        def complete(self, system: str, prompt: str, model: str | None) -> str:
            assert store.lockfile.exists()
            return super().complete(system, prompt, model)

    GroupChat(roster, Spy(), store).send("@po hi")
    assert not store.lockfile.exists()


def test_held_lock_refuses_and_records_nothing(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    chat = make(roster, backend, tmp_path)
    chat.store.directory.mkdir()
    chat.store.lockfile.write_text("")
    with pytest.raises(StateError, match="held by another process"):
        chat.send("@po hi")
    assert backend.calls == []
    assert not chat.store.path.exists()


def test_lock_released_after_address_error(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    chat = make(roster, backend, tmp_path)
    with pytest.raises(AddressError):
        chat.send("nobody")
    assert not chat.store.lockfile.exists()


def test_human_turn_saved_before_first_model_call(roster: Roster, tmp_path: Path) -> None:
    store = Store(tmp_path / "chat")

    class Spy(FakeBackend):
        def complete(self, system: str, prompt: str, model: str | None) -> str:
            assert store.load().turns[-1] == Turn("human", "@po hi")
            assert store.load().last_addressed == ("po",)
            return super().complete(system, prompt, model)

    GroupChat(roster, Spy(), store).send("@po hi")


def test_each_reply_is_saved_before_the_next_call(roster: Roster, tmp_path: Path) -> None:
    store = Store(tmp_path / "chat")
    seen: list[int] = []

    class Spy(FakeBackend):
        def complete(self, system: str, prompt: str, model: str | None) -> str:
            seen.append(len(store.load().turns))
            return super().complete(system, prompt, model)

    GroupChat(roster, Spy(), store).send("@all hi")
    assert seen == [1, 2, 3]


def test_partial_reply_keeps_earlier_replies(roster: Roster, tmp_path: Path) -> None:
    backend = FailingBackend(fail_roles={"po"})
    chat = GroupChat(roster, backend, Store(tmp_path / "chat"))
    with pytest.raises(PartialReplyError, match="overloaded") as exc:
        chat.send("@all status?")
    note = Turn("orchestrator", "@po could not answer: overloaded")
    assert exc.value.replies == [Turn("manager", "manager reply"), note]
    assert chat.store.load().turns == [Turn("human", "@all status?"), *exc.value.replies]
    assert chat.store.load().last_addressed == NAMES
    assert not chat.store.lockfile.exists()


def test_partial_reply_skips_later_roles(roster: Roster, tmp_path: Path) -> None:
    backend = FailingBackend(fail_roles={"manager"})
    chat = GroupChat(roster, backend, Store(tmp_path / "chat"))
    with pytest.raises(PartialReplyError):
        chat.send("@all status?")
    assert len(backend.calls) == 1


def test_failure_note_does_not_touch_the_log(roster: Roster, tmp_path: Path) -> None:
    chat = GroupChat(roster, FailingBackend(fail_roles={"po"}), Store(tmp_path / "chat"))
    with pytest.raises(PartialReplyError):
        chat.send("@po hi")
    assert chat.store.load().log.decisions == []


def test_summary_failure_keeps_turns_and_notes_it(roster: Roster, tmp_path: Path) -> None:
    backend = FailingBackend(fail_summary=True)
    chat = GroupChat(
        roster, backend, Store(tmp_path / "chat"), Limits(recent_tokens=1, keep_turns=2)
    )
    chat.send("@po one")
    replies = chat.send("@po two")
    note = Turn("orchestrator", "summary skipped, turns kept verbatim: overloaded")
    assert replies == [Turn("po", "po reply"), note]
    state = chat.store.load()
    assert state.summary == ""
    assert [t.text for t in state.turns[:2]] == ["@po one", "po reply"]


def test_compaction_retries_after_summary_failure(roster: Roster, tmp_path: Path) -> None:
    backend = FailingBackend(fail_summary=True)
    chat = GroupChat(
        roster, backend, Store(tmp_path / "chat"), Limits(recent_tokens=1, keep_turns=2)
    )
    chat.send("@po one")
    chat.send("@po two")
    backend.fail_summary = False
    chat.send("@po three")
    state = chat.store.load()
    assert state.summary == "SUMMARY"
    assert len(state.turns) == 2


def test_handoff_to_queued_role_is_skipped(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"]}
    replies = make(roster, backend, tmp_path).send("@all status?")
    assert [turn.speaker for turn in replies] == list(NAMES)


def test_handoff_to_queued_role_does_not_use_a_hop(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"], "liaison": ["HANDOFF: @manager"]}
    replies = make(roster, backend, tmp_path, max_handoffs=1).send("@all status?")
    assert [turn.speaker for turn in replies] == [*NAMES, "manager"]


def test_handoff_to_role_that_already_spoke_is_allowed(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"po": ["HANDOFF: @manager"]}
    replies = make(roster, backend, tmp_path).send("@manager @po hi")
    assert [turn.speaker for turn in replies] == ["manager", "po", "manager"]


def test_last_addressed_is_human_targets_not_handoff(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"po": ["HANDOFF: @liaison"]}
    chat = make(roster, backend, tmp_path)
    chat.send("@po @manager hi")
    assert chat.store.load().last_addressed == ("po", "manager")


@pytest.mark.parametrize(
    "text",
    [
        "HANDOFF: @PO",
        "HANDOFF: @Po",
        "- HANDOFF: @po",
        "* HANDOFF: @po",
        "**HANDOFF:** @po",
        "- **HANDOFF:** @po",
        "@human HANDOFF: @po",
        "  @Human, **HANDOFF:** @po",
    ],
)
def test_handoff_prefixes_and_case(text: str) -> None:
    assert find_handoff(text, NAMES, "manager") == "po"


@pytest.mark.parametrize("text", ["handoff: @po", "> HANDOFF: @po", "x HANDOFF: @po"])
def test_handoff_not_at_line_start(text: str) -> None:
    assert find_handoff(text, NAMES, "manager") is None


def test_handoff_to_self_in_other_case_is_ignored() -> None:
    assert find_handoff("HANDOFF: @MANAGER", NAMES, "manager") is None


@pytest.mark.parametrize(
    "text",
    [
        "```\nHANDOFF: @po\n```",
        "~~~\nHANDOFF: @po\n~~~",
        "Example:\n```text\nHANDOFF: @po",
    ],
)
def test_fenced_handoff_is_ignored(text: str) -> None:
    assert find_handoff(text, NAMES, "manager") is None


def test_handoff_after_fence_counts() -> None:
    assert find_handoff("```\nHANDOFF: @liaison\n```\nHANDOFF: @po", NAMES, "manager") == "po"


def test_partial_reply_error_is_a_backend_error() -> None:
    assert issubclass(PartialReplyError, BackendError)
    error = PartialReplyError([Turn("po", "x")], BackendError("down"))
    assert str(error) == "down"
    assert error.replies == [Turn("po", "x")]


def test_sdk_error_gives_partial_reply_with_note(roster: Roster, tmp_path: Path) -> None:
    async def query_fn(**_kwargs: object) -> AsyncIterator[object]:
        raise ProcessError("crashed", exit_code=1)
        yield  # pragma: no cover

    chat = GroupChat(roster, ClaudeBackend(query_fn), Store(tmp_path / "chat"))
    with pytest.raises(PartialReplyError) as exc:
        chat.send("@po hi")
    assert exc.value.replies[-1].speaker == "orchestrator"
    assert exc.value.replies[-1].text.startswith("@po could not answer: ProcessError: crashed")
    assert not chat.store.lockfile.exists()
