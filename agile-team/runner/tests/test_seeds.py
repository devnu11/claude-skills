"""s105: seeds.py plants a delivery's seed files in a presentation workspace and checks them."""

from __future__ import annotations

from pathlib import Path

from agile_team import config as cfg
from agile_team import seeds, system
from agile_team.config import Delivery
from agile_team.seeds import Seeds

from .fake_system import FAKE_ROOT

GOOD = '[dashboard]\ntoken = "presentation"\n'
SOURCE = FAKE_ROOT / "repo" / "seed"
WORKSPACE = FAKE_ROOT / "ws" / "workspace"


def seed_with(**files: str) -> Seeds:
    """A seed dir holding ``files`` and a workspace that does not exist yet."""
    system.make_dirs(SOURCE)
    for name, text in files.items():
        system.write_text(SOURCE / name, text)
    return Seeds(SOURCE, WORKSPACE)


def config_seed(text: str = GOOD) -> Seeds:
    system.make_dirs(SOURCE)
    system.write_text(SOURCE / cfg.CONFIG_NAME, text)
    return Seeds(SOURCE, WORKSPACE)


# ----- config ---------------------------------------------------------------


def test_delivery_seed_defaults_to_none() -> None:
    assert Delivery("a", "web").seed is None


def test_delivery_seed_loads_from_the_config(repo: Path) -> None:
    raw = {"delivery": [{"name": "a", "kind": "web", "seed": "x/y"}, {"name": "b", "kind": "web"}]}
    c = cfg.from_raw(repo, raw)
    assert [d.seed for d in c.deliveries] == ["x/y", None]


# ----- seed_dir -------------------------------------------------------------


def test_seed_dir_without_a_delivery_is_none() -> None:
    assert seeds.seed_dir(FAKE_ROOT, None) is None


def test_seed_dir_with_an_empty_seed_is_none_not_the_repo() -> None:
    assert seeds.seed_dir(FAKE_ROOT, Delivery("a", "web", seed="")) is None


def test_seed_dir_of_a_web_delivery_without_a_key_is_the_packaged_seed() -> None:
    assert seeds.seed_dir(FAKE_ROOT, Delivery("a", "web")) == seeds.PACKAGED_SEED


def test_seed_dir_of_a_package_delivery_without_a_key_is_none() -> None:
    assert seeds.seed_dir(FAKE_ROOT, Delivery("a", "package")) is None


def test_default_seeds_and_packaged_seed_location() -> None:
    import agile_team

    assert seeds.DEFAULT_SEEDS == {"web": seeds.PACKAGED_SEED}
    assert seeds.PACKAGED_SEED == Path(agile_team.__file__).parent / "dashboard" / "seed"


def test_packaged_seed_names_and_config_are_valid() -> None:
    assert Seeds(seeds.PACKAGED_SEED, WORKSPACE).names() == [cfg.CONFIG_NAME]
    assert seeds.config_problem(seeds.PACKAGED_SEED / cfg.CONFIG_NAME) is None
    assert cfg.load(seeds.PACKAGED_SEED).dashboard.token == "presentation"


def test_seed_dir_joins_the_repo_and_the_seed() -> None:
    d = Delivery("a", "web", seed="a/b")
    assert seeds.seed_dir(FAKE_ROOT, d) == FAKE_ROOT / "a/b"


# ----- names ----------------------------------------------------------------


def test_names_of_no_source_is_empty() -> None:
    assert Seeds(None, WORKSPACE).names() == []


def test_names_of_a_missing_dir_is_empty() -> None:
    assert Seeds(SOURCE, WORKSPACE).names() == []


def test_names_are_the_direct_files_sorted_and_skip_subdirectories() -> None:
    s = seed_with(zed="z", alpha="a")
    system.make_dirs(SOURCE / "sub")
    system.write_text(SOURCE / "sub" / "deep", "d")
    assert s.names() == ["alpha", "zed"]


# ----- plant ----------------------------------------------------------------


def test_plant_writes_a_missing_file_and_creates_the_workspace() -> None:
    config_seed().plant()
    assert system.read_text(WORKSPACE / cfg.CONFIG_NAME) == GOOD


