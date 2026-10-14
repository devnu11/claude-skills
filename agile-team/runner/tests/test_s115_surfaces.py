"""s115: ops-review on the dashboard, in the snapshot and in the cli pipeline."""

from importlib import resources
from pathlib import Path

import tomli_w
from agile_team import cli, system
from agile_team import config as cfg
from agile_team.dashboard import snapshot

from .test_snapshot import book_for, build, config, rewrite_config  # noqa: F401

PAGE = system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))
GROUPS = PAGE.split("const FLOW_GROUPS = [")[1].split("];")[0]
TEST_GROUP = next(line for line in GROUPS.splitlines() if '"Test"' in line)


def test_the_flow_test_group_lists_ops_review_before_tests() -> None:
    steps = TEST_GROUP.split("steps:")[1]
    assert steps.index('"ops-review"') < steps.index('"tests"')


def test_the_flow_test_group_holds_devops() -> None:
    assert '"devops"' in TEST_GROUP.split("steps:")[0]


def test_the_snapshot_pipeline_puts_ops_review_after_design(config, scratch) -> None:  # noqa: F811
    pipeline = build(config, scratch)["pipeline"]
    assert pipeline[pipeline.index("design") + 1] == "ops-review"


def test_the_snapshot_step_roles_name_devops_for_ops_review(config, scratch) -> None:  # noqa: F811
    assert build(config, scratch)["step_roles"]["ops-review"] == ["devops"]


def test_a_config_without_ops_review_still_gets_it(config, scratch) -> None:  # noqa: F811
    rewrite_config(config, ["design", "tests", "implement"], 20.0, 3)
    pipeline = snapshot.build(config, book_for(config, scratch))["pipeline"]
    assert pipeline == ["design", "ops-review", "tests", "implement"]


def test_a_config_listing_it_elsewhere_gets_it_once_after_design(config, scratch) -> None:  # noqa: F811
    rewrite_config(config, ["design", "tests", "ops-review", "implement"], 20.0, 3)
    pipeline = snapshot.build(config, book_for(config, scratch))["pipeline"]
    assert pipeline == ["design", "ops-review", "tests", "implement"]


def test_make_pipeline_runs_the_built_pipeline(configured: Path) -> None:
    conf = cfg.load(configured)
    text = tomli_w.dumps({"gates": {"steps": ["design", "tests"]}})
    system.write_text(conf.repo / cfg.CONFIG_NAME, text)
    steps = cli.make_pipeline(cfg.load(configured)).steps
    assert list(steps) == ["design", "ops-review", "tests"]
