"""s12 end to end: the Proxy's OS sandbox refuses every shell escape form (cd, ~, $VAR, ...)."""

from __future__ import annotations

import copy
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import sandbox

from .scripted_cli import PROXY_SANDBOX_PLATFORMS, PROXY_SANDBOX_SKIP, CliRun, run_scripted

pytestmark = pytest.mark.skipif(
    sys.platform not in PROXY_SANDBOX_PLATFORMS, reason=PROXY_SANDBOX_SKIP
)

MARKER = "s12-secret-6c1f"
SECRET_LINE = f'MARKER = "{MARKER}"\n'


@dataclass(frozen=True)
class Probe:
    """One escape form: a shell command that prints MARKER if the read works."""

    name: str
    command: str


@dataclass(frozen=True)
class ProbeLayout:
    """Where the repo, the CLI's home and its working directory are."""

    repo: Path
    home: Path
    workdir: Path


@dataclass(frozen=True)
class Section:
    """One probe's output and exit code, parsed from the tool result."""

    output: str
    code: int


def _cd_up(layout: ProbeLayout) -> str:
    steps = len(Path(os.path.relpath(layout.repo, layout.workdir)).parts)
    return " && ".join(["cd .."] * steps) + " && cat src/secret.txt"


def _case_row(layout: ProbeLayout) -> list[Probe]:
    if not (layout.home / "REPO" / "src" / "secret.txt").exists():
        return []
    return [Probe("case", f"cat {shlex.quote(str(layout.home))}/REPO/src/secret.txt")]


def probes(layout: ProbeLayout) -> list[Probe]:
    """The table of escape probes (E1)."""
    r = shlex.quote(str(layout.repo))
    bare_root = shlex.quote(str(layout.repo).lstrip("/"))
    table = [
        Probe("cd-up", _cd_up(layout)),
        Probe("cd-home", "cd && cat repo/src/secret.txt"),
        Probe("cd-root", f"cd / && cat {bare_root}/src/secret.txt"),
        Probe("tilde", "cat ~/repo/src/secret.txt"),
        Probe("home-var", 'cat "$HOME/repo/src/secret.txt"'),
        Probe("env-var", 'cat "$S12_SECRET_DIR/secret.txt"'),
        Probe("shell-var", f'S="{layout.repo}/src"; cat "$S/secret.txt"'),
        Probe("command-sub", f'cat "$(printf %s {r})/src/secret.txt"'),
        Probe("wildcard", f"cat {r}/s?c/secret.*"),
        Probe("option-glued", f"echo '{SECRET_LINE.strip()}' | grep --file={r}/src/secret.txt"),
    ]
    return table + _case_row(layout)


def probe_script(rows: list[Probe]) -> str:
    """One script: each probe in a subshell, between labelled markers."""
    block = "printf '\\n@@ %s\\n' {name}; ( {command} ) 2>&1; printf '\\n@@ exit=%s\\n' $?"
    return "; ".join(block.format(name=p.name, command=p.command) for p in rows)


SECTION = re.compile(r"\n@@ (?P<name>[^\n]+)\n(?P<out>.*?)\n@@ exit=(?P<code>\d+)", re.S)


def sections(text: str) -> dict[str, Section]:
    """Parse the tool result back into one Section per probe name."""
    return {m["name"]: Section(m["out"], int(m["code"])) for m in SECTION.finditer(text)}


def bare(settings: dict) -> dict:
    """The settings with the sandbox and permissions off (E3 control)."""
    out = copy.deepcopy(settings)
    out["sandbox"]["enabled"] = False
    out.pop("permissions", None)
    return out


@pytest.fixture
def escape(configured: Path, tmp_path: Path):
    (configured / "src" / "secret.txt").write_text(SECRET_LINE)
    c = cfg.load(configured)
    prepared = sandbox.layout(c, c.environments[0])
    settings = sandbox.os_sandbox_settings(c, prepared)
    rows = probes(ProbeLayout(configured, tmp_path, prepared.workdir))
    return settings, prepared, rows, configured


def run_probes(escape, tmp_path: Path, settings: dict) -> dict[str, Section]:
    """Run every probe through the CLI under ``settings``; return the parsed sections."""
    _, prepared, rows, repo = escape
    env = {"S12_SECRET_DIR": f"{repo}/src"}
    run = CliRun(settings, prepared.workdir, tmp_path, tmp_path / "cli-config", env)
    code, results = run_scripted(run, probe_script(rows))
    assert code == 0, results
    return sections("\n" + "\n".join(results))


def test_every_escape_probe_reads_the_secret_without_the_sandbox(escape, tmp_path) -> None:
    got = run_probes(escape, tmp_path, bare(escape[0]))
    broken = [p.name for p in escape[2] if p.name not in got or MARKER not in got[p.name].output]
    assert broken == [], got


def test_the_proxy_sandbox_refuses_every_escape_form(escape, tmp_path) -> None:
    got = run_probes(escape, tmp_path, escape[0])

    def leaked(name: str) -> bool:
        s = got.get(name)
        return s is None or MARKER in s.output or s.code == 0

    assert {p.name: leaked(p.name) for p in escape[2]} == {p.name: False for p in escape[2]}, got
