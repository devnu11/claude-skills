"""Snapshot builder: run files -> the dashboard's one JSON document (s4, D1-D10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from agile_team import config as cfg
from agile_team import state as state_mod
from agile_team import system
from agile_team.dashboard import snapshot
from agile_team.gates import PreviousStep, StoryState, StoryStatus
from agile_team.roles import RoleBook
from agile_team.state import ModelOverride, RunState, RunStatus

FIXTURE = Path(snapshot.__file__).parent / "fixtures" / "snapshot.json"
FIXTURE_TEXT = FIXTURE.read_text()  # at import, before the fake world: the unit tests touch no file
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
    "upstream",
    "turns",
    "heartbeat",
    "health",
]


def shape(value: Any) -> Any:
    """Keys and value types; list items collapse to the set of their shapes."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted({json.dumps(shape(i), sort_keys=True) for i in value})
    return type(value).__name__


AFTER_CUTOFF_S = 10_000_000  # fixture times are ~1.79e9; the cutoff is 1791694950


def write_jsonl(path: Path, rows: list[Any]) -> None:
    system.make_dirs(path.parent)
    system.write_text(path, "".join(json.dumps(r) + "\n" for r in rows))


def make_config(root: Path, steps: list[str] | None = None, **extra: Any) -> cfg.Config:
    system.make_dirs(root)
    raw: dict[str, Any] = {
        "team": {"docs_dir": "docs", "budget_usd": 20.0, "manager_every_pct": 25},
        "gates": {"round_cap": 3, "steps": steps or ["design", "tests", "implement"]},
        **extra,
    }
    system.write_text(root / cfg.CONFIG_NAME, tomli_w.dumps(raw))
    return cfg.load(root)


def book_for(config: cfg.Config, scratch: Path) -> RoleBook:
    return RoleBook.for_repo(config.repo, config.roles, scratch / "no-global")


@pytest.fixture
def config(scratch: Path) -> cfg.Config:
    return make_config(scratch / "repo")


def build(config: cfg.Config, scratch: Path) -> dict[str, Any]:
    return json.loads(json.dumps(snapshot.build(config, book_for(config, scratch))))


def write_story_file(config: cfg.Config, sid: str, meta: str, body: str = "x\n") -> None:
    path = config.stories_dir / f"{sid}.md"
    system.make_dirs(path.parent)
    system.write_text(path, f"---\n{meta}---\n{body}")


def restore_upstream(state: RunState, section: dict[str, Any] | None) -> None:
    """Put the fixture's ``upstream`` section back into the run state (s29)."""
    if not section:
        return
    from agile_team import boundary as bd

    state.upstream = bd.UpstreamState(
        team_branch=section["team_branch"],
        push=section["push"],
        report=section["report"],
        stack=[
            bd.StackEntry(
                e["sprint"],
                e["branch"],
                "a",
                "b",
                head=e["head"],
                check=e["check"],
                pr=e["pr"],
                url=e["url"],
                base=e["base"],
                mode=e["mode"],
            )
            for e in section["stack"]
        ],
    )
    b = section["boundary"]
    if b:
        state.boundary = bd.Boundary(
            b["edge"], b["sprint"], stage=b["stage"], hold=b["hold"], rounds=b["rounds"]
        )


def previous_from(wait: dict[str, Any] | None) -> PreviousStep | None:
    """Rebuild ``previous`` from the last "role: summary" line of a wait's detail."""
    if not wait or not wait["on"] or ": " not in wait["on"][-1]:
        return None
    role, summary = wait["on"][-1].split(": ", 1)
    return PreviousStep(role, "done", summary) if role in ROLES_WITH_PREVIOUS else None


