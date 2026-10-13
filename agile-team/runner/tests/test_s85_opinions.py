"""s85: the liaison's opinions on stories (O1-O20, unit side)."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, opinions, system, threads
from agile_team import state as state_mod
from agile_team.backlog import Ask, View
from agile_team.dashboard import server, snapshot
from agile_team.dashboard.server import Dashboard
from agile_team.opinions import Act, ActAsk, Board, Kind, Opinions, Route
from agile_team.relay import Relay
from agile_team.reorders import Desk, Requests
from agile_team.roles import RoleBook
from agile_team.router import Router
from agile_team.state import StoryStatus
from agile_team.threads import Party, Post, Threads

from .fake_system import FAKE_REPO, FakeSystem
from .pipeline_helpers import add_story
from .test_s62_tell import ready
from .test_s62_watch import FakePace, put, remember, until
from .test_s83_dashboard import TOKEN, PostWire

RUN = FAKE_REPO / "run"
KINDS = ["keep", "move-up", "move-down", "fold", "close", "scope", "ask"]


def lines_of(path: Path) -> list[dict]:
    return [json.loads(x) for x in system.read_text(path).splitlines() if x]


def add_line(path: Path, **data: Any) -> None:
    system.make_dirs(path.parent)
    system.append_text(path, json.dumps(data) + "\n")


def op(story: str = "s5", kind: str = "move-up", text: str = "why", at: float = 1.0) -> dict:
    return {"story": story, "kind": kind, "text": text, "at": at}


# ----- O1: kinds -----


def test_kinds_are_the_seven_in_order() -> None:
    assert [k.value for k in Kind] == KINDS
    assert [a.value for a in Act] == ["dismiss", "apply"]
    assert [r.value for r in Route] == ["", "reorder", "product-owner"]


def test_kind_refusal() -> None:
    assert opinions.kind_refusal("fold") is None
    text = opinions.kind_refusal("later")
    assert text == opinions.UNKNOWN_KIND.format(kind="later", kinds=", ".join(KINDS))
    assert "'later'" in text and "keep, move-up" in text


def test_the_texts() -> None:
    assert opinions.ACT_STATUS == {Act.DISMISS: "dismissed", Act.APPLY: "applied"}
    assert opinions.RECORDED == "recorded {id}: {kind} on {story}"
    assert opinions.REVIEWED == "recorded backlog review {id}"
    assert opinions.UNKNOWN_OPINION == "no opinion {id!r}"
    assert threads.BACKLOG == ""
    assert "agile-team reviewed -" in opinions.REVIEW_TEXT


# ----- O2, O4: the CLI -----


@pytest.fixture
def story_repo(make_runtime) -> Path:
    rt = make_runtime()
    add_story(rt, "s5")
    add_story(rt, "s6", status=StoryStatus.DONE)
    rt.save()
    return rt.config.repo


def run_cli(repo: Path, *argv: str) -> int:
    return cli.main(["--repo", str(repo), *argv])


def opinion_path(repo: Path, name: str = "opinions.jsonl") -> Path:
    return repo / ".team" / "run" / "liaison" / name


def test_commands_follow_reply() -> None:
    names = [c.name for c in cli.COMMANDS]
    assert names[names.index("reply") + 1 : names.index("reply") + 3] == ["opinion", "reviewed"]


def test_opinion_from_a_file(story_repo: Path, scratch: Path, capsys, fake: FakeSystem) -> None:
    src = scratch / "o.md"
    system.write_text(src, " do it \n")
    assert run_cli(story_repo, "opinion", "s5", "move-up", str(src)) == 0
    assert capsys.readouterr().out.strip() == "recorded o1: move-up on s5"
    assert lines_of(opinion_path(story_repo)) == [
        {"story": "s5", "kind": "move-up", "text": "do it", "at": fake.clock}
    ]


def test_opinion_from_stdin_and_a_done_story(story_repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
    assert run_cli(story_repo, "opinion", "s6", "keep", "-") == 0
    assert "recorded o1: keep on s6" in capsys.readouterr().out
    assert lines_of(opinion_path(story_repo))[0]["text"] == "from stdin"


@pytest.mark.parametrize(
    ("story", "kind", "text", "reason"),
    [
        ("s9", "keep", "x", "no story 's9'"),
        ("s5", "later", "x", opinions.kind_refusal("later")),
        ("s5", "keep", "  \n", "the message is empty"),
        ("s5", "keep", "x" * 4001, "the message is longer than 4000 characters"),
    ],
)
def test_opinion_refusals_write_nothing(
    story_repo: Path, scratch: Path, capsys, story, kind, text, reason
) -> None:
    src = scratch / "o.md"
    system.write_text(src, text)
    assert run_cli(story_repo, "opinion", story, kind, str(src)) == 1
    assert capsys.readouterr().err.strip() == f"agile-team opinion: {reason}"
    assert not system.exists(opinion_path(story_repo))


def test_opinion_story_is_checked_before_kind(story_repo: Path, scratch: Path, capsys) -> None:
    src = scratch / "o.md"
    system.write_text(src, "")
    run_cli(story_repo, "opinion", "s9", "later", str(src))
    assert "no story 's9'" in capsys.readouterr().err


def test_opinion_numbers_on(story_repo: Path, monkeypatch, capsys) -> None:
    for text in ("a", "b"):
        monkeypatch.setattr("sys.stdin", io.StringIO(text))
        run_cli(story_repo, "opinion", "s5", "keep", "-")
    assert capsys.readouterr().out.splitlines() == [
        "recorded o1: keep on s5",
        "recorded o2: keep on s5",
    ]


def test_reviewed(story_repo: Path, monkeypatch, capsys, fake: FakeSystem) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(" all fine "))
    assert run_cli(story_repo, "reviewed", "-") == 0
    assert capsys.readouterr().out.strip() == "recorded backlog review v1"
    assert lines_of(opinion_path(story_repo, "reviews.jsonl")) == [
        {"text": "all fine", "at": fake.clock}
    ]


def test_reviewed_refuses_empty(story_repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(" "))
    assert run_cli(story_repo, "reviewed", "-") == 1
    assert "the message is empty" in capsys.readouterr().err
    assert not system.exists(opinion_path(story_repo, "reviews.jsonl"))


# ----- O3: latest wins; lenient reads -----


def test_latest_is_the_last_line_not_the_latest_time(fake: FakeSystem) -> None:
    path = RUN / "liaison" / "opinions.jsonl"
    add_line(path, **op("s5", "keep", "1", at=5))
    add_line(path, **op("s5", "fold", "2", at=6))
    add_line(path, **op("s5", "scope", "3", at=2))
    add_line(path, **op("s6", "ask", "4", at=9))
    latest = Opinions(RUN).board().latest()
    assert latest["s5"].id == "o3" and latest["s5"].kind is Kind.SCOPE
    assert latest["s6"].id == "o4"
    assert [o.id for o in Opinions(RUN).all()] == ["o1", "o2", "o3", "o4"]


def test_bad_lines_are_skipped_and_ids_hold(fake: FakeSystem) -> None:
    path = RUN / "liaison" / "opinions.jsonl"
    add_line(path, **op(text="a"))
    add_line(path, **op(kind="bogus"))
    system.append_text(path, "\n[1]\n")
    add_line(path, story=5, kind="keep", text="x", at=1)
    add_line(path, **op(text="b", at=True))
    add_line(path, **op(text="c"))
    system.append_text(path, '{"story": "s5", "ki')
    assert [(o.id, o.text) for o in Opinions(RUN).all()] == [("o1", "a"), ("o2", "c")]


def test_opinion_and_review_as_dict_are_plain() -> None:
    o = opinions.Opinion("o1", "s5", Kind.FOLD, "t", 2.0)
    assert o.as_dict() == {"id": "o1", "story": "s5", "kind": "fold", "text": "t", "at": 2.0}
    assert type(o.as_dict()["kind"]) is str
    assert opinions.Review("v1", "t", 3.0).as_dict() == {"id": "v1", "text": "t", "at": 3.0}
    s = opinions.Settled("a1", "o1", "s5", Act.APPLY, Route.REORDER, "r1", 4.0)
    assert s.as_dict() == {
        "id": "a1",
        "opinion": "o1",
        "story": "s5",
        "act": "apply",
        "route": "reorder",
        "ref": "r1",
        "at": 4.0,
    }
    assert type(s.as_dict()["act"]) is type(s.as_dict()["route"]) is str


def test_reviews_are_read_leniently(fake: FakeSystem) -> None:
    path = RUN / "liaison" / "reviews.jsonl"
    add_line(path, text="one", at=1)
    add_line(path, text=5, at=1)
    add_line(path, text="two", at=2)
    assert [(r.id, r.text) for r in Opinions(RUN).reviews()] == [("v1", "one"), ("v2", "two")]


def test_acts_are_read_leniently(fake: FakeSystem) -> None:
    path = RUN / "liaison" / "opinion-acts.jsonl"
    good = {"opinion": "o1", "story": "s5", "act": "apply", "route": "", "ref": "", "at": 1}
    add_line(path, **good)
    add_line(path, **(good | {"act": "undo"}))
    add_line(path, **(good | {"ref": 5}))
    add_line(path, **(good | {"act": "dismiss"}))
    got = Opinions(RUN).acts()
    assert [(a.id, a.act) for a in got] == [("a1", Act.APPLY), ("a2", Act.DISMISS)]


def test_watched_is_the_three_files() -> None:
    d = RUN / "liaison"
    assert opinions.watched(RUN) == [
        d / "opinions.jsonl",
        d / "reviews.jsonl",
        d / "opinion-acts.jsonl",
    ]


# ----- O5: asking for a review -----


def test_ask_review_is_an_inbox_line_with_no_story(fake: FakeSystem) -> None:
    entry = Opinions(RUN).ask_review()
    assert entry.id == "lp1"
    assert lines_of(RUN / "liaison" / "inbox.jsonl") == [
        {"story": "", "text": opinions.REVIEW_TEXT, "at": fake.clock}
    ]
    assert Opinions(RUN).asked_at() == fake.clock


def test_asked_at_ignores_story_posts_and_is_none_without_asks(fake: FakeSystem) -> None:
    assert Opinions(RUN).asked_at() is None
    Threads(RUN).post(Post("s5", Party.LIAISON, "hi"))
    assert Opinions(RUN).asked_at() is None
    first = fake.clock
    fake.clock += 5
    Opinions(RUN).ask_review()
    fake.clock += 5
    Threads(RUN).post(Post("s5", Party.LIAISON, "later"))
    assert Opinions(RUN).asked_at() == first + 5


def test_watch_wakes_the_liaison_for_a_review_request(scratch: Path) -> None:
    run_dir = scratch / "run"
    system.make_dirs(run_dir)
    put(run_dir, state_mod.RunStatus.RUNNING)
    remember(run_dir, 0, "running")
    Opinions(run_dir).ask_review()
    out = until(run_dir, FakePace())
    assert out["triggers"] == ["liaison_message"]
    [one] = out["posts"]
    assert one["story"] == "" and one["text"] == opinions.REVIEW_TEXT


# ----- O7: parse_act -----


def act_body(**kw: Any) -> bytes:
    return json.dumps({"opinion": "o1", "act": "apply", "version": "v"} | kw).encode()


def test_parse_act_accepts_a_good_body_and_ignores_extras() -> None:
    assert opinions.parse_act(act_body(x=1)) == ActAsk("o1", Act.APPLY, "v")
    assert opinions.parse_act(act_body(act="dismiss", version="")) == ActAsk("o1", Act.DISMISS, "")
    assert opinions.parse_act(act_body(version="x" * 64)) is not None


@pytest.mark.parametrize(
    "bad",
    [
        b"nope",
        b"[]",
        b"5",
        act_body(act="undo"),
        act_body(act=1),
        act_body(opinion="x1"),
        act_body(opinion="o0"),
        act_body(opinion="o01"),
        act_body(opinion="o1\n"),
        act_body(opinion=1),
        act_body(version=5),
        act_body(version="x" * 65),
        json.dumps({"act": "apply", "version": "v"}).encode(),
        json.dumps({"opinion": "o1", "version": "v"}).encode(),
        json.dumps({"opinion": "o1", "act": "apply"}).encode(),
    ],
)
def test_parse_act_refuses_bad_bodies(bad: bytes) -> None:
    assert opinions.parse_act(bad) is None


def test_is_object() -> None:
    assert opinions.is_object(b"{}") and opinions.is_object(b'{"a": 1}')
    for bad in (b"[]", b"1", b"x", b'"s"', b""):
        assert not opinions.is_object(bad)


# ----- the world for acting -----


@pytest.fixture
def backlog_world(make_runtime, fake: FakeSystem):
    """Sprint 1: s1; backlog: s5, s6, s7; s9 done."""
    rt = make_runtime()
    add_story(rt, "s1")
    for sid in ("s5", "s6", "s7"):
        add_story(rt, sid, sprint=None)
    add_story(rt, "s9", sprint=None, status=StoryStatus.DONE)
    rt.state.order = ["s1", "s5", "s6", "s7", "s9"]
    rt.save()
    return rt


def box_of(rt) -> Opinions:
    return Opinions(rt.config.run_dir)


def version_of(rt) -> str:
    return View.of(state_mod.load(rt.config.run_dir)).version


def record(rt, story: str, kind: Kind, text: str = "why") -> opinions.Opinion:
    return box_of(rt).record(story, kind, text)


def ask_for(rt, oid: str, act: Act = Act.APPLY, version: str | None = None) -> ActAsk:
    return ActAsk(oid, act, version or version_of(rt))


# ----- record -----


def test_record_appends_and_returns_the_opinion(backlog_world, fake: FakeSystem) -> None:
    o = Opinions(backlog_world.config.run_dir).record("s5", Kind.MOVE_UP, "  text ")
    assert o == opinions.Opinion("o1", "s5", Kind.MOVE_UP, "text", fake.clock)
    assert box_of(backlog_world).record("s5", Kind.KEEP, "z").id == "o2"


def test_review_returns_the_review(backlog_world, fake: FakeSystem) -> None:
    r = box_of(backlog_world).review(" sum ")
    assert r == opinions.Review("v1", "sum", fake.clock)


# ----- O8: refusals -----


def test_unknown_opinion(backlog_world) -> None:
    board = box_of(backlog_world).board()
    assert board.refusal(ActAsk("o1", Act.APPLY, "v")) == "no opinion 'o1'"
    assert board.find("o1") is None


def test_superseded(backlog_world) -> None:
    record(backlog_world, "s5", Kind.FOLD)
    record(backlog_world, "s5", Kind.SCOPE)
    assert box_of(backlog_world).refusal(ask_for(backlog_world, "o1")) == (
        "o1 is no longer the latest opinion on s5; reload"
    )
    assert box_of(backlog_world).refusal(ask_for(backlog_world, "o2")) is None


def test_keep_has_nothing_to_act_on(backlog_world) -> None:
    record(backlog_world, "s5", Kind.KEEP)
    assert box_of(backlog_world).refusal(ask_for(backlog_world, "o1")) == (
        "o1 is keep: there is nothing to dismiss or apply"
    )


@pytest.mark.parametrize(("first", "status"), [(Act.DISMISS, "dismissed"), (Act.APPLY, "applied")])
def test_a_second_act_is_refused(backlog_world, first: Act, status: str) -> None:
    record(backlog_world, "s5", Kind.FOLD)
    box_of(backlog_world).act(ask_for(backlog_world, "o1", first))
    for second in Act:
        assert (
            box_of(backlog_world).refusal(ask_for(backlog_world, "o1", second))
            == f"o1 was already {status}"
        )


def test_refusal_order_unknown_then_superseded_then_keep_then_settled() -> None:
    o1 = opinions.Opinion("o1", "s5", Kind.KEEP, "t", 1)
    o2 = opinions.Opinion("o2", "s5", Kind.FOLD, "t", 2)
    done = opinions.Settled("a1", "o1", "s5", Act.DISMISS, Route.NONE, "", 3)
    board = Board([o1, o2], [done])
    assert "no longer the latest" in board.refusal(ActAsk("o1", Act.APPLY, "v"))
    assert board.act_of("o1") == done and board.act_of("o2") is None
    assert board.refusal(ActAsk("o2", Act.APPLY, "v")) is None


def test_refusals_write_nothing(backlog_world) -> None:
    record(backlog_world, "s5", Kind.KEEP)
    box_of(backlog_world).refusal(ask_for(backlog_world, "o1"))
    box_of(backlog_world).refusal(ask_for(backlog_world, "o7"))
    assert not system.exists(box_of(backlog_world).acts_file)


# ----- O9-O11: acting -----


def test_dismiss_writes_the_act_and_nothing_else(backlog_world, fake: FakeSystem) -> None:
    record(backlog_world, "s5", Kind.MOVE_UP)
    settled = box_of(backlog_world).act(ask_for(backlog_world, "o1", Act.DISMISS))
    assert settled.id == "a1" and settled.route is Route.NONE and settled.ref == ""
    assert lines_of(box_of(backlog_world).acts_file) == [
        {
            "opinion": "o1",
            "story": "s5",
            "act": "dismiss",
            "route": "",
            "ref": "",
            "at": fake.clock,
        }
    ]
    assert Requests(backlog_world.config.run_dir).all() == []
    assert Relay(backlog_world.config.run_dir).told() == []


def test_apply_move_up_queues_the_top_place(backlog_world) -> None:
    record(backlog_world, "s7", Kind.MOVE_UP)
    version = version_of(backlog_world)
    settled = box_of(backlog_world).act(ActAsk("o1", Act.APPLY, version))
    assert (settled.route, settled.ref) == (Route.REORDER, "r1")
    [req] = Requests(backlog_world.config.run_dir).all()
    assert req.ask == Ask("s7", 1, version)
    assert Relay(backlog_world.config.run_dir).told() == []


def test_apply_move_down_queues_the_last_place(backlog_world) -> None:
    record(backlog_world, "s5", Kind.MOVE_DOWN)
    box_of(backlog_world).act(ask_for(backlog_world, "o1"))
    [req] = Requests(backlog_world.config.run_dir).all()
    assert req.ask.position == 3 and req.ask.story == "s5"


def test_a_queued_move_is_applied_by_the_desk(backlog_world) -> None:
    record(backlog_world, "s7", Kind.MOVE_UP)
    box_of(backlog_world).act(ask_for(backlog_world, "o1"))
    Desk(backlog_world).apply()
    assert backlog_world.state.reorders == {"r1": "applied"}
    queue = View.of(backlog_world.state).backlog
    assert queue[0] == "s7"
    [event] = [e for e in backlog_world.events.events() if e.kind == "priority"]
    assert event.data["source"] == "human (dashboard)"


def test_a_stale_move_is_refused_by_the_desk_and_the_act_stays(backlog_world) -> None:
    record(backlog_world, "s7", Kind.MOVE_UP)
    box_of(backlog_world).act(ActAsk("o1", Act.APPLY, "old"))
    Desk(backlog_world).apply()
    assert (
        backlog_world.state.reorders["r1"]
        == "the order changed since the dashboard showed it; reload"
    )
    assert box_of(backlog_world).board().act_of("o1") is not None


@pytest.mark.parametrize(
    ("story", "kind"),
    [
        ("s5", Kind.FOLD),
        ("s5", Kind.CLOSE),
        ("s5", Kind.SCOPE),
        ("s5", Kind.ASK),
        ("s1", Kind.MOVE_UP),
        ("s1", Kind.MOVE_DOWN),
    ],
)
def test_other_applies_go_to_the_po_as_a_tagged_tell(backlog_world, story: str, kind: Kind) -> None:
    record(backlog_world, story, kind, "because")
    settled = box_of(backlog_world).act(ask_for(backlog_world, "o1"))
    assert (settled.route, settled.ref) == (Route.PO, "t1")
    [told] = Relay(backlog_world.config.run_dir).told()
    tag = threads.tag_of(told)
    assert tag is not None and tag.story == story
    assert tag.text == opinions.APPLY_TEXT.format(
        id="o1", story=story, kind=kind.value, text="because"
    )
    assert Requests(backlog_world.config.run_dir).all() == []


def test_the_route_is_worked_out_again_from_the_state(backlog_world) -> None:
    record(backlog_world, "s5", Kind.MOVE_UP)
    view = View.of(backlog_world.state)
    o = box_of(backlog_world).all()[0]
    assert opinions.route_of(o, view) is Route.REORDER
    in_sprint = dataclasses.replace(o, story="s1")
    assert opinions.route_of(in_sprint, view) is Route.PO
    keep = dataclasses.replace(o, kind=Kind.KEEP)
    assert opinions.route_of(keep, view) is Route.NONE
    fold = dataclasses.replace(o, kind=Kind.FOLD)
    assert opinions.route_of(fold, view) is Route.PO


def test_a_po_apply_reaches_the_router(make_runtime) -> None:
    rt = ready(make_runtime)
    Opinions(rt.config.run_dir).record("s5", Kind.FOLD, "fold it")
    box_of(rt).act(ask_for(rt, "o1"))
    found = asyncio.run(Router(rt).advance())
    assert [k.value for k in found.kinds] == ["human_message"]
    assert "s5" in found.stories


def test_acting_on_a_later_opinion_is_fresh(backlog_world) -> None:
    record(backlog_world, "s5", Kind.FOLD)
    box_of(backlog_world).act(ask_for(backlog_world, "o1", Act.DISMISS))
    record(backlog_world, "s5", Kind.SCOPE)
    assert box_of(backlog_world).refusal(ask_for(backlog_world, "o2")) is None


# ----- the write gate -----


@pytest.fixture
def gate(backlog_world):
    app = Dashboard(lambda: {}, lambda: [], token=TOKEN, opinions=box_of(backlog_world))
    return app, backlog_world


def review_wire(app: Dashboard, body: bytes = b"{}", **kw: Any) -> PostWire:
    server.Handler.do_POST(wire := PostWire(app, body, path="/api/review", **kw))  # type: ignore[arg-type]
    return wire


def act_wire(app: Dashboard, body: bytes | None = None, **kw: Any) -> PostWire:
    data = act_body() if body is None else body
    server.Handler.do_POST(wire := PostWire(app, data, path="/api/opinion", **kw))  # type: ignore[arg-type]
    return wire


def test_limits_table() -> None:
    assert server.BODY_LIMITS["/api/review"] == server.MAX_BODY == 4096
    assert server.BODY_LIMITS["/api/opinion"] == 4096
    assert "/api/review" in server.POSTS and "/api/opinion" in server.POSTS


def test_for_run_binds_the_opinions(backlog_world) -> None:
    app = Dashboard.for_run(backlog_world.config, RoleBook.for_repo(backlog_world.config.repo, {}))
    assert app.opinions == Opinions(backlog_world.config.run_dir)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_review_is_accepted(gate, host) -> None:
    app, rt = gate
    wire = review_wire(app, host=host)
    assert wire.status == 202
    assert json.loads(wire.body) == {"id": "lp1", "status": "asked"}
    assert box_of(rt).asked_at() is not None


def test_review_ignores_any_keys(gate) -> None:
    app, _ = gate
    assert review_wire(app, b'{"a": [1]}').status == 202


@pytest.mark.parametrize(
    "kw", [{"host": "10.0.0.5"}, {"token": "wrong"}, {"token": None}, {"token": ""}]
)
def test_review_refused_writers_get_403_and_no_read(gate, kw) -> None:
    app, rt = gate
    wire = review_wire(app, **kw)
    assert wire.status == 403 and wire.reads == []
    assert box_of(rt).asked_at() is None


def test_review_empty_app_token_never_matches(gate) -> None:
    app, _ = gate
    app = dataclasses.replace(app, token="")
    wire = review_wire(app, token="")
    assert wire.status == 403 and wire.reads == []


@pytest.mark.parametrize(
    ("data", "length"),
    [(b"nope", None), (b"[]", None), (b"{}", "0"), (b"{}", "4097"), (b"{}", "abc")],
)
def test_review_bad_requests_are_400(gate, data, length) -> None:
    app, rt = gate
    wire = review_wire(app, data, length=length)
    assert wire.status == 400
    assert not system.exists(rt.config.run_dir / "liaison" / "inbox.jsonl")


def test_review_without_opinions_is_400(gate) -> None:
    app, _ = gate
    assert review_wire(dataclasses.replace(app, opinions=None)).status == 400


def test_an_oversize_review_is_never_read(gate) -> None:
    app, _ = gate
    assert review_wire(app, length="4097").reads == []


def test_act_dismiss_and_apply_answers(gate) -> None:
    app, rt = gate
    record(rt, "s5", Kind.FOLD)
    record(rt, "s6", Kind.MOVE_UP)
    wire = act_wire(app, act_body(act="dismiss"))
    assert wire.status == 202
    assert json.loads(wire.body) == {"id": "a1", "status": "dismissed", "route": "", "ref": ""}
    version = version_of(rt)
    wire = act_wire(app, act_body(opinion="o2", version=version))
    assert json.loads(wire.body) == {
        "id": "a2",
        "status": "applied",
        "route": "reorder",
        "ref": "r1",
    }


def test_act_to_the_po_answer(gate) -> None:
    app, rt = gate
    record(rt, "s5", Kind.SCOPE)
    wire = act_wire(app)
    assert json.loads(wire.body)["route"] == "product-owner"
    assert json.loads(wire.body)["ref"] == "t1"


def test_a_refused_act_is_409_with_the_reason(gate) -> None:
    app, rt = gate
    record(rt, "s5", Kind.KEEP)
    wire = act_wire(app)
    assert wire.status == 409
    assert json.loads(wire.body) == {
        "status": "refused",
        "reason": "o1 is keep: there is nothing to dismiss or apply",
    }
    assert not system.exists(box_of(rt).acts_file)


def test_act_unknown_opinion_is_409(gate) -> None:
    app, _ = gate
    assert act_wire(app).status == 409


@pytest.mark.parametrize(
    "kw", [{"host": "10.0.0.5"}, {"token": "wrong"}, {"token": None}, {"token": ""}]
)
def test_act_refused_writers_get_403_and_no_read(gate, kw) -> None:
    app, rt = gate
    record(rt, "s5", Kind.FOLD)
    wire = act_wire(app, **kw)
    assert wire.status == 403 and wire.reads == []
    assert not system.exists(box_of(rt).acts_file)


def test_act_empty_app_token_never_matches(gate) -> None:
    app, _ = gate
    wire = act_wire(dataclasses.replace(app, token=""), token="")
    assert wire.status == 403 and wire.reads == []


@pytest.mark.parametrize(
    ("data", "length"),
    [
        (b"nope", None),
        (b"[]", None),
        (act_body(act="undo"), None),
        (act_body(opinion="x"), None),
        (act_body(), "0"),
        (act_body(), "4097"),
        (act_body(), "abc"),
    ],
)
def test_act_bad_requests_are_400(gate, data, length) -> None:
    app, rt = gate
    record(rt, "s5", Kind.FOLD)
    wire = act_wire(app, data, length=length)
    assert wire.status == 400
    assert not system.exists(box_of(rt).acts_file)


def test_act_without_opinions_is_400(gate) -> None:
    app, _ = gate
    assert act_wire(dataclasses.replace(app, opinions=None)).status == 400


def test_the_token_is_in_no_opinion_file_or_snapshot(gate) -> None:
    app, rt = gate
    record(rt, "s5", Kind.FOLD)
    review_wire(app)
    act_wire(app)
    assert TOKEN not in json.dumps(build(rt))
    run_dir = rt.config.run_dir
    paths = [run_dir / "liaison" / "inbox.jsonl", box_of(rt).acts_file, box_of(rt).opinions_file]
    paths += list(Relay(run_dir).told() and [t.path for t in Relay(run_dir).told()])
    for path in paths:
        assert TOKEN not in system.read_text(path)


# ----- O13, O14: the snapshot -----


def build(rt) -> dict[str, Any]:
    book = RoleBook.for_repo(rt.config.repo, rt.config.roles)
    return json.loads(json.dumps(snapshot.build(rt.config, book)))


@pytest.fixture
def seen(backlog_world, fake: FakeSystem):
    """o1 (superseded move-up), o2 (open move-down on s6), o3 (applied scope on s5)."""
    fake.clock += 10
    record(backlog_world, "s6", Kind.MOVE_UP, "first")
    fake.clock += 10
    record(backlog_world, "s6", Kind.MOVE_DOWN, "second")
    fake.clock += 10
    record(backlog_world, "s5", Kind.SCOPE, "narrow")
    fake.clock += 10
    box_of(backlog_world).act(ask_for(backlog_world, "o3"))
    fake.clock += 10
    box_of(backlog_world).ask_review()
    fake.clock += 10
    box_of(backlog_world).review("all done")
    return backlog_world


def test_snapshot_has_the_opinions(seen) -> None:
    snap = build(seen)["opinions"]
    assert set(snap) == {"items", "asked_at", "review"}
    assert [i["id"] for i in snap["items"]] == ["o1", "o2", "o3"]
    assert [i["latest"] for i in snap["items"]] == [False, True, True]
    assert [i["route"] for i in snap["items"]] == ["", "reorder", ""]
    assert snap["items"][0]["act"] is None and snap["items"][1]["act"] is None
    act = snap["items"][2]["act"]
    assert set(act) == {"id", "act", "route", "ref", "at"}
    assert (act["act"], act["route"], act["ref"]) == ("apply", "product-owner", "t1")
    assert set(snap["items"][0]) == {
        "id",
        "story",
        "kind",
        "text",
        "at",
        "latest",
        "route",
        "act",
    }
    assert snap["review"]["id"] == "v1" and snap["review"]["text"] == "all done"
    assert snap["asked_at"] == snap["review"]["at"] - 10


def test_a_keep_has_no_route(backlog_world) -> None:
    record(backlog_world, "s5", Kind.KEEP)
    assert build(backlog_world)["opinions"]["items"][0]["route"] == ""


def test_no_opinions_means_empty(backlog_world) -> None:
    assert build(backlog_world)["opinions"] == {"items": [], "asked_at": None, "review": None}


def test_snapshot_opinion_events(seen) -> None:
    snap = build(seen)
    events = [e for e in snap["events"] if e["kind"] in ("opinion", "opinion-act")]
    assert [e["id"] for e in events] == [
        "opinion-o1",
        "opinion-o2",
        "opinion-o3",
        "opinion-act-a1",
    ]
    assert all(e["role"] is None for e in events)
    assert events[1]["story"] == "s6"
    assert events[1]["data"] == {"opinion": "o2", "kind": "move-down"}
    assert events[3]["data"] == {
        "opinion": "o3",
        "act": "apply",
        "route": "product-owner",
        "ref": "t1",
    }
    ats = [e["at"] for e in snap["events"]]
    assert ats == sorted(ats)


def test_a_review_request_is_a_thread_event_on_no_story(seen) -> None:
    events = [e for e in build(seen)["events"] if e["kind"] == "thread"]
    [ask] = [e for e in events if e["id"] == "thread-lp1"]
    assert ask["story"] is None


def test_watched_files_cover_the_opinion_files(seen) -> None:
    files = snapshot.watched_files(seen.config)
    for path in opinions.watched(seen.config.run_dir):
        assert path in files


def test_the_fixture_matches_build(seen) -> None:
    fixture = json.loads(
        system.read_text(resources.files("agile_team.dashboard").joinpath("fixtures/snapshot.json"))
    )
    snap = build(seen)
    assert set(fixture["opinions"]) == set(snap["opinions"])
    assert set(fixture["opinions"]["items"][0]) == set(snap["opinions"]["items"][0])
    assert set(fixture["opinions"]["review"]) == set(snap["opinions"]["review"])
    kinds = {e["kind"] for e in fixture["events"]}
    assert {"opinion", "opinion-act"} <= kinds
    acted = [i for i in fixture["opinions"]["items"] if i["act"]]
    assert acted and set(acted[0]["act"]) == {"id", "act", "route", "ref", "at"}
    assert fixture["opinions"]["asked_at"] < fixture["opinions"]["review"]["at"]
    assert any(i["latest"] and i["route"] == "reorder" for i in fixture["opinions"]["items"])


# ----- the page: static checks (behaviour runs under node in e2e) -----


@pytest.fixture
def page() -> str:
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_the_page_defines_the_opinion_functions(page: str) -> None:
    for name in (
        "storyOpinion",
        "isSuggestion",
        "reviewWaiting",
        "opinionBadge",
        "opinionHtml",
        "reviewBarHtml",
        "postReview",
        "postOpinionAct",
    ):
        assert f"function {name}(" in page, name


def test_the_page_texts_and_hooks(page: str) -> None:
    for text in (
        "The liaison has not reviewed the backlog yet.",
        "apply: move to the top of the backlog",
        "apply: move to the bottom of the backlog",
        "apply: send to the PO",
        "data-opinion-act",
        "data-ask-review",
        "data-suggested",
        "only suggestions",
        "Nothing here.",
        "api/review",
        "api/opinion",
        "waiting for the liaison",
        "TIMELINE.opinion",
        'TIMELINE["opinion-act"]',
        "ACT_TO",
        "ui.suggested",
        "ui.acting",
    ):
        assert text in page, text
