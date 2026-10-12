"""Repo settings: ``.house-rules.toml`` or ``[tool.house-rules]``, validated on load."""

from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any

from . import verbs
from .model import Level, Limits
from .rules import RULE_IDS

CONFIG_FILE = ".house-rules.toml"
PYPROJECT = "pyproject.toml"
DEFAULT_INCLUDE = ("**/*.py",)
DEFAULT_EXCLUDE = ("**/.venv/**", "**/build/**", "**/dist/**", "**/node_modules/**")
DEFAULT_TEST_GLOBS = ("**/tests/**", "**/test_*.py", "**/*_test.py", "**/conftest.py")
DEFAULT_FACTORY_NAMES = ("create", "create_{class}", "from_*")
DEFAULT_BASELINE = ".house-rules-baseline.json"


class ConfigError(Exception):
    """The settings file is missing a value's right type, or names an unknown key or rule."""


class TestPolicy(StrEnum):
    """Whether test files are checked."""

    __test__ = False  # not a pytest test class
    SKIP = "skip"
    CHECK = "check"


@dataclass(frozen=True)
class Settings:
    """Everything a check reads from the repo. The defaults are the human's global rules."""

    root: Path
    include: tuple[str, ...] = DEFAULT_INCLUDE
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    tests: TestPolicy = TestPolicy.SKIP
    test_globs: tuple[str, ...] = DEFAULT_TEST_GLOBS
    limits: Mapping[str, Limits] = field(default_factory=dict)
    severity: Mapping[str, Level] = field(default_factory=dict)
    disable: frozenset[str] = frozenset()
    verbs: frozenset[str] = frozenset()
    synonyms: Mapping[str, str] = field(default_factory=dict)
    allow_names: tuple[str, ...] = ()
    factory_names: tuple[str, ...] = DEFAULT_FACTORY_NAMES
    baseline: str = DEFAULT_BASELINE

    @cached_property
    def known_synonyms(self) -> dict[str, str]:
        """The built-in synonym map with the repo's additions."""
        return {**verbs.SYNONYMS, **self.synonyms}

    @cached_property
    def known_verbs(self) -> frozenset[str]:
        """Every word a function name may start with."""
        return verbs.VERBS | self.verbs | set(self.known_synonyms)

    @property
    def baseline_path(self) -> Path:
        """Where the baseline file lives."""
        return self.root / self.baseline


def load_settings(start: Path) -> Settings:
    """The settings for ``start``: the nearest config file above it, else the defaults."""
    found = find_config(start.resolve())
    root = found.parent if found else find_root(start.resolve())
    table = read_table(found) if found else {}
    return build_settings(root, table)


def find_config(start: Path) -> Path | None:
    """The nearest ``.house-rules.toml``, or ``pyproject.toml`` with a house-rules table."""
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_FILE
        if candidate.is_file():
            return candidate
        pyproject = directory / PYPROJECT
        if pyproject.is_file() and "house-rules" in read_toml(pyproject).get("tool", {}):
            return pyproject
    return None


def find_root(start: Path) -> Path:
    """The git work tree holding ``start``, or ``start`` itself outside git."""
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else start


def read_toml(path: Path) -> dict[str, Any]:
    """The parsed TOML file, or a ``ConfigError`` naming it."""
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error


def read_table(path: Path) -> dict[str, Any]:
    """The house-rules table of a config file."""
    data = read_toml(path)
    return data["tool"]["house-rules"] if path.name == PYPROJECT else data


def build_settings(root: Path, table: Mapping[str, Any]) -> Settings:
    """Validate ``table`` and build the settings from it."""
    unknown = sorted(set(table) - set(CONVERTERS))
    if unknown:
        raise ConfigError(f"unknown keys: {', '.join(unknown)}")
    return Settings(root, **{key: convert_value(key, value) for key, value in table.items()})


def convert_value(key: str, value: Any) -> Any:
    """``value`` as the type ``key`` takes, or a ``ConfigError`` naming the key."""
    try:
        return CONVERTERS[key](value)
    except (TypeError, ValueError, KeyError) as error:
        raise ConfigError(f"{key}: {error}") from error


def to_strings(value: Any) -> tuple[str, ...]:
    """A list of strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("expected a list of strings")
    return tuple(value)


def to_string(value: Any) -> str:
    """A string."""
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


def to_words(value: Any) -> frozenset[str]:
    """A set of lower-case words."""
    return frozenset(word.lower() for word in to_strings(value))


def to_rule_id(value: str) -> str:
    """A known rule id; ``function_length`` is accepted for ``function-length``."""
    rule = value.replace("_", "-")
    if rule not in RULE_IDS:
        raise ValueError(f"unknown rule {value!r}")
    return rule


def to_rule_ids(value: Any) -> frozenset[str]:
    """A set of known rule ids."""
    return frozenset(to_rule_id(item) for item in to_strings(value))


def to_limits(value: Any) -> dict[str, Limits]:
    """``{rule = {warn = N, fail = M}}``."""
    return {to_rule_id(rule): Limits(**to_table(pair)) for rule, pair in to_table(value).items()}


def to_severity(value: Any) -> dict[str, Level]:
    """``{rule = "warn" | "fail"}``."""
    return {to_rule_id(rule): Level(level) for rule, level in to_table(value).items()}


def to_synonyms(value: Any) -> dict[str, str]:
    """``{synonym = "canonical verb"}``."""
    return {word.lower(): to_string(canonical) for word, canonical in to_table(value).items()}


def to_table(value: Any) -> dict[str, Any]:
    """A TOML table."""
    if not isinstance(value, dict):
        raise TypeError("expected a table")
    return value


CONVERTERS: dict[str, Callable[[Any], Any]] = {
    "include": to_strings,
    "exclude": to_strings,
    "tests": TestPolicy,
    "test_globs": to_strings,
    "limits": to_limits,
    "severity": to_severity,
    "disable": to_rule_ids,
    "verbs": to_words,
    "synonyms": to_synonyms,
    "allow_names": to_strings,
    "factory_names": to_strings,
    "baseline": to_string,
}
