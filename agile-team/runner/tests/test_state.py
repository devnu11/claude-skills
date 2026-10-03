"""Run state round trip."""

from pathlib import Path

from agile_team import state
from agile_team.gates import StoryState


def test_round_trip(tmp_path: Path) -> None:
    assert state.load(tmp_path).status == "idle"
    st = state.RunState(cadence="until-blocker", sprint=2)
    st.stories["s1"] = StoryState("s1", "Add", "tests", rounds=1)
    st.overrides["developer"] = state.ModelOverride("opus", "high", "hard")
    state.save(tmp_path / "run", st)
    back = state.load(tmp_path / "run")
    assert back.stories["s1"].rounds == 1
    assert back.runtime_overrides("developer") == {"model": "opus", "effort": "high"}
    assert back.runtime_overrides("architect") == {}