def test_plant_keeps_an_existing_file_byte_for_byte() -> None:
    s = config_seed()
    system.make_dirs(WORKSPACE)
    mine = '[dashboard]\ntoken = "mine"\n'
    system.write_text(WORKSPACE / cfg.CONFIG_NAME, mine)
    s.plant()
    assert system.read_text(WORKSPACE / cfg.CONFIG_NAME) == mine


def test_plant_leaves_a_directory_at_the_name_alone() -> None:
    s = config_seed()
    system.make_dirs(WORKSPACE / cfg.CONFIG_NAME)
    s.plant()
    assert system.is_dir(WORKSPACE / cfg.CONFIG_NAME)


def test_plant_plants_only_the_missing_files() -> None:
    s = seed_with(a="seed-a", b="seed-b")
    system.make_dirs(WORKSPACE)
    system.write_text(WORKSPACE / "a", "mine")
    s.plant()
    assert system.read_text(WORKSPACE / "a") == "mine"
    assert system.read_text(WORKSPACE / "b") == "seed-b"


def test_plant_with_no_source_writes_nothing_and_makes_no_workspace() -> None:
    Seeds(None, WORKSPACE).plant()
    assert not system.exists(WORKSPACE)


def test_plant_with_an_empty_source_makes_no_workspace() -> None:
    system.make_dirs(SOURCE)
    Seeds(SOURCE, WORKSPACE).plant()
    assert not system.exists(WORKSPACE)


# ----- problems -------------------------------------------------------------


def test_problems_is_empty_without_a_source() -> None:
    assert Seeds(None, WORKSPACE).problems() == []


def test_problems_names_a_seed_dir_that_is_gone() -> None:
    assert Seeds(SOURCE, WORKSPACE).problems() == [seeds.SEED_GONE.format(source=SOURCE)]


def test_problems_flags_an_unparsable_config() -> None:
    s = config_seed()
    system.make_dirs(WORKSPACE)
    system.write_text(WORKSPACE / cfg.CONFIG_NAME, "[dashboard\n")
    (line,) = s.problems()
    assert line.startswith("workspace/.agile-team.toml is broken: ")
    assert line.endswith("or delete it so the runner seeds a working one")


def test_problems_flags_a_mistyped_token() -> None:
    s = config_seed()
    system.make_dirs(WORKSPACE)
    system.write_text(WORKSPACE / cfg.CONFIG_NAME, "[dashboard]\ntoken = 5\n")
    (line,) = s.problems()
    assert cfg.DASHBOARD_TOKEN in line


def test_problems_of_a_good_config_is_empty() -> None:
    s = config_seed()
    s.plant()
    assert s.problems() == []


def test_problems_of_a_seed_not_yet_planted_is_empty() -> None:
    assert config_seed().problems() == []


def test_problems_ignores_a_broken_file_with_no_check() -> None:
    s = seed_with(other="x")
    system.make_dirs(WORKSPACE)
    system.write_text(WORKSPACE / "other", "garbage [")
    assert s.problems() == []


# ----- checks table ---------------------------------------------------------


def test_the_only_check_is_the_config() -> None:
    assert list(seeds.CHECKS.items()) == [(cfg.CONFIG_NAME, seeds.config_problem)]


def test_config_problem_is_none_for_a_good_file() -> None:
    system.make_dirs(WORKSPACE)
    system.write_text(WORKSPACE / cfg.CONFIG_NAME, GOOD)
    assert seeds.config_problem(WORKSPACE / cfg.CONFIG_NAME) is None


def test_config_problem_reports_a_mistyped_table() -> None:
    system.make_dirs(WORKSPACE)
    system.write_text(WORKSPACE / cfg.CONFIG_NAME, "dashboard = 5\n")
    assert seeds.config_problem(WORKSPACE / cfg.CONFIG_NAME)


def test_texts_are_exact() -> None:
    assert seeds.SEED_GONE == (
        "seed directory {source} is missing from the repo; restore it or remove "
        "`seed` from the delivery in .agile-team.toml"
    )
    assert seeds.BROKEN == (
        "workspace/{name} is broken: {error}. Fix it in the presentation's "
        "workspace/, or delete it so the runner seeds a working one"
    )
