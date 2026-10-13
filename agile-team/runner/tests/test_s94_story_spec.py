"""s94: story_spec parses a story file's frontmatter (SF1-SF3, SF6, SF9)."""

from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import story_spec, system
from agile_team.config import Environment
from agile_team.story_spec import PROBLEMS, Problem, Source

FILE = ".team/stories/s120.md"
NAMES = ["cli", "unattended", "dashboard"]
LISTED = "cli, unattended, dashboard"

GOOD = """---
id: s120
title: "Export the board as CSV"
depends_on: [s83]
suite_runs: 3
acceptance:
  - id: AC1
    text: "agile-team export --csv prints one row per story."
    environment: cli
  - id: AC2
    text: "The Backlog tab has an Export button."
    environment: dashboard
---

Body text.
"""


def src(text: str | None, story: str = "s120") -> Source:
    return Source(story, f".team/stories/{story}.md", text)


def doc(head: str = "", acceptance: str | None = None, story: str = "s120") -> str:
    """A frontmatter file with a valid id/title unless ``head`` overrides them."""
    base = head or f'id: {story}\ntitle: "T"\n'
    return f"---\n{base}{acceptance or ''}---\nbody\n"


def item(id_: str = "AC1", text: str = "does it", env: str = "cli") -> str:
    return f'  - id: {id_}\n    text: "{text}"\n    environment: {env}\n'


def lines(text: str | None, names=NAMES) -> list[str]:
    return list(story_spec.parse(src(text), names).problems)


def acc(*items: str) -> str:
    return "acceptance:\n" + "".join(items)


# ----- the good file ----------------------------------------------------------


def test_the_example_parses() -> None:
    read = story_spec.parse(src(GOOD), NAMES)
    assert read.problems == () and read.refusal() is None
    spec = read.spec
    assert spec is not None
    assert (spec.story, spec.title) == ("s120", "Export the board as CSV")
    assert [(c.id, c.environment) for c in spec.criteria] == [("AC1", "cli"), ("AC2", "dashboard")]
    assert spec.criteria[0].text == "agile-team export --csv prints one row per story."
    assert spec.environments(NAMES) == ["cli", "dashboard"]


def test_environments_follow_config_order_not_file_order() -> None:
    text = doc(acceptance=acc(item("AC1", env="dashboard"), item("AC2", env="cli")))
    spec = story_spec.parse(src(text), NAMES).spec
    assert spec is not None
    assert spec.environments(NAMES) == ["cli", "dashboard"]


def test_environments_are_distinct() -> None:
    text = doc(acceptance=acc(item("AC1"), item("AC2"), item("AC3", env="dashboard")))
    spec = story_spec.parse(src(text), NAMES).spec
    assert spec is not None and spec.environments(NAMES) == ["cli", "dashboard"]


def test_extra_keys_are_ignored() -> None:
    text = (
        "---\nid: s120\ntitle: T\nowner: me\nacceptance:\n"
        "  - id: AC1\n    text: x\n    environment: cli\n    note: y\n---\n"
    )
    assert lines(text) == []


# ----- one test per problem ---------------------------------------------------


def test_no_file() -> None:
    assert lines(None) == [f"{FILE}: " + PROBLEMS[Problem.NO_FILE]]


def test_no_frontmatter() -> None:
    assert lines("# just prose\n") == [f"{FILE}: " + PROBLEMS[Problem.NO_FRONTMATTER]]


def test_bad_yaml_carries_the_parser_error() -> None:
    [line] = lines("---\nid: [unclosed\n---\n")
    assert line.startswith(f"{FILE}: frontmatter does not parse: ")
    assert len(line) > len(f"{FILE}: frontmatter does not parse: ")


def test_frontmatter_that_is_not_a_mapping_is_bad_yaml() -> None:
    [line] = lines("---\n- a\n- b\n---\n")
    assert line.startswith(f"{FILE}: frontmatter does not parse: ")


@pytest.mark.parametrize("text", [None, "prose", "---\nid: [x\n---\n"])
def test_the_first_three_checks_stop_the_read(text) -> None:
    assert len(lines(text)) == 1


