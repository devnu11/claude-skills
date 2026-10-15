"""s64: the PO tool schemas no longer carry an environment rule (open_story left in s135)."""

from agile_team.po_tools import SCHEMAS


def test_no_schema_mentions_the_environment_table() -> None:
    assert "open_story" not in SCHEMAS
    assert [name for name, spec in SCHEMAS.items() if "[[environment]]" in str(spec)] == []
