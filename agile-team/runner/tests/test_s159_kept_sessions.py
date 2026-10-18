"""s159 K1 to K3: kept sessions per role on a story."""

from types import SimpleNamespace

import pytest
from agile_team import kept_sessions as ks
from agile_team.gates import StoryState
from agile_team.story_branches import KeptSession


def story() -> StoryState:
    s = StoryState(id="s1", title="t", step="implement")
    s.sessions["developer"] = KeptSession("sess-d", "opus", "high", "anthropic")
    s.sessions["tester"] = KeptSession("sess-t", "opus", "high", "anthropic")
    return s


def role(model="opus", effort="high", provider="anthropic", name="developer"):
    return SimpleNamespace(name=name, model=model, effort=effort, provider=provider)


def test_the_same_settings_resume() -> None:
    assert ks.resume_of(story(), role()) == "sess-d"


@pytest.mark.parametrize("change", [{"model": "haiku"}, {"effort": "low"}, {"provider": "local"}])
def test_a_changed_setting_starts_fresh(change: dict) -> None:
    assert ks.resume_of(story(), role(**change)) is None


def test_no_kept_session_starts_fresh() -> None:
    assert ks.resume_of(story(), role(name="architect")) is None


def test_drop_all_ends_every_session() -> None:
    s = story()
    ks.drop_all(s)
    assert s.sessions == {}


def test_drop_role_ends_only_that_role() -> None:
    s = story()
    ks.drop_role(s, "developer")
    assert list(s.sessions) == ["tester"]
    ks.drop_role(s, "nobody")
    assert list(s.sessions) == ["tester"]


@pytest.mark.parametrize(
    "text", ["Prompt is too long", "context window exceeded", "maximum context length is 200000"]
)
def test_context_limit_errors_are_recognised(text: str) -> None:
    assert ks.context_exceeded(text)


def test_other_errors_are_not_context_errors() -> None:
    assert not ks.context_exceeded("rate limit reached")
    assert not ks.context_exceeded("")
    assert ks.CONTEXT_PATTERNS