ROLES_WITH_PREVIOUS = ("architect", "unit-tester", "developer", "reviewer", "integration-tester")


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
            repeated=s.get("repeated"),
            hold=s.get("hold"),
            previous=previous_from(s.get("wait")),
        )
        for s in fixture["stories"]
    }
    state = RunState(
        cadence=run["cadence"],
        sprint=run["sprint"],
        status=RunStatus(run["status"]),
        stories=stories,
        order=run["order"],
        manager_due=run["manager_due"],
        task=run["task"],
    )
    restore_upstream(state, fixture.get("upstream"))
    state_mod.save(config.run_dir, state)
    plain = [e for e in fixture["events"] if e["kind"] not in ("message", "answer")]
    write_jsonl(config.run_dir / "events.jsonl", plain)
    write_jsonl(config.run_dir / "ledger.jsonl", fixture["ledger"])
    write_jsonl(config.run_dir / "outbox.jsonl", fixture["messages"])
    write_jsonl(config.run_dir / "inbox.jsonl", fixture["answers"])
    fresh = [{**t, "at": system.now()} for t in fixture["turns"]]  # inside the 600 s window
    write_jsonl(config.run_dir / "turns.jsonl", fresh)
    if fixture["heartbeat"] is not None:
        system.write_text(config.run_dir / "heartbeat.json", json.dumps(fixture["heartbeat"]))
    for s in fixture["stories"]:
        meta = json.dumps({"id": s["id"], "title": s["title"], "acceptance": s["acceptance"]})
        write_story_file(config, s["id"], meta + "\n")
    for r in fixture["requirements"]:
        meta = json.dumps({k: r[k] for k in ("id", "title", "status", "covers")})
        path = config.requirements_dir / f"{r['id']}.md"
        system.make_dirs(path.parent)
        system.write_text(path, f"---\n{meta}\n---\n{r['text']}\n")
    return config


# ----- 1. fixture shape (AC3) ----------------------------------------------


def test_build_matches_fixture_shape(scratch: Path) -> None:
    fixture = json.loads(FIXTURE_TEXT)
    config = write_run(scratch / "repo", fixture)
    snap = build(config, scratch)
    assert list(snap) == KEYS
    assert shape(snap) == shape(fixture)


def test_build_matches_fixture_values(scratch: Path) -> None:
    fixture = json.loads(FIXTURE_TEXT)
    config = write_run(scratch / "repo", fixture)
    # Rows from before ledger.PO_DELTAS_FROM are corrected on read (s38 K2); move them past it.
    after = [{**e, "at": e["at"] + AFTER_CUTOFF_S} for e in fixture["ledger"]]
    write_jsonl(config.run_dir / "ledger.jsonl", after)
    snap = build(config, scratch)
    assert snap["ledger"] == after
    assert [s["acceptance"] for s in snap["stories"]] == [
        s["acceptance"] for s in fixture["stories"]
    ]
    for key in ("messages", "answers", "pipeline"):
        assert snap[key] == fixture[key]
    for got, want in zip(snap["requirements"], fixture["requirements"], strict=True):
        want_history = [{**h, "sha": ""} for h in want["history"]]
        assert {**got, "history": [{**h, "sha": ""} for h in got["history"]]} == {
            **want,
            "history": want_history,
        }


# ----- 2. empty (AC1) --------------------------------------------------------


def test_empty_run_files(config: cfg.Config, scratch: Path) -> None:
    snap = build(config, scratch)
    assert list(snap) == KEYS
    for key in ("stories", "requirements", "events", "ledger", "messages", "answers"):
        assert snap[key] == []
    assert snap["run"]["status"] == "idle"
    assert snap["run"]["sprint"] == 0
    assert snap["run"]["task"] == ""
    assert snap["run"]["manager_due"] == []
    assert snap["pipeline"] == ["design", "tests", "implement"]
    assert snap["roles"]


def test_run_section_reads_config(config: cfg.Config, scratch: Path) -> None:
    """The run section carries the config values and the (empty) queue `order` (s40 D1/D5)."""
    run = build(config, scratch)["run"]
    assert run == {
        "status": "idle",
        "sprint": 0,
        "cadence": "sprint",
        "task": "",
        "budget_usd": 20.0,
        "manager_every_pct": 25,
        "round_cap": 3,
        "manager_due": [],
        "order": [],
    }


