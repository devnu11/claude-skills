"""``agile-team init`` phase A: detect the stack and write the repo's team config.

No API calls. The liaison asks the human the questions in chat and passes the
answers as flags; ``--reconfigure`` fills in missing settings without
overwriting anything already in the file.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Any

import tomli_w

from .config import API_KEY_AUTH, CONFIG_NAME, DEFAULT_KEY_FILE, PIPELINE_STEPS, config_path
from .git_ops import Git
from .roles import REPO_ROLES, Layer, RoleBook

CHARTER = ".team/CLAUDE.md"
RUN_IGNORE = ".team/run/"
COMMIT_MESSAGE = "chore(team): onboard agile team"
ONBOARD_FILES = (CONFIG_NAME, ".gitignore", CHARTER, REPO_ROLES)
CHARTER_TEMPLATE = """\
# Team charter

Every role reads this file. Keep it short and specific to this repo.

## House rules

- (e.g. public API changes need an ADR)

## Domain vocabulary

- (term: meaning)

## Do not touch

- (paths or systems the team must leave alone)
"""


def load_presets() -> dict[str, dict[str, Any]]:
    """The packaged stack preset table."""
    text = resources.files("agile_team").joinpath("presets.toml").read_text()
    return tomllib.loads(text)


def detect(repo: Path, presets: dict[str, dict[str, Any]]) -> str | None:
    """Name of the first preset with a marker file in ``repo``."""
    return next(
        (name for name, p in presets.items() if any((repo / m).exists() for m in p["markers"])),
        None,
    )


def suggest_kind(repo: Path, preset: dict[str, Any]) -> str:
    """Likely delivery kind: ``web`` when package.json depends on a web framework."""
    web = set(preset.get("web_dependencies", []))
    pkg = repo / "package.json"
    if web and pkg.is_file():
        data = json.loads(pkg.read_text())
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        if web & set(deps):
            return "web"
    return preset.get("delivery", "manual")


class WriteMode(StrEnum):
    """Whether ``init`` may touch an existing config (keeping every value in it)."""

    CREATE = "create"
    RECONFIGURE = "reconfigure"


@dataclass
class Answers:
    """The human's answers to the init questions."""

    preset: str
    delivery_kind: str
    docs_dir: str = "docs"
    artifacts: str = "committed"
    key_file: str = DEFAULT_KEY_FILE
    budget_usd: float = 20.0
    cadence: str = "sprint"
    url: str = ""
    auth: str = API_KEY_AUTH
    mode: WriteMode = WriteMode.CREATE


def build_config(preset: dict[str, Any], answers: Answers) -> dict[str, Any]:
    """Fresh config data for ``answers`` on top of ``preset``."""
    return {
        "team": {
            "docs_dir": answers.docs_dir,
            "artifacts": answers.artifacts,
            "key_file": answers.key_file,
            "auth": answers.auth,
            "cadence": answers.cadence,
            "budget_usd": answers.budget_usd,
            "manager_every_pct": 25,
        },
        "toolchain": {
            "preset": answers.preset,
            **preset["commands"],
            "pragma": preset.get("pragma", ""),
            "globs": preset["globs"],
        },
        "gates": {"coverage": 95, "round_cap": 3, "steps": list(PIPELINE_STEPS)},
        "delivery": [delivery_entry(preset, answers)],
        "roles": {},
    }


def delivery_entry(preset: dict[str, Any], answers: Answers) -> dict[str, Any]:
    """The first ``[[delivery]]``: installable kinds reuse the preset's prepare step."""
    installed = {"prepare": preset.get("prepare", ""), "bin": preset.get("bin", [])}
    extras = {"package": installed, "script": installed, "web": {"prepare": "", "url": answers.url}}
    return {"name": "main", "kind": answers.delivery_kind, **extras.get(answers.delivery_kind, {})}


def merge_keep(existing: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """``fresh`` with every value already in ``existing`` kept as is."""
    merged = dict(fresh)
    for key, value in existing.items():
        both_tables = isinstance(value, dict) and isinstance(fresh.get(key), dict)
        merged[key] = merge_keep(value, fresh[key]) if both_tables else value
    return merged


def gitignore_lines(artifacts: str) -> list[str]:
    """``.team/run/`` always; the rest of ``.team/`` too when artifacts are ignored."""
    if artifacts == "ignored":
        return [RUN_IGNORE, ".team/*", "!.team/roles/", "!.team/CLAUDE.md"]
    return [RUN_IGNORE]


def ensure_lines(path: Path, lines: list[str]) -> None:
    """Append any of ``lines`` missing from ``path``."""
    current = path.read_text().splitlines() if path.is_file() else []
    missing = [ln for ln in lines if ln not in current]
    if missing:
        prefix = "" if not current or current[-1] == "" else "\n"
        with path.open("a") as fh:
            fh.write(prefix + "# agile-team\n" + "\n".join(missing) + "\n")


def write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def write_config(repo: Path, answers: Answers) -> None:
    """Write the config; on reconfigure keep every value already in the file."""
    path, data = config_path(repo), build_config(_preset(answers.preset), answers)
    if path.is_file():
        if answers.mode is not WriteMode.RECONFIGURE:
            raise FileExistsError(f"{CONFIG_NAME} exists; use --reconfigure")
        data = merge_keep(tomllib.loads(path.read_text()), data)
    path.write_text(tomli_w.dumps(data))


def _preset(name: str) -> dict[str, Any]:
    presets = load_presets()
    if name not in presets:
        raise ValueError(f"unknown preset {name!r}; known: {sorted(presets)}")
    return presets[name]


def onboard(repo: Path, answers: Answers) -> str | None:
    """Run phase A and commit the result; returns the commit sha (None if nothing changed)."""
    write_config(repo, answers)
    ensure_lines(repo / ".gitignore", gitignore_lines(answers.artifacts))
    write_if_missing(repo / CHARTER, CHARTER_TEMPLATE)
    RoleBook.for_repo(repo, {}).scaffold(repo / REPO_ROLES, Layer.REPO)
    return commit_onboarding(Git(repo))


def commit_onboarding(git: Git) -> str | None:
    if not git.changed_paths():
        return None
    paths = [p for p in ONBOARD_FILES if not git.is_ignored(p)]
    return git.commit(paths, COMMIT_MESSAGE)
