"""Settings: finding the file, validating it, defaults."""

from pathlib import Path

import pytest
from house_rules.config import ConfigError, Settings, TestPolicy, build_settings, load_settings
from house_rules.model import Level, Limits


def test_house_rules_toml_wins_and_sets_the_root(tmp_path: Path) -> None:
    (tmp_path / ".house-rules.toml").write_text('tests = "check"\nbaseline = "b.json"\n')
    nested = tmp_path / "pkg" / "sub"
    nested.mkdir(parents=True)
    settings = load_settings(nested)
    assert (settings.root, settings.tests, settings.baseline_path) == (
        tmp_path,
        TestPolicy.CHECK,
        tmp_path / "b.json",
    )


def test_pyproject_table_is_found(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.house-rules]\nverbs = ["Frob"]\n')
    assert "frob" in load_settings(tmp_path).known_verbs


def test_pyproject_without_the_table_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert load_settings(tmp_path).limits == {}


def test_no_config_outside_git_roots_at_the_start(tmp_path: Path) -> None:
    assert load_settings(tmp_path).root == tmp_path.resolve()


def test_every_key_converts(tmp_path: Path) -> None:
    table = {
        "include": ["src/**"], "exclude": ["gen/**"], "tests": "skip", "test_globs": ["t/**"],
        "limits": {"function_length": {"warn": 5, "fail": 9}}, "severity": {"verb-name": "warn"},
        "disable": ["query-property"], "verbs": ["Zap"], "synonyms": {"Zap": "remove"},
        "allow_names": ["do_*"], "factory_names": ["make_*"], "baseline": "b.json",
    }  # fmt: skip
    settings = build_settings(tmp_path, table)
    assert settings.limits == {"function-length": Limits(5, 9)}
    assert settings.severity == {"verb-name": Level.WARN}
    assert settings.disable == frozenset({"query-property"})
    assert settings.known_synonyms["zap"] == "remove"


@pytest.mark.parametrize(
    ("table", "message"),
    [({"colour": 1}, "unknown keys: colour"), ({"include": "x"}, "include: expected a list"),
     ({"disable": ["nope"]}, "disable: unknown rule 'nope'"),
     ({"limits": []}, "limits: expected a table"),
     ({"tests": "maybe"}, "tests:"), ({"baseline": 3}, "baseline: expected a string"),
     ({"limits": {"parameters": {"warn": 1}}}, "limits:")],
)  # fmt: skip
def test_invalid_settings_name_the_key(tmp_path: Path, table: dict, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        build_settings(tmp_path, table)


def test_bad_toml_names_the_file(tmp_path: Path) -> None:
    (tmp_path / ".house-rules.toml").write_text("tests = \n")
    with pytest.raises(ConfigError, match=r"\.house-rules\.toml"):
        load_settings(tmp_path)


def test_defaults_are_the_global_rules(tmp_path: Path) -> None:
    settings = Settings(tmp_path)
    assert settings.tests is TestPolicy.SKIP and "create" in settings.known_verbs


@pytest.mark.parametrize(
    "reason",
    [
        "name fixed by the tests",
        "name fixed by the s159 tests",
        "tool name fixed by the s163 design",
        "named by test_rewrite.py",
        "name fixed by a test file",
        "s163 design name",
        "the design's name",
        "the s159 tests use this name",
        "the design named it",
        "name fixed by the tests.",
        "NAME FIXED BY THE DESIGN",
        "name fixed by the tests  # expect: verb-name fail",
        "a test fixes the name",
        "test file fixed the name",
        "the e2e tests expect it",
        "tests require the tool name",
        "the tests pin this name",
        "kept because the s159 design chose it",
        "as named by the design",
        "name used in test_router.py",
        "the tests' name",
        "per the s159 design",
        "name fixed by the tests;",
        "name fixed by the tests!",
        "name fixed by the tests. ",
    ],
)
def test_an_excuse_reason_is_refused(tmp_path: Path, reason: str) -> None:
    assert Settings(tmp_path).is_excuse(reason) is True


@pytest.mark.parametrize(
    "reason",
    [
        "",
        "matches the CLI flag",
        "name fixed by the tests; it mirrors git's verb",
        "registry needs an instance",
        "the latest gh output sets the name",
        "a testing helper sets the name",
        "pytest needs this name for discovery",
        "the test helper mirrors git's verb",
    ],
)
def test_a_real_reason_is_accepted(tmp_path: Path, reason: str) -> None:
    assert Settings(tmp_path).is_excuse(reason) is False


def test_a_repo_extends_the_excuses_and_keeps_the_defaults(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, {"excuses": ["copied from upstream"]})
    assert settings.is_excuse("copied from upstream") is True
    assert settings.is_excuse("name fixed by the tests") is True


@pytest.mark.parametrize("value", ["x", ["("], [3]])
def test_bad_excuses_name_the_key(tmp_path: Path, value: object) -> None:
    with pytest.raises(ConfigError, match="excuses"):
        build_settings(tmp_path, {"excuses": value})
