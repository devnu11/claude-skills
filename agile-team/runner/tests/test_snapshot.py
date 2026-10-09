"""Snapshot builder: run files -> the dashboard's one JSON document (s4, D1-D10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from agile_team import config as cfg
from agile_team import state as state_mod
from agile_team.dashboard import snapshot
from agile_team.gates import StoryState, StoryStatus
from agile_team.roles import RoleBook
from agile_team.state import ModelOverride, RunState, RunStatus

FIXTURE = Path(snapshot.__file__).parent / "fixtures" / "snapshot.json"
KEYS = [
    "generated_at",
    "run",
    "pipeline",
    "roles",
    "stories",
    "requirements",
    "events",
    "ledger",
    "messages",
    "answers",
]


def shape(value: Any) -> Any:
    """Keys and value types; list items collapse to the set of their shapes."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted({json.dumps(shape(i), sort_keys=True) for i in value})
    return type(value).__name__


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def make_config(root: Path, steps: list[str] | None = None, **extra: Any) -> cfg.Config:
    root.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = {
        "team": {"docs_dir": "docs", "budget_usd": 20.0, "manager_every_pct": 25},
        "gates": {"round_cap": 3, "steps": steps or ["design", "tests", "implement"]},
        **extra,
    }
    (root / cfg.CONFIG_NAME).write_text(tomli_w.dumps(raw))
    return cfg.load(root)


def book_for(config: cfg.Config, tmp_path: Path) -> RoleBook:
    return RoleBook.for_repo(config.repo, config.roles, tmp_path / "no-global")


@pytest.fixture
def config(tmp_path: Path) -> cfg.Config:
    return make_config(tmp_path / "repo")


def build(config: cfg.Config, tmp_path: Path) -> dict[str, Any]:
    return json.loads(json.dumps(snapshot.build(config, book_for(config, tmp_path))))


def write_story_file(config: cfg.Config, sid: str, meta: str, body: str = "x\n") -> None:
    path = config.stories_dir / f"{sid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{meta}---\n{body}")


def write_run(root: Path, fixture: dict[str, Any]) -> cfg.Config:
    """Turn the fixture back into the run files it was derived from."""
    config = make_config(root, steps=fixture["pipeline"])
    run = fixture["run"]
    stories = {
        s["id"]: StoryState(
            s["id"],
            s["title"],
            s["step"],
            rounds=s["rounds"],
            status=StoryStatus(s["status"]),
            delivery=s["delivery"],
            sprint=s["sprint"],
        )
        for s in fixture["stories"]
    }
    state = RunState(
        cadence=run["cadence"],
        sprint=run["sprint"],
        status=RunStatus(run["status"]),
        stories=stories,
        manager_due=run["manager_due"],
        task=run["task"],
    )
    state_mod.save(config.run_dir, state)
    plain = [e for e in fixture["events"] if e["kind"] not in ("message", "answer")]
    write_jsonl(config.run_dir / "events.jsonl", plain)
    write_jsonl(config.run_dir / "ledger.jsonl", fixture["ledger"])
    write_jsonl(config.run_dir / "outbox.jsonl", fixture["messages"])
    write_jsonl(config.run_dir / "inbox.jsonl", fixture["answers"])
    for s in fixture["stories"]:
        meta = json.dumps({"id": s["id"], "title": s["title"], "acceptance": s["acceptance"]})
        write_story_file(config, s["id"], meta + "\n")
    for r in fixture["requirements"]:
        meta = json.dumps({k: r[k] for k in ("id", "title", "status", "covers")})
        path = config.requirements_dir / f"{r['id']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\n{meta}\n---\n{r['text']}\n")
    return config


# ----- 1. fixture shape (AC3) ----------------------------------------------


def test_build_matches_fixture_shape(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text())
    config = write_run(tmp_path / "repo", fixture)
    snap = build(config, tmp_path)
    assert list(snap) == KEYS
    assert shape(snap) == shape(fixture)


def test_build_matches_fixture_values(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text())
    snap = build(write_run(tmp_path / "repo", fixture), tmp_path)
    assert [s["acceptance"] for s in snap["stories"]] == [
        s["acceptance"] for s in fixture["stories"]
    ]
    for key in ("ledger", "messages", "answers", "pipeline"):
        assert snap[key] == fixture[key]
    for got, want in zip(snap["requirements"], fixture["requirements"], strict=True):
        want_history = [{**h, "sha": ""} for h in want["history"]]
        assert {**got, "history": [{**h, "sha": ""} for h in got["history"]]} == {
            **want,
            "history": want_history,
        }