# ----- 3. torn lines (D3) ----------------------------------------------------


def test_torn_and_blank_lines_are_skipped(config: cfg.Config, scratch: Path) -> None:
    good = {
        "events.jsonl": {"id": "e1", "at": 1.0, "kind": "gate", "role": None, "story": None,
                         "data": {}},
        "ledger.jsonl": {"role": "architect", "model": "opus", "cost_usd": 0.5, "story": None,
                         "at": 2.0},
        "outbox.jsonl": {"id": "m1", "kind": "update", "text": "hi", "stories": [], "at": 3.0},
    }  # fmt: skip
    system.make_dirs(config.run_dir)
    for name, row in good.items():
        text = json.dumps(row) + '\n\n[1]\n{"kind": "ga'
        system.write_text(config.run_dir / name, text)
    snap = build(config, scratch)
    assert [e["id"] for e in snap["events"] if e["kind"] == "gate"] == ["e1"]
    assert len(snap["ledger"]) == 1
    assert [m["id"] for m in snap["messages"]] == ["m1"]
    assert len(snap["events"]) == 2  # the gate plus the merged outbox message


def test_read_jsonl_missing_and_junk(scratch: Path) -> None:
    assert snapshot.read_jsonl(scratch / "nope.jsonl") == []
    path = scratch / "x.jsonl"
    system.write_text(path, '{"a": 1}\n\n"str"\n42\nnot json\n{"b": 2}\n{"c"')
    assert snapshot.read_jsonl(path) == [{"a": 1}, {"b": 2}]


# ----- 4. ledger (D8) --------------------------------------------------------


def test_ledger_line_without_tokens_gets_zero_counts(config: cfg.Config, scratch: Path) -> None:
    write_jsonl(
        config.run_dir / "ledger.jsonl",
        [{"role": "architect", "model": "opus", "cost_usd": 0.1, "story": "s1", "at": 5.0}],
    )
    (entry,) = build(config, scratch)["ledger"]
    assert entry["tokens"] == {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    assert entry["role"] == "architect"


# ----- 5. stories (D5) -------------------------------------------------------


def put_story(config: cfg.Config, story: StoryState) -> None:
    state_mod.save(config.run_dir, RunState(stories={story.id: story}, sprint=1))


def test_story_without_file_or_event(config: cfg.Config, scratch: Path) -> None:
    put_story(config, StoryState("s1", "One", "design", delivery=None, commit="abc", sprint=1))
    (story,) = build(config, scratch)["stories"]
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
        "repeated": None,
        "position": 1,
        "in_progress": False,
        "hold": None,
        "wait": None,
    }
    assert "commit" not in story


def test_story_acceptance_and_opened_at(config: cfg.Config, scratch: Path) -> None:
    put_story(config, StoryState("s1", "One", "design"))
    meta = "acceptance:\n  - {id: AC1, text: first}\n  - just a string\n  - {id: 2}\n"
    write_story_file(config, "s1", meta)
    opened = {"role": None, "story": "s1", "data": {}, "kind": "story-opened"}
    write_jsonl(
        config.run_dir / "events.jsonl",
        [{"id": "e1", "at": 7.5, **opened}, {"id": "e2", "at": 9.0, **opened}],
    )
    (story,) = build(config, scratch)["stories"]
    assert story["opened_at"] == 7.5
    assert story["acceptance"] == [{"id": "AC1", "text": "first"}, {"id": "2", "text": ""}]


