"""s94 end to end: the real open story files name a ruled environment per AC (AC4, SF11).

The test builds its own scratch config; it never opens the repo's `.agile-team.toml`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from agile_team import config, story_spec

STORIES = Path(__file__).resolve().parents[4] / ".team" / "stories"
SCRATCH_NAMES = ("cli", "dashboard", "review", "unattended", "house-rules")
SCRATCH_CONFIG = """[[environment]]
name = "cli"
kind = "package"

[[environment]]
name = "dashboard"
kind = "web"
url = "http://127.0.0.1:8765/"

[[environment]]
name = "review"
kind = "document"

[[environment]]
name = "unattended"
kind = "package"

[[environment]]
name = "house-rules"
kind = "package"
"""
# Stories whose status was done in state.json when the migration landed.
DONE_AT_MIGRATION = frozenset(
    {
        "s100",
        "s101",
        "s102",
        "s103",
        "s104",
        "s105",
        "s107",
        "s108",
        "s109",
        "s11",
        "s110",
        "s13",
        "s15",
        "s19",
        "s21",
        "s23",
        "s24",
        "s25",
        "s26",
        "s27",
        "s29",
        "s3",
        "s30",
        "s37",
        "s38",
        "s4",
        "s40",
        "s41",
        "s43",
        "s44",
        "s45",
        "s46",
        "s47",
        "s5",
        "s51",
        "s53",
        "s58",
        "s59",
        "s61",
        "s62",
        "s64",
        "s65",
        "s67",
        "s68",
        "s69",
        "s7",
        "s70",
        "s71",
        "s72",
        "s74",
        "s75",
        "s76",
        "s77",
        "s78",
        "s79",
        "s8",
        "s81",
        "s82",
        "s83",
        "s84",
        "s85",
        "s86",
        "s89",
        "s9",
        "s92",
        "s93",
        "s96",
        "s97",
        "s98",
        "s99",
    }
)


def scratch(tmp_path: Path) -> config.Config:
    """A scratch repo holding SCRATCH_CONFIG, loaded."""
    (tmp_path / ".agile-team.toml").write_text(SCRATCH_CONFIG)
    return config.load(tmp_path)


def test_scratch_config_has_the_three_ruled_environments(tmp_path: Path) -> None:
    cfg = scratch(tmp_path)
    assert [e.name for e in cfg.environments] == list(SCRATCH_NAMES)
    assert [e.kind for e in cfg.environments] == [
        "package",
        "web",
        "document",
        "package",
        "package",
    ]


def test_every_open_story_names_a_ruled_environment_per_ac(tmp_path: Path) -> None:
    cfg = scratch(tmp_path)
    target = tmp_path / ".team" / "stories"
    target.mkdir(parents=True)
    for path in STORIES.glob("s*.md"):
        shutil.copy(path, target / path.name)
    open_ids = sorted(p.stem for p in target.glob("s*.md") if p.stem not in DONE_AT_MIGRATION)
    assert open_ids
    refusals = [r for sid in open_ids if (r := story_spec.read(cfg, sid).refusal())]
    assert not refusals, "\n".join(refusals)
