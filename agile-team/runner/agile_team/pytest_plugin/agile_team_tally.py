"""Live test counts for the agile-team runner (s118 AC6), loaded through PYTEST_PLUGINS.

It does something only where AGILE_TEAM_TALLY names a file. Imports nothing from agile_team.
"""

import contextlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ENV = "AGILE_TEAM_TALLY"
PLUGIN = "agile_team_tally"
WRITE_EVERY_S = 0.5
RANKS = {"passed": 1, "skipped": 2, "xfailed": 2, "xpassed": 2, "failed": 3, "error": 3}


def unlisted(value: str) -> str:
    """``value`` (a comma list of plugins) without this plugin."""
    return ",".join(name for name in value.split(",") if name and name != PLUGIN)


def _unlist_plugin() -> None:
    kept = unlisted(os.environ.get("PYTEST_PLUGINS", ""))
    if kept:
        os.environ["PYTEST_PLUGINS"] = kept
    else:
        os.environ.pop("PYTEST_PLUGINS", None)


def pytest_configure(config: pytest.Config) -> None:
    """Pop ENV; when it names a file, register a Recorder for it."""
    path = os.environ.pop(ENV, "")
    _unlist_plugin()
    if path:
        config.pluginmanager.register(Recorder(Path(path), config), "agile-team-tally")


@dataclass(eq=False)
class Recorder:
    """Counts this session's tests and writes the record to ``path``."""

    path: Path
    config: pytest.Config
    session_id: str = field(default_factory=lambda: f"{os.getpid()}-{time.time():.3f}")
    total: int | None = None
    ranks: dict[str, int] = field(default_factory=dict)
    done: set[str] = field(default_factory=set)
    warned: set[str] = field(default_factory=set)
    written_at: float = -math.inf

    def pytest_collection_finish(self, session: Any) -> None:
        """Take the total from the collected items."""
        with contextlib.suppress(Exception):
            if len(session.items) > 0:
                self.total = len(session.items)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, ids: Any) -> None:
        """On the xdist controller, keep the largest collection."""
        with contextlib.suppress(Exception):
            self.total = max(self.total or 0, len(ids))

    def pytest_runtest_logreport(self, report: Any) -> None:
        """Fold the report; a teardown report marks the test done."""
        with contextlib.suppress(Exception):
            hook = self.config.hook.pytest_report_teststatus
            category = hook(report=report, config=self.config)[0]
            rank = RANKS.get(category, 0)
            self.ranks[report.nodeid] = max(self.ranks.get(report.nodeid, 0), rank)
            if report.when == "teardown":
                self.done.add(report.nodeid)
            self._write_when_due()

    @pytest.hookimpl(optionalhook=True)
    def pytest_warning_recorded(self, when: str, nodeid: str) -> None:
        """A warning during a test moves it to Warn."""
        with contextlib.suppress(Exception):
            if when == "runtest" and nodeid:
                self.warned.add(nodeid)
                self._write_when_due()

    def pytest_sessionfinish(self) -> None:
        """Write the final record."""
        with contextlib.suppress(Exception):
            self._write()

    def outcome(self, nodeid: str) -> str:
        """The one count a done test belongs to."""
        rank = self.ranks.get(nodeid, 0)
        if rank == 3:
            return "failed"
        if nodeid in self.warned:
            return "warned"
        return "skipped" if rank == 2 else "passed"

    def record(self) -> dict[str, Any]:
        """The session, the total and the four counts."""
        outcomes = [self.outcome(nodeid) for nodeid in self.done]
        counts = {key: outcomes.count(key) for key in ("passed", "warned", "skipped", "failed")}
        return {"session": self.session_id, "total": self.total, **counts}

    def _write_when_due(self) -> None:
        if time.monotonic() - self.written_at >= WRITE_EVERY_S:
            self._write()

    def _write(self) -> None:
        self.written_at = time.monotonic()
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(self.record()))
        os.replace(temp, self.path)