@pytest.mark.parametrize("content", ["---\nacceptance: [unclosed\n---\nbody", "no frontmatter"])
def test_story_file_unparseable_gives_empty_acceptance(
    config: cfg.Config, scratch: Path, content: str
) -> None:
    put_story(config, StoryState("s1", "One", "design"))
    system.make_dirs(config.stories_dir)
    system.write_text(config.stories_dir / "s1.md", content)
    assert build(config, scratch)["stories"][0]["acceptance"] == []


def test_stories_are_in_ranking_order(config: cfg.Config, scratch: Path) -> None:
    stories = {i: StoryState(i, i.upper(), "design") for i in ("s10", "s9", "s2")}
    state_mod.save(config.run_dir, RunState(stories=stories, order=["s2"]))
    snap = build(config, scratch)
    assert [s["id"] for s in snap["stories"]] == ["s2", "s9", "s10"]
    assert snap["run"]["order"] == ["s2", "s9", "s10"]
    assert [s["position"] for s in snap["stories"]] == [1, 2, 3]


def test_story_fields_for_progress_hold_and_done(config: cfg.Config, scratch: Path) -> None:
    prev = PreviousStep("architect", "done", "Asked which")
    stories = {
        "s1": StoryState("s1", "A", "tests", status=StoryStatus.DONE),
        "s2": StoryState("s2", "B", "tests", hold="questions", previous=prev),
        "s3": StoryState("s3", "C", "design"),
    }
    state_mod.save(config.run_dir, RunState(stories=stories))
    write_jsonl(config.run_dir / "outbox.jsonl", [
        {"id": "m1", "kind": "question", "text": "Which DB?", "stories": ["s2"], "at": 1.0}
    ])  # fmt: skip
    by_id = {s["id"]: s for s in build(config, scratch)["stories"]}
    assert by_id["s1"]["position"] is None and by_id["s1"]["wait"] is None
    assert by_id["s2"]["position"] == 1 and by_id["s2"]["in_progress"] is True
    assert by_id["s2"]["hold"] == "questions"
    assert by_id["s2"]["wait"] == {
        "reason": "questions",
        "on": ["m1: Which DB?", "architect: Asked which"],
    }
    assert by_id["s3"]["in_progress"] is False and by_id["s3"]["hold"] is None
    assert by_id["s3"]["wait"] is None


def test_answered_question_is_not_a_wait(config: cfg.Config, scratch: Path) -> None:
    stories = {"s1": StoryState("s1", "A", "tests")}
    state_mod.save(config.run_dir, RunState(stories=stories))
    write_jsonl(config.run_dir / "outbox.jsonl", [
        {"id": "m1", "kind": "question", "text": "Which DB?", "stories": ["s1"], "at": 1.0}
    ])  # fmt: skip
    write_jsonl(config.run_dir / "inbox.jsonl", [{"id": "m1", "text": "sqlite", "at": 2.0}])
    (story,) = build(config, scratch)["stories"]
    assert story["wait"] is None


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
    system.make_dirs(config.requirements_dir)
    system.write_text(config.requirements_dir / name, text)


def test_requirement_defaults_and_body(config: cfg.Config, scratch: Path) -> None:
    write_req(config, "REQ-002.md", "Plain body.\n")
    write_req(config, "REQ-001.md", "---\ntitle: T\ncovers: [s1/AC1]\n---\n\nBody here.\n\n")
    first, second = build(config, scratch)["requirements"]
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


def test_requirement_bad_yaml_still_gets_a_row(config: cfg.Config, scratch: Path) -> None:
    write_req(config, "REQ-009.md", "---\ntitle: [unclosed\n---\nbody")
    (row,) = build(config, scratch)["requirements"]
    assert row["id"] == "REQ-009" and row["status"] == "active"
    assert row["text"] == "" and row["history"] == []


def test_requirement_history_by_id_in_order(config: cfg.Config, scratch: Path) -> None:
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
    (row,) = build(config, scratch)["requirements"]
    common = {"reason": "why", "role": "architect", "story": "s1"}
    assert row["history"] == [
        {"at": 1.0, "change": "added", "sha": "", **common},
        {"at": 3.0, "change": "changed", "sha": "abc1234", **common},
    ]


