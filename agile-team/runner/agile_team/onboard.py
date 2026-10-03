"""``agile-team init`` phase A: detect the stack and write the repo's team config.

No API calls. The liaison asks the human the questions in chat and passes the
answers as flags; ``--reconfigure`` fills in missing settings without
overwriting anything already in the file.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import tomli_w

from .config import CONFIG_NAME, DEFAULT_KEY_FILE, PIPELINE_STEPS, config_path
from .git_ops import Git

CHARTER = ".team/CLAUDE.md"
ROLES_KEEP = ".team/roles/.gitkeep"
RUN_IGNORE = ".team/run/"
COMMIT_MESSAGE = "chore(team): onboard agile team"
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


def build_config(name: str, preset: dict[str, Any], answers: Answers) -> dict[str, Any]:
    """Fresh config data for ``answers`` on top of ``preset``."""
    delivery: dict[str, Any] = {"name": "main", "kind": answers.delivery_kind}
    if answers.delivery_kind in ("package", "script"):
        delivery.update(prepare=preset.get("prepare", ""), bin=preset.get("bin", []))
    if answers.delivery_kind == "web":
        delivery.update(prepare="", url=answers.url)
    return {
        "team": {
            "docs_dir": answers.docs_dir,
            "artifacts": answers.artifacts,
            "key_file": answers.key_file,
            "cadence": answers.cadence,
            "budget_usd": answers.budget_usd,
            "manager_every_pct": 25,
        },
        "toolchain": {
            "preset": name,
            **preset["commands"],
            "pragma": preset.get("pragma", ""),
            "globs": preset["globs"],
        },
        "gates": {"coverage": 95, "round_cap": 3, "steps": list(PIPELINE_STEPS)},
        "delivery": [delivery],
        "roles": {},
    }


def merge_keep(existing: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """``fresh`` with every value already in ``existing`` kept as is."""
    merged = dict(fresh)
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(fresh.get(key), dict):
            merged[key] = merge_keep(value, fresh[key])
        else:
            merged[key] = value
    return merged


def gitignore_lines(artifacts: str) -> list[str]:
    """``.team/run/`` always; the rest of ``.team/`` too when artifacts are ignored."""
    if artifacts == "ignored":
        return [RUN_IGNORE, ".team/*", "!.team/roles/", "!.team/CLAUDE.md"]
    return [RUN_IGNORE]


def ensure_lines(path: Path, lines: list[str]) -> bool:
    """Append any of ``lines`` missing from ``path``; True when the file changed."""
    current = path.read_text().splitlines() if path.is_file() else []
    missing = [ln for ln in lines if ln not in current]
    if not missing:
        return False
    prefix = "" if not current or current[-1] == "" else "\n"
    with path.open("a") as fh:
        fh.write(prefix + "# agile-team\n" + "\n".join(missing) + "\n")
    return True


def write_if_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def write_config(repo: Path, data: dict[str, Any], reconfigure: bool) -> None:
    """Write the config, keeping existing values when reconfiguring."""
    path = config_path(repo)
    if path.is_file():
        if not reconfigure:
            raise FileExistsError(f"{CONFIG_NAME} exists; use --reconfigure")
        data = merge_keep(tomllib.loads(path.read_text()), data)
    path.write_text(tomli_w.dumps(data))


def onboard(repo: Path, answers: Answers, reconfigure: bool = False) -> str | None:
    """Run phase A and commit the result; returns the commit sha (None if nothing changed)."""
    presets = load_presets()
    if answers.preset not in presets:
        raise ValueError(f"unknown preset {answers.preset!r}; known: {sorted(presets)}")
    data = build_config(answers.preset, presets[answers.preset], answers)
    write_config(repo, data, reconfigure)
    ensure_lines(repo / ".gitignore", gitignore_lines(answers.artifacts))
    write_if_missing(repo / CHARTER, CHARTER_TEMPLATE)
    write_if_missing(repo / ROLES_KEEP, "")
    git = Git(repo)
    paths = [p for p in (CONFIG_NAME, ".gitignore", CHARTER, ROLES_KEEP) if not git.is_ignored(p)]
    if not git.changed_paths():
        return None
    return git.commit(paths, COMMIT_MESSAGE)
