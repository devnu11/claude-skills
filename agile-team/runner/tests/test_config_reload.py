"""s173: the run follows the committed ``.agile-team.toml`` (ADR-0094; REQ-262 to REQ-264)."""

from __future__ import annotations

import copy
import dataclasses
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from agile_team import config as config_mod
from agile_team import config_reload as cr
from agile_team.dispatch import Runtime
from agile_team.events import EventKind
from agile_team.git_ops import GitError

from .conftest import PY_CONFIG

SHA = "c0ffee" * 6 + "abcd"


class FakeGit:
    """The three git calls the watch makes, answered from a table of blob id -> text."""

    def __init__(self, blobs: dict[str, str], head: str | None, sha: str = SHA):
        self.blobs, self.head, self.sha = blobs, head, sha
        self.calls: list[tuple[str, ...]] = []

    def attempt(self, *args: str) -> tuple[int, str]:
        self.calls.append(args)
        if args[0] == "rev-parse":
            return (0, f"{self.head}\n") if self.head is not None else (128, "fatal\n")
        if args[0] == "log":
            return (0, f"{self.sha}\n") if self.sha else (128, "fatal\n")
        raise AssertionError(args)

    def run(self, *args: str) -> str:
        self.calls.append(args)
        assert args[:2] == ("cat-file", "blob")
        if args[2] not in self.blobs:
            raise GitError("no blob", None)  # type: ignore[arg-type]
        return self.blobs[args[2]]


def config_text(**changes: Any) -> str:
    """The test config as TOML text, with top-level sections replaced by ``changes``."""
    raw = copy.deepcopy(PY_CONFIG) | changes
    return tomli_w.dumps(raw)


def with_env(*names: str) -> str:
    rows = [{"name": n, "kind": "package", "prepare": "", "bin": ["bin"]} for n in names]
    return config_text(environment=rows)


def watched(make_runtime, blobs: dict[str, str], head: str | None, **kw: Any) -> Runtime:
    """A runtime whose git is the fake, already holding the first blob."""
    rt = make_runtime(**kw)
    rt.git = FakeGit(blobs, head)  # type: ignore[assignment]
    rt.config_blob = head
    return rt


def configs(rt: Runtime) -> list[Any]:
    return [e for e in rt.events.events() if e.kind is EventKind.CONFIG]


# ---------- config.parse_text ----------


def test_parse_text_parses_toml_s173() -> None:
    assert config_mod.parse_text("[team]\nbudget_usd = 3\n") == {"team": {"budget_usd": 3}}


def test_parse_text_names_the_file_on_bad_toml_s173() -> None:
    with pytest.raises(config_mod.ConfigError, match=r"^\.agile-team\.toml:"):
        config_mod.parse_text("[team\n")


# ---------- read_blob, find_last_change ----------


def test_read_blob_gives_the_head_blob_s173() -> None:
    git = FakeGit({}, "abc123")
    assert cr.read_blob(git) == "abc123"  # type: ignore[arg-type]
    assert git.calls == [("rev-parse", "HEAD:.agile-team.toml")]


def test_read_blob_is_empty_when_there_is_no_file_s173() -> None:
    assert cr.read_blob(FakeGit({}, None)) == ""  # type: ignore[arg-type]


def test_find_last_change_strips_the_log_output_s173() -> None:
    git = FakeGit({}, "b", sha="deadbeef")
    assert cr.find_last_change(git) == "deadbeef"  # type: ignore[arg-type]
    assert git.calls == [("log", "-1", "--format=%H", "HEAD", "--", ".agile-team.toml")]


def test_find_last_change_is_empty_on_failure_s173() -> None:
    assert cr.find_last_change(FakeGit({}, "b", sha="")) == ""  # type: ignore[arg-type]


# ---------- ConfigChange, find_changed_sections ----------