def test_wrong_id() -> None:
    text = doc("id: s999\ntitle: T\n", acc(item()))
    assert lines(text) == [
        f"{FILE}: " + PROBLEMS[Problem.WRONG_ID].format(found="s999", story="s120")
    ]


@pytest.mark.parametrize("title", ["title: ''\n", "title: 5\n", ""])
def test_no_title(title) -> None:
    text = doc(f"id: s120\n{title}", acc(item()))
    assert lines(text) == [f"{FILE}: " + PROBLEMS[Problem.NO_TITLE]]


def test_wrong_id_and_no_title_give_two_lines() -> None:
    text = doc("id: s9\n", acc(item()))
    assert lines(text) == [
        f"{FILE}: " + PROBLEMS[Problem.WRONG_ID].format(found="s9", story="s120"),
        f"{FILE}: " + PROBLEMS[Problem.NO_TITLE],
    ]


@pytest.mark.parametrize("acceptance", [None, "acceptance: []\n", "acceptance: x\n"])
def test_no_criteria(acceptance) -> None:
    assert lines(doc(acceptance=acceptance)) == [f"{FILE}: " + PROBLEMS[Problem.NO_CRITERIA]]


def test_no_criteria_stops_before_the_items_but_after_story_checks() -> None:
    text = doc("id: s120\n")
    assert lines(text) == [
        f"{FILE}: " + PROBLEMS[Problem.NO_TITLE],
        f"{FILE}: " + PROBLEMS[Problem.NO_CRITERIA],
    ]


def test_not_a_mapping_names_the_item_number() -> None:
    text = doc(acceptance="acceptance:\n  - just text\n")
    assert lines(text) == [f"{FILE}: item 1: " + PROBLEMS[Problem.NOT_A_MAPPING]]


@pytest.mark.parametrize("id_line", ["", "    id: ''\n", "    id: 3\n"])
def test_no_id_names_the_item_number_and_nothing_else(id_line) -> None:
    text = doc(acceptance=f"acceptance:\n  - text: x\n    environment: nope\n{id_line}")
    assert lines(text) == [f"{FILE}: item 1: " + PROBLEMS[Problem.NO_ID]]


def test_duplicate_id() -> None:
    text = doc(acceptance=acc(item("AC1"), item("AC1")))
    assert lines(text) == [f"{FILE}: AC AC1: " + PROBLEMS[Problem.DUPLICATE_ID]]


@pytest.mark.parametrize("text", ["''", "'  '"])
def test_no_text(text) -> None:
    body = f"acceptance:\n  - id: AC1\n    text: {text}\n    environment: cli\n"
    assert lines(doc(acceptance=body)) == [f"{FILE}: AC AC1: " + PROBLEMS[Problem.NO_TEXT]]


def test_text_missing_entirely() -> None:
    body = "acceptance:\n  - id: AC1\n    environment: cli\n"
    assert lines(doc(acceptance=body)) == [f"{FILE}: AC AC1: " + PROBLEMS[Problem.NO_TEXT]]


@pytest.mark.parametrize("env_line", ["", "    environment: ''\n", "    environment: 4\n"])
def test_no_environment_lists_the_names(env_line) -> None:
    body = f"acceptance:\n  - id: AC1\n    text: x\n{env_line}"
    assert lines(doc(acceptance=body)) == [
        f"{FILE}: AC AC1: " + PROBLEMS[Problem.NO_ENVIRONMENT].format(names=LISTED)
    ]


def test_unknown_environment_lists_the_names() -> None:
    text = doc(acceptance=acc(item(env="mars")))
    assert lines(text) == [
        f"{FILE}: AC AC1: "
        + PROBLEMS[Problem.UNKNOWN_ENVIRONMENT].format(name="mars", names=LISTED)
    ]


def test_none_configured_when_there_are_no_names() -> None:
    text = doc(acceptance=acc(item(env="cli")))
    assert lines(text, names=[]) == [
        f"{FILE}: AC AC1: " + PROBLEMS[Problem.NONE_CONFIGURED].format(name="cli")
    ]