# ----- 2. empty (AC1) --------------------------------------------------------


def test_empty_run_files(config: cfg.Config, tmp_path: Path) -> None:
    snap = build(config, tmp_path)
    assert list(snap) == KEYS
    for key in ("stories", "requirements", "events", "ledger", "messages", "answers"):
        assert snap[key] == []
    assert snap["run"]["status"] == "idle"
    assert snap["run"]["sprint"] == 0
    assert snap["run"]["task"] == ""
    assert snap["run"]["manager_due"] == []
    assert snap["pipeline"] == ["design", "tests", "implement"]
    assert snap["roles"]


def test_run_section_reads_config(config: cfg.Config, tmp_path: Path) -> None:
    run = build(config, tmp_path)["run"]
    assert run == {
        "status": "idle",
        "sprint": 0,
        "cadence": "sprint",
        "task": "",
        "budget_usd": 20.0,
        "manager_every_pct": 25,
        "round_cap": 3,
        "manager_due": [],
    }


# ----- 3. torn lines (D3) ----------------------------------------------------


def test_torn_and_blank_lines_are_skipped(config: cfg.Config, tmp_path: Path) -> None:
    good = {
        "events.jsonl": {"id": "e1", "at": 1.0, "kind": "gate", "role": None, "story": None,
                         "data": {}},
        "ledger.jsonl": {"role": "architect", "model": "opus", "cost_usd": 0.5, "story": None,
                         "at": 2.0},
        "outbox.jsonl": {"id": "m1", "kind": "update", "text": "hi", "stories": [], "at": 3.0},
    }  # fmt: skip
    config.run_dir.mkdir(parents=True, exist_ok=True)
    for name, row in good.items():
        text = json.dumps(row) + '\n\n[1]\n{"kind": "ga'
        (config.run_dir / name).write_text(text)
    snap = build(config, tmp_path)
    assert [e["id"] for e in snap["events"] if e["kind"] == "gate"] == ["e1"]
    assert len(snap["ledger"]) == 1
    assert [m["id"] for m in snap["messages"]] == ["m1"]
    assert len(snap["events"]) == 2  # the gate plus the merged outbox message


def test_read_jsonl_missing_and_junk(tmp_path: Path) -> None:
    assert snapshot.read_jsonl(tmp_path / "nope.jsonl") == []
    path = tmp_path / "x.jsonl"
    path.write_text('{"a": 1}\n\n"str"\n42\nnot json\n{"b": 2}\n{"c"')
    assert snapshot.read_jsonl(path) == [{"a": 1}, {"b": 2}]


# ----- 4. ledger (D8) --------------------------------------------------------