# ----- 7. roles (D4) ---------------------------------------------------------


def names(snap: dict[str, Any]) -> list[str]:
    return [r["name"] for r in snap["roles"]]


def test_roles_sorted_with_fields(config: cfg.Config, scratch: Path) -> None:
    snap = build(config, scratch)
    assert names(snap) == sorted(names(snap))
    assert all(set(r) == {"name", "model", "provider"} for r in snap["roles"])
    assert "architect" in names(snap)


def test_role_override_shows_model(config: cfg.Config, scratch: Path) -> None:
    state = RunState(overrides={"architect": ModelOverride("haiku", "low", "cheap")})
    state_mod.save(config.run_dir, state)
    roles = {r["name"]: r for r in build(config, scratch)["roles"]}
    assert roles["architect"]["model"] == "haiku"


def test_disabled_and_dangling_roles_are_left_out(scratch: Path) -> None:
    config = make_config(
        scratch / "repo",
        roles={"integration-tester": {"enabled": False}, "ghost": {"extends": "nope"}},
    )
    snap = build(config, scratch)
    assert "integration-tester" not in names(snap)
    assert "ghost" not in names(snap)
    assert "architect" in names(snap)


# ----- 8. events (D7) --------------------------------------------------------


def test_outbox_and_inbox_merge_into_events(config: cfg.Config, scratch: Path) -> None:
    def ev(eid: str, at: float, kind: str) -> dict[str, Any]:
        return {"id": eid, "at": at, "kind": kind, "role": None, "story": None, "data": {}}

    write_jsonl(config.run_dir / "events.jsonl", [ev("e1", 1.0, "gate"), ev("e2", 4.0, "future")])
    write_jsonl(
        config.run_dir / "outbox.jsonl",
        [{"id": "m1", "kind": "question", "text": "q", "stories": [], "at": 2.0}],
    )
    write_jsonl(config.run_dir / "inbox.jsonl", [{"id": "m1", "text": "a", "at": 3.0}])
    events = build(config, scratch)["events"]
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
    system.make_dirs(config.stories_dir)
    system.make_dirs(config.requirements_dir)
    for p in (config.stories_dir / "s2.md", config.stories_dir / "s1.md"):
        system.write_text(p, "x")
    system.write_text(config.stories_dir / "notes.txt", "x")
    system.write_text(config.requirements_dir / "REQ-001.md", "x")
    system.write_text(config.requirements_dir / "README.md", "x")
    system.make_dirs(config.run_dir)
    system.write_text(config.run_dir / "keyfile", "secret")
    run = config.run_dir
    assert snapshot.watched_files(config) == [
        run / "state.json",
        run / "events.jsonl",
        run / "ledger.jsonl",
        run / "outbox.jsonl",
        run / "inbox.jsonl",
        run / "heartbeat.json",
        run / "turns.jsonl",
        config.repo / cfg.CONFIG_NAME,
        config.stories_dir / "s1.md",
        config.stories_dir / "s2.md",
        config.requirements_dir / "REQ-001.md",
    ]


def test_watched_files_without_dirs(config: cfg.Config) -> None:
    assert len(snapshot.watched_files(config)) == 8


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


# ----- s29: the upstream section (U25) -------------------------------------------


def test_snapshot_has_an_empty_upstream_section(config: cfg.Config, scratch: Path) -> None:
    section = build(config, scratch)["upstream"]
    assert section == {
        "remote": "origin",
        "branch": "main",
        "team_branch": "",
        "push": "unasked",
        "report": "",
        "boundary": None,
        "stack": [],
    }


