"""s64: open_story schema still states the environment rule (checks moved to s94)."""

from agile_team.po_tools import SCHEMAS


def test_schema_description_mentions_environment_rule() -> None:
    assert "[[environment]]" in str(SCHEMAS["open_story"])