def test_ledger_line_without_tokens_gets_zero_counts(config: cfg.Config, tmp_path: Path) -> None:
    write_jsonl(
        config.run_dir / "ledger.jsonl",
        [{"role": "architect", "model": "opus", "cost_usd": 0.1, "story": "s1", "at": 5.0}],
    )
    (entry,) = build(config, tmp_path)["ledger"]
    assert entry["tokens"] == {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    assert entry["role"] == "architect"


# ----- 5. stories (D5) -------------------------------------------------------


def put_story(config: cfg.Config, story: StoryState) -> None:
    state_mod.save(config.run_dir, RunState(stories={story.id: story}, sprint=1))


def test_story_without_file_or_event(config: cfg.Config, tmp_path: Path) -> None:
    put_story(config, StoryState("s1", "One", "design", delivery=None, commit="abc", sprint=1))
    (story,) = build(config, tmp_path)["stories"]
    assert story == {
        "id": "s1",
        "title": "One",
        "sprint": 1,
        "delivery": "",
        "step": "design",
        "status": "active",
        "rounds": 0,
        "opened_at": None,
        "acceptance": [],
    }
    assert "commit" not in story


def test_story_acceptance_and_opened_at(config: cfg.Config, tmp_path: Path) -> None:
    put_story(config, StoryState("s1", "One", "design"))
    meta = "acceptance:\n  - {id: AC1, text: first}\n  - just a string\n  - {id: 2}\n"
    write_story_file(config, "s1", meta)
    opened = {"role": None, "story": "s1", "data": {}, "kind": "story-opened"}
    write_jsonl(
        config.run_dir / "events.jsonl",
        [{"id": "e1", "at": 7.5, **opened}, {"id": "e2", "at": 9.0, **opened}],
    )
    (story,) = build(config, tmp_path)["stories"]
    assert story["opened_at"] == 7.5
    assert story["acceptance"] == [{"id": "AC1", "text": "first"}, {"id": "2", "text": ""}]


@pytest.mark.parametrize("content", ["---\nacceptance: [unclosed\n---\nbody", "no frontmatter"])
def test_story_file_unparseable_gives_empty_acceptance(
    config: cfg.Config, tmp_path: Path, content: str
) -> None:
    put_story(config, StoryState("s1", "One", "design"))
    config.stories_dir.mkdir(parents=True)
    (config.stories_dir / "s1.md").write_text(content)
    assert build(config, tmp_path)["stories"][0]["acceptance"] == []


def test_stories_keep_state_order(config: cfg.Config, tmp_path: Path) -> None:
    stories = {i: StoryState(i, i.upper(), "design") for i in ("s3", "s1", "s2")}
    state_mod.save(config.run_dir, RunState(stories=stories))
    assert [s["id"] for s in build(config, tmp_path)["stories"]] == ["s3", "s1", "s2"]


# ----- 6. requirements (D6) --------------------------------------------------


def req_event(eid: str, at: float, rid: str, **data: Any) -> dict[str, Any]:
    return {
        "id": eid,
        "at": at,
        "kind": "requirement-changed",
        "role": "architect",
        "story": "s1",
        "data": {"id": rid, "change": "added", "reason": "why", **data},
    }


def write_req(config: cfg.Config, name: str, text: str) -> None:
    config.requirements_dir.mkdir(parents=True, exist_ok=True)
    (config.requirements_dir / name).write_text(text)


def test_requirement_defaults_and_body(config: cfg.Config, tmp_path: Path) -> None:
    write_req(config, "REQ-002.md", "Plain body.\n")
    write_req(config, "REQ-001.md", "---\ntitle: T\ncovers: [s1/AC1]\n---\n\nBody here.\n\n")
    first, second = build(config, tmp_path)["requirements"]
    assert first == {
        "id": "REQ-001",
        "title": "T",
        "status": "active",
        "covers": ["s1/AC1"],
        "text": "Body here.",
        "history": [],
    }
    assert second["id"] == "REQ-002" and second["text"] == "Plain body."
    assert second["title"] == "" and second["covers"] == []


def test_requirement_bad_yaml_still_gets_a_row(config: cfg.Config, tmp_path: Path) -> None:
    write_req(config, "REQ-009.md", "---\ntitle: [unclosed\n---\nbody")
    (row,) = build(config, tmp_path)["requirements"]
    assert row["id"] == "REQ-009" and row["status"] == "active"
    assert row["text"] == "" and row["history"] == []


def test_requirement_history_by_id_in_order(config: cfg.Config, tmp_path: Path) -> None:
    write_req(config, "REQ-001.md", "---\nid: REQ-001\n---\nx")
    gate = {"id": "e4", "at": 4.0, "kind": "gate", "role": None, "story": None}
    write_jsonl(
        config.run_dir / "events.jsonl",
        [
            req_event("e1", 1.0, "REQ-001"),
            req_event("e2", 2.0, "REQ-002"),
            req_event("e3", 3.0, "REQ-001", sha="abc1234", change="changed"),
            {**gate, "data": {"id": "REQ-001"}},
        ],
    )
    (row,) = build(config, tmp_path)["requirements"]
    common = {"reason": "why", "role": "architect", "story": "s1"}
    assert row["history"] == [
        {"at": 1.0, "change": "added", "sha": "", **common},
        {"at": 3.0, "change": "changed", "sha": "abc1234", **common},
    ]


# ----- 7. roles (D4) ---------------------------------------------------------


def names(snap: dict[str, Any]) -> list[str]:
    return [r["name"] for r in snap["roles"]]


def test_roles_sorted_with_fields(config: cfg.Config, tmp_path: Path) -> None:
    snap = build(config, tmp_path)
    assert names(snap) == sorted(names(snap))
    assert all(set(r) == {"name", "model", "provider"} for r in snap["roles"])
    assert "architect" in names(snap)


def test_role_override_shows_model(config: cfg.Config, tmp_path: Path) -> None:
    state = RunState(overrides={"architect": ModelOverride("haiku", "low", "cheap")})
    state_mod.save(config.run_dir, state)
    roles = {r["name"]: r for r in build(config, tmp_path)["roles"]}
    assert roles["architect"]["model"] == "haiku"


def test_disabled_and_dangling_roles_are_left_out(tmp_path: Path) -> None:
    config = make_config(
        tmp_path / "repo",
        roles={"integration-tester": {"enabled": False}, "ghost": {"extends": "nope"}},
    )
    snap = build(config, tmp_path)
    assert "integration-tester" not in names(snap)
    assert "ghost" not in names(snap)
    assert "architect" in names(snap)


# ----- 8. events (D7) --------------------------------------------------------


def test_outbox_and_inbox_merge_into_events(config: cfg.Config, tmp_path: Path) -> None:
    def ev(eid: str, at: float, kind: str) -> dict[str, Any]:
        return {"id": eid, "at": at, "kind": kind, "role": None, "story": None, "data": {}}

    write_jsonl(config.run_dir / "events.jsonl", [ev("e1", 1.0, "gate"), ev("e2", 4.0, "future")])
    write_jsonl(
        config.run_dir / "outbox.jsonl",
        [{"id": "m1", "kind": "question", "text": "q", "stories": [], "at": 2.0}],
    )
    write_jsonl(config.run_dir / "inbox.jsonl", [{"id": "m1", "text": "a", "at": 3.0}])
    events = build(config, tmp_path)["events"]
    assert [e["id"] for e in events] == ["e1", "out-m1", "in-m1", "e2"]
    assert events[1] == {
        "id": "out-m1",
        "at": 2.0,
        "kind": "message",
        "role": "product-owner",
        "story": None,
        "data": {"message": "m1"},
    }
    assert events[2] == {
        "id": "in-m1",
        "at": 3.0,
        "kind": "answer",
        "role": None,
        "story": None,
        "data": {"message": "m1"},
    }
    assert events[3]["kind"] == "future"


# ----- 9. watched_files ------------------------------------------------------


def test_watched_files_lists_inputs_only(config: cfg.Config) -> None:
    config.stories_dir.mkdir(parents=True)
    config.requirements_dir.mkdir(parents=True)
    for p in (config.stories_dir / "s2.md", config.stories_dir / "s1.md"):
        p.write_text("x")
    (config.stories_dir / "notes.txt").write_text("x")
    (config.requirements_dir / "REQ-001.md").write_text("x")
    (config.requirements_dir / "README.md").write_text("x")
    config.run_dir.mkdir(parents=True)
    (config.run_dir / "keyfile").write_text("secret")
    run = config.run_dir
    assert snapshot.watched_files(config) == [
        run / "state.json",
        run / "events.jsonl",
        run / "ledger.jsonl",
        run / "outbox.jsonl",
        run / "inbox.jsonl",
        config.stories_dir / "s1.md",
        config.stories_dir / "s2.md",
        config.requirements_dir / "REQ-001.md",
    ]


def test_watched_files_without_dirs(config: cfg.Config) -> None:
    assert len(snapshot.watched_files(config)) == 5


# ----- 10. D10 / config / ledger constants -----------------------------------


def test_state_task_defaults_and_round_trips() -> None:
    data = json.loads(RunState().to_json())
    data.pop("task")
    assert RunState.from_json(json.dumps(data)).task == ""
    assert RunState.from_json(RunState(task="ship it").to_json()).task == "ship it"


def test_config_dirs(config: cfg.Config) -> None:
    assert cfg.STORIES_DIR == ".team/stories" and cfg.REQUIREMENTS_DIR == "requirements"
    assert config.stories_dir == config.repo / ".team/stories"
    assert config.requirements_dir == config.repo / "docs" / "requirements"


def test_ledger_constant_lives_in_ledger_module() -> None:
    from agile_team import cli, ledger

    assert ledger.LEDGER == "ledger.jsonl" and cli.LEDGER is ledger.LEDGER