def test_a_config_change_data_is_the_event_payload_s173() -> None:
    change = cr.ConfigChange("s", "b", ["gates"], "")
    assert change.data == {"sha": "s", "blob": "b", "sections": ["gates"], "error": ""}


def parsed(text: str) -> config_mod.Config:
    return config_mod.from_raw(Path("/r"), config_mod.parse_text(text))


def test_sections_one_changed_environment_s173() -> None:
    assert cr.find_changed_sections(parsed(with_env("cli")), parsed(with_env("cli", "x"))) == [
        "environment"
    ]


def test_sections_come_in_table_order_s173() -> None:
    raw = copy.deepcopy(PY_CONFIG)
    raw["toolchain"]["test"] = "pytest -x"
    raw["gates"] = {"round_cap": 7}
    new = config_mod.from_raw(Path("/r"), raw)
    old = parsed(config_text())
    assert cr.find_changed_sections(old, new) == ["toolchain", "gates"]


def test_sections_of_equal_configs_are_empty_s173() -> None:
    assert cr.find_changed_sections(parsed(config_text()), parsed(config_text())) == []


def test_the_sections_table_covers_every_config_field_s173() -> None:
    not_sections = {"repo", "run_home", "warnings"}
    every = {f.name for f in dataclasses.fields(config_mod.Config)} - not_sections
    assert {field for field, _ in cr.SECTIONS} == every


def test_a_changed_upstream_section_builds_a_new_upstream_s173(make_runtime) -> None:
    rt = watched(make_runtime, {"b2": config_text(upstream={"branch": "trunk"})}, "b2")
    rt.config_blob = "b1"
    old = rt.upstream
    cr.ConfigWatch(rt).update()
    assert rt.upstream is not old
    assert rt.upstream.settings.branch == "trunk"
    assert rt.upstream.settings is rt.config.upstream


def test_a_change_to_another_section_keeps_the_upstream_s173(make_runtime) -> None:
    rt = watched(make_runtime, {"b2": with_env("cli", "x")}, "b2")
    rt.config_blob = "b1"
    old = rt.upstream
    cr.ConfigWatch(rt).update()
    assert rt.upstream is old


# ---------- ConfigWatch.update ----------


def test_the_first_check_of_an_unset_blob_only_records_it_s173(make_runtime) -> None:
    rt = watched(make_runtime, {}, "b1")
    rt.config_blob = None
    assert cr.ConfigWatch(rt).update() is None
    assert rt.config_blob == "b1" and configs(rt) == []


def test_the_same_blob_does_nothing_s173(make_runtime) -> None:
    rt = watched(make_runtime, {"b1": config_text()}, "b1")
    assert cr.ConfigWatch(rt).update() is None
    assert configs(rt) == []
    assert all(call[0] != "cat-file" for call in rt.git.calls)  # type: ignore[attr-defined]


def test_a_new_blob_is_taken_and_logged_once_s173(make_runtime) -> None:
    rt = watched(make_runtime, {"b2": with_env("cli", "house-rules")}, "b1")
    rt.git.head = "b2"  # type: ignore[attr-defined]
    old = rt.config
    change = cr.ConfigWatch(rt).update()
    assert change == cr.ConfigChange(SHA, "b2", ["environment"], "")
    assert [e.name for e in rt.config.environments] == ["cli", "house-rules"]
    assert rt.config is not old and rt.config.run_home == old.run_home
    assert rt.config_blob == "b2"
    (event,) = configs(rt)
    assert event.data == change.data and event.role is None and event.story is None
    assert cr.ConfigWatch(rt).update() is None
    assert len(configs(rt)) == 1


def test_a_taken_change_swaps_the_derived_parts_by_assignment_s173(make_runtime) -> None:
    rt = watched(make_runtime, {"b2": config_text()}, "b2")
    rt.config_blob = "b1"
    old = (rt.book, rt.pipeline, rt.providers, rt.shell)
    live = cr.LiveConfig(rt.config, old[0], copy.copy(rt.pipeline), old[2], old[3])
    rt.live_for = lambda config: live
    cr.ConfigWatch(rt).update()
    assert rt.pipeline is live.pipeline and rt.book is live.book
    assert rt.pipeline.checks.stages == rt.stage_log.open