def test_problems_text_table_is_exact() -> None:
    assert PROBLEMS[Problem.NO_FILE] == "no story file; write it before open_story"
    assert PROBLEMS[Problem.NO_ID] == "id is missing or empty"
    assert PROBLEMS[Problem.DUPLICATE_ID] == "id is used by an earlier AC"
    assert PROBLEMS[Problem.NO_TEXT] == "text is missing or empty"
    assert story_spec.LINE == "{file}: {where}{problem}"
    assert set(PROBLEMS) == set(Problem)


# ----- several items ----------------------------------------------------------


def test_two_bad_items_report_all_lines_in_file_order() -> None:
    body = (
        "acceptance:\n  - id: AC1\n    text: ''\n    environment: mars\n  - id: AC2\n    text: ok\n"
    )
    assert lines(doc(acceptance=body)) == [
        f"{FILE}: AC AC1: " + PROBLEMS[Problem.NO_TEXT],
        f"{FILE}: AC AC1: "
        + PROBLEMS[Problem.UNKNOWN_ENVIRONMENT].format(name="mars", names=LISTED),
        f"{FILE}: AC AC2: " + PROBLEMS[Problem.NO_ENVIRONMENT].format(names=LISTED),
    ]


def test_refusal_joins_lines_with_newlines() -> None:
    read = story_spec.parse(src(doc("id: s9\n", acc(item()))), NAMES)
    assert read.refusal() == "\n".join(read.problems) and len(read.problems) == 2
    assert read.spec is None


def test_the_hold_text() -> None:
    assert story_spec.STORY_FILE_HOLD == (
        "the story file must be fixed before acceptance:\n{refusal}\n"
        "Edit the file; no state change is needed"
    )


# ----- read, file_of, first_environment ---------------------------------------


def configured_with(repo: Path, *envs: Environment) -> cfg.Config:
    config = cfg.load(repo)
    config.environments = list(envs)
    return config


def put(config: cfg.Config, story: str, text: str) -> None:
    folder = config.repo / ".team" / "stories"
    system.make_dirs(folder)
    system.write_text(folder / f"{story}.md", text)


def test_file_of_is_repo_relative_posix(configured: Path) -> None:
    config = cfg.load(configured)
    assert story_spec.file_of(config, "s120") == ".team/stories/s120.md"


def test_read_of_a_missing_file_is_no_file(configured: Path) -> None:
    config = cfg.load(configured)
    read = story_spec.read(config, "s120")
    assert read.refusal() == f"{FILE}: " + PROBLEMS[Problem.NO_FILE]


def test_read_parses_the_file_against_the_configured_names(configured: Path) -> None:
    config = configured_with(
        configured, Environment("cli", "package"), Environment("dashboard", "web", url="http://x")
    )
    put(config, "s120", GOOD)
    read = story_spec.read(config, "s120")
    assert read.refusal() is None
    assert story_spec.environment_names(config, "s120") == ["cli", "dashboard"]


def test_read_with_no_environments_configured(configured: Path) -> None:
    config = configured_with(configured)
    put(config, "s120", GOOD)
    lines_ = (story_spec.read(config, "s120").refusal() or "").split("\n")
    assert len(lines_) == 2 and "configures no [[environment]]" in lines_[0]


def test_first_environment_is_the_config_order_first(configured: Path) -> None:
    cli, dash = Environment("cli", "package"), Environment("dashboard", "web", url="http://x")
    config = configured_with(configured, dash, cli)
    put(config, "s120", GOOD)
    assert story_spec.first_environment(config, "s120") is dash


def test_first_environment_and_names_on_problems(configured: Path) -> None:
    config = configured_with(configured, Environment("cli", "package"))
    assert story_spec.first_environment(config, "s120") is None
    assert story_spec.environment_names(config, "s120") == []
    put(config, "s120", "no frontmatter")
    assert story_spec.first_environment(config, "s120") is None
    assert story_spec.environment_names(config, "s120") == []
