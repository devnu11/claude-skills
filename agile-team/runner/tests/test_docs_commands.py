"""s62 F1-F3: documented installs use ``--frozen``; CI uses ``--locked``."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

FROZEN_FILES = (
    "agile-team/SKILL.md",
    "agile-team/reference/*.md",
    "agile-team/docs/customer/*.md",
    "unattended/SKILL.md",
    "unattended/reference/*.md",
    "README.md",
)
WORKFLOWS = (".github/workflows/agile-team.yml", ".github/workflows/unattended.yml")
CI_PATHS = (
    "unattended/SKILL.md",
    "unattended/reference/**",
    "README.md",
    ".github/workflows/unattended.yml",
)
RUN = re.compile(r"\buv run\b[^\n`]*")
CI_STEP = re.compile(r"\buv (?:run|sync)\b[^\n]*")


def files(patterns: tuple[str, ...]) -> list[Path]:
    return sorted(p for pattern in patterns for p in ROOT.glob(pattern))


def unfrozen(text: str) -> list[str]:
    """The ``uv run`` commands that name a ``--project`` but not ``--frozen``."""
    return [m for m in RUN.findall(text) if "--project" in m and "--frozen" not in m]


def unlocked(text: str) -> list[str]:
    """The ``uv sync`` / ``uv run`` commands without ``--locked``."""
    return [m for m in CI_STEP.findall(text) if "--locked" not in m]


def test_the_checker_flags_a_line_without_frozen() -> None:
    assert unfrozen("run `uv run --project x agile-team start`") == [
        "uv run --project x agile-team start"
    ]
    assert unfrozen("uv run --frozen --project x agile-team start") == []
    assert unfrozen("uv run pytest") == []


def test_the_ci_checker_flags_a_step_without_locked() -> None:
    assert unlocked("- run: uv sync --dev") == ["uv sync --dev"]
    assert unlocked("- run: uv run --locked ruff check .") == []


def test_every_pattern_finds_files() -> None:
    for pattern in FROZEN_FILES:
        assert files((pattern,)), pattern


@pytest.mark.parametrize("path", files(FROZEN_FILES), ids=lambda p: str(p.relative_to(ROOT)))
def test_documented_project_commands_are_frozen(path: Path) -> None:
    assert unfrozen(path.read_text()) == []


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_steps_are_locked(name: str) -> None:
    text = (ROOT / name).read_text()
    assert CI_STEP.findall(text), name
    assert unlocked(text) == []


def test_agile_team_workflow_watches_the_files_the_test_reads() -> None:
    text = (ROOT / WORKFLOWS[0]).read_text()
    for section in ("push:", "pull_request:"):
        block = text.split(section, 1)[1].split("paths:", 1)[1].splitlines()[0]
        for entry in CI_PATHS:
            assert f'"{entry}"' in block, (section, entry)