def test_a_comment_only_commit_logs_one_event_with_no_sections_s173(make_runtime) -> None:
    rt = watched(make_runtime, {"b2": "# hi\n" + config_text()}, "b1")
    rt.git.head = "b2"  # type: ignore[attr-defined]
    change = cr.ConfigWatch(rt).update()
    assert change is not None and change.sections == [] and change.error == ""
    assert len(configs(rt)) == 1


def test_a_changed_budget_applies_at_once_s173(make_runtime) -> None:
    rt = watched(
        make_runtime, {"b2": config_text(team={**PY_CONFIG["team"], "budget_usd": 99.0})}, "b1"
    )
    rt.git.head = "b2"  # type: ignore[attr-defined]
    change = cr.ConfigWatch(rt).update()
    assert change is not None and change.sections == ["team"]
    assert rt.config.team.budget_usd == 99.0


BAD_BLOBS = {
    "toml": ("[team\n", "ConfigError", ".agile-team.toml:"),
    "rule": (config_text(team={"budget_usd": -1}), "ConfigError", "budget_usd"),
    "shape": (config_text(team=3), "AttributeError", "AttributeError:"),
}


@pytest.mark.parametrize("kind", sorted(BAD_BLOBS))
def test_a_bad_blob_keeps_the_last_good_config_and_logs_once_s173(make_runtime, kind) -> None:
    text, _, shown = BAD_BLOBS[kind]
    rt = watched(make_runtime, {"bad": text}, "b1")
    rt.git.head = "bad"  # type: ignore[attr-defined]
    config, pipeline = rt.config, rt.pipeline
    change = cr.ConfigWatch(rt).update()
    assert change is not None and shown in change.error and change.sections == []
    assert rt.config is config and rt.pipeline is pipeline and rt.config_blob == "bad"
    assert cr.ConfigWatch(rt).update() is None
    (event,) = configs(rt)
    assert event.data["error"] == change.error and event.data["sections"] == []


def test_a_missing_file_is_reported_once_s173(make_runtime) -> None:
    rt = watched(make_runtime, {}, "b1")
    rt.git.head = None  # type: ignore[attr-defined]
    change = cr.ConfigWatch(rt).update()
    assert change is not None and "not found at HEAD" in change.error
    assert all(call[0] != "cat-file" for call in rt.git.calls)  # type: ignore[attr-defined]
    assert cr.ConfigWatch(rt).update() is None


def test_a_valid_commit_after_a_bad_one_is_compared_with_the_last_good_s173(make_runtime) -> None:
    blobs = {"bad": "[team\n", "ok": with_env("cli", "x")}
    rt = watched(make_runtime, blobs, "b1")
    rt.git.head = "bad"  # type: ignore[attr-defined]
    cr.ConfigWatch(rt).update()
    rt.git.head = "ok"  # type: ignore[attr-defined]
    change = cr.ConfigWatch(rt).update()
    assert change is not None and change.error == "" and change.sections == ["environment"]
    assert len(configs(rt)) == 2


def test_an_unknown_role_in_the_new_config_is_refused_s173(make_runtime) -> None:
    text = config_text(roles={"x": {"file": "nope.md"}})
    rt = watched(make_runtime, {"b2": text}, "b1")
    rt.git.head = "b2"  # type: ignore[attr-defined]
    change = cr.ConfigWatch(rt).update()
    assert change is not None and change.error and rt.config_blob == "b2"


def test_check_static_lists_problems_s173(make_runtime) -> None:
    rt = make_runtime()
    assert cr.check_static(rt.config, rt.book) == []
    rt.config.team.budget_usd = -1
    assert cr.check_static(rt.config, rt.book)