def test_snapshot_upstream_shows_stack_and_boundary(config: cfg.Config, scratch: Path) -> None:
    from agile_team import boundary as bd

    st = RunState(sprint=2)
    st.upstream = bd.UpstreamState(
        team_branch="agile-team",
        push=bd.Permission.YES,
        stack=[
            bd.StackEntry(
                1,
                "team/sprint-1",
                "a",
                "b",
                head="h",
                pr=4,
                url="u",
                base="main",
                mode="ready",
                check="pass",
            )
        ],
    )
    st.boundary = bd.Boundary(
        bd.Edge.END, 2, stage=bd.Stage.CHECK, hold=bd.BoundaryHold.ERROR, rounds=1
    )
    st.boundary.failure = bd.Failure(
        bd.Stage.CHECK, bd.FixCase.TEAM_CHECK, "first line\nsecond line"
    )
    state_mod.save(config.run_dir, st)
    section = build(config, scratch)["upstream"]
    assert section["team_branch"] == "agile-team" and section["push"] == "yes"
    assert section["stack"] == [
        {
            "sprint": 1,
            "branch": "team/sprint-1",
            "base": "main",
            "pr": 4,
            "url": "u",
            "mode": "ready",
            "check": "pass",
            "head": "h",
        }
    ]
    assert section["boundary"] == {
        "edge": "end", "sprint": 2, "stage": "check", "hold": "error", "failure": "first line", "rounds": 1,  # noqa: E501
    }  # fmt: skip


def test_fixture_upstream_section_has_a_two_entry_stack_and_boundary_events() -> None:
    fixture = json.loads(FIXTURE_TEXT)
    section = fixture["upstream"]
    assert [e["mode"] for e in section["stack"]] == ["ready", "none"]
    assert section["stack"][1]["pr"] is None and section["boundary"]["hold"] == "push_permission"
    events = [e["data"] for e in fixture["events"] if e["kind"] == "boundary"]
    assert {(d["stage"], d["outcome"]) for d in events} >= {
        ("sync", "merged"), ("check", "fail"), ("check", "pass"), ("review", "built"), ("push", "held"),  # noqa: E501
    }  # fmt: skip


# ----- s21: the config is re-read on every build (F5) --------------------------


def rewrite_config(config: cfg.Config, steps: list[str], budget: float, cap: int) -> None:
    raw = {
        "team": {"docs_dir": "docs", "budget_usd": budget, "manager_every_pct": 25},
        "gates": {"round_cap": cap, "steps": steps},
    }
    system.write_text(config.repo / cfg.CONFIG_NAME, tomli_w.dumps(raw))


def test_build_rereads_budget_and_round_cap(config: cfg.Config, scratch: Path) -> None:
    book = book_for(config, scratch)
    assert snapshot.build(config, book)["run"]["budget_usd"] == 20.0
    rewrite_config(config, ["design", "tests", "implement"], 7.5, 5)
    run = snapshot.build(config, book)["run"]
    assert run["budget_usd"] == 7.5
    assert run["round_cap"] == 5


def test_build_rereads_pipeline(config: cfg.Config, scratch: Path) -> None:
    book = book_for(config, scratch)
    rewrite_config(config, ["design", "implement"], 20.0, 3)
    assert snapshot.build(config, book)["pipeline"] == ["design", "implement"]


@pytest.mark.parametrize("content", [None, "budget_usd = ", "[team\n"])
def test_build_falls_back_when_file_missing_or_unparsable(
    config: cfg.Config, scratch: Path, content: str | None
) -> None:
    book = book_for(config, scratch)
    path = config.repo / cfg.CONFIG_NAME
    if content is None:
        system.remove(path)
    else:
        system.write_text(path, content)
    assert snapshot.fresh_config(config) is config
    assert snapshot.build(config, book)["run"]["budget_usd"] == 20.0


def test_fresh_config_returns_new_values(config: cfg.Config) -> None:
    rewrite_config(config, ["design"], 3.0, 3)
    fresh = snapshot.fresh_config(config)
    assert fresh.team.budget_usd == 3.0
    assert fresh is not config
