"""s84: a story thread with the PO and the liaison (H1-H19, unit side)."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
from functools import partial
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, po_tools, system, threads, watch
from agile_team.dashboard import server, snapshot
from agile_team.dashboard.server import Dashboard
from agile_team.relay import KINDS, REPLY, TOLD_LINE, Note, Relay
from agile_team.roles import RoleBook
from agile_team.router import Router
from agile_team.state import RunStatus
from agile_team.threads import Entry, Party, Post, Threads

from .fake_system import FAKE_REPO, FakeSystem
from .pipeline_helpers import add_story
from .test_s62_tell import ready
from .test_s62_watch import FakePace, put, remember, until
from .test_s83_dashboard import TOKEN, PostWire, post

RUN = FAKE_REPO / "run"
HEAD = "<!-- thread story=s5 at={at} -->"
THREAD_LINE = (
    "The human wrote to you on s5's thread (t1): read .team/run/liaison/messages/t1.md. "
    "Answer there with reply_story; the reply shows under the story on the dashboard."
)


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def lines_of(path: Path) -> list[dict]:
    return [json.loads(x) for x in system.read_text(path).splitlines() if x]


# ----- H1-H3, H5: checks and shapes -----


def test_parties_and_recipients() -> None:
    assert [p.value for p in Party] == ["human", "product-owner", "liaison"]
    assert {Party.PO, Party.LIAISON} == threads.RECIPIENTS
    assert threads.MAX_TEXT == 4000


@pytest.mark.parametrize("text", ["", "  \n", "\t"])
def test_a_blank_text_is_refused(text: str) -> None:
    assert threads.text_refusal(text) == threads.EMPTY == "the message is empty"


def test_the_text_limit_counts_stripped_characters() -> None:
    assert threads.text_refusal("x" * 4000) is None
    assert threads.text_refusal(f"  {'x' * 4000}  ") is None
    assert threads.text_refusal("x" * 4001) == "the message is longer than 4000 characters"


def test_story_refusal_names_the_story_and_allows_done_ones() -> None:
    assert threads.story_refusal("s9", {}) == "no story 's9'"
    assert threads.story_refusal("s9", {"s9": object()}) is None


def body(**kw: Any) -> bytes:
    data = {"story": "s5", "to": "product-owner", "text": "hi"} | kw
    return json.dumps(data).encode()


def test_parse_post_accepts_a_good_body_and_ignores_extra_keys() -> None:
    assert threads.parse_post(body()) == Post("s5", Party.PO, "hi")
    assert threads.parse_post(body(to="liaison", extra=1)) == Post("s5", Party.LIAISON, "hi")


@pytest.mark.parametrize(
    "bad",
    [
        b"not json",
        b"[]",
        b'"x"',
        body(to="manager"),
        body(to="human"),
        body(story="../x"),
        body(story=5),
        body(text=5),
        body(text="  "),
        body(text="x" * 4001),
        json.dumps({"story": "s5", "to": "liaison"}).encode(),
        json.dumps({"to": "liaison", "text": "x"}).encode(),
        json.dumps({"story": "s5", "text": "x"}).encode(),
    ],
)
def test_parse_post_refuses_bad_bodies(bad: bytes) -> None:
    assert threads.parse_post(bad) is None


# ----- H6, H7: to the PO -----


def test_a_post_to_the_po_is_a_tagged_tell_file(fake: FakeSystem) -> None:
    entry = Threads(RUN).post(Post("s5", Party.PO, " hi "))
    at = fake.clock
    assert entry == Entry("t1", "s5", Party.HUMAN, Party.PO, "hi", at)
    [told] = Relay(RUN).told()
    text = system.read_text(told.path)
    assert text.startswith(HEAD.format(at=at) + "\n\n") and text.endswith("hi")
    assert not any(p.name.startswith(".draft") for p in system.list_dir(told.path.parent))


def test_two_posts_to_the_po_get_two_numbers(fake: FakeSystem) -> None:
    box = Threads(RUN)
    ids = [box.post(Post("s5", Party.PO, t)).id for t in ("a", "b")]
    assert ids == ["t1", "t2"]


def test_tag_of_reads_the_head_and_the_text(fake: FakeSystem) -> None:
    told = Relay(RUN).tell(threads.tagged("s5", "hello"))
    tag = threads.tag_of(told)
    assert tag == threads.Tag("s5", fake.clock, "hello")


def test_tag_of_is_none_without_a_head_or_a_file(fake: FakeSystem) -> None:
    plain = Relay(RUN).tell("plain")
    assert threads.tag_of(plain) is None
    gone = Relay(RUN).tell("x")
    system.remove(gone.path)
    assert threads.tag_of(gone) is None


def test_the_head_is_strict(fake: FakeSystem) -> None:
    for text in ("<!-- thread story=s5 at=1 -->\ntext", "x\n<!-- thread story=s5 at=1 -->\n\nt"):
        assert threads.tag_of(Relay(RUN).tell(text)) is None


def test_tell_drafts_are_named_by_token_not_pid(fake: FakeSystem) -> None:
    relay = Relay(RUN)
    relay.tell("one")
    assert relay.tell("two").id == "t2"
    assert not any(".draft" in k for k in fake.files)
    assert fake.tokens >= 2


# ----- H8: the PO is told -----


def test_a_tagged_post_ends_the_pass_with_the_thread_line(make_runtime) -> None:
    rt = ready(make_runtime)
    Threads(rt.config.run_dir).post(Post("s5", Party.PO, "please"))
    found = asyncio.run(Router(rt).advance())
    assert [k.value for k in found.kinds] == ["human_message"]
    assert found.lines == [THREAD_LINE]
    assert "s5" in found.stories


def test_a_plain_tell_keeps_the_old_line_and_adds_no_story(make_runtime) -> None:
    rt = ready(make_runtime)
    rt.relay.tell("plain")
    found = asyncio.run(Router(rt).advance())
    assert found.lines == [TOLD_LINE.format(id="t1", path=".team/run/liaison/messages/t1.md")]
    assert found.stories == []


def test_told_line_and_stories_helpers(fake: FakeSystem) -> None:
    relay = Relay(RUN)
    tagged = [relay.tell(threads.tagged(s, "x")) for s in ("s5", "s6", "s5")]
    plain = relay.tell("plain")
    assert threads.told_stories([*tagged, plain]) == ["s5", "s6"]
    assert threads.told_stories([plain]) == []
    line = threads.told_line(plain, FAKE_REPO)
    assert line == TOLD_LINE.format(id="t4", path="run/liaison/messages/t4.md")
    assert "s5's thread (t1)" in threads.told_line(tagged[0], FAKE_REPO)


# ----- H9: reply_story -----


@pytest.fixture
def tools(make_runtime) -> po_tools.Tools:
    rt = make_runtime()
    add_story(rt, "s5")
    rt.save()
    return po_tools.Tools(rt)


def test_reply_kind_exists() -> None:
    assert REPLY == "reply" and KINDS[-1] == "reply"


def test_reply_story_appends_a_reply_message(tools: po_tools.Tools) -> None:
    out = call(tools.reply_story({"story": "s5", "text": " done "}))
    assert out == {"status": "posted", "id": "m1"}
    [msg] = tools.runtime.relay.messages()
    assert (msg.kind, msg.stories, msg.text) == ("reply", ["s5"], "done")


def test_reply_story_refuses_unknown_story_then_empty_text(tools: po_tools.Tools) -> None:
    out = call(tools.reply_story({"story": "s9", "text": ""}))
    assert out == {"status": "refused", "reason": "no story 's9'"}
    out = call(tools.reply_story({"story": "s5", "text": " "}))
    assert out == {"status": "refused", "reason": threads.EMPTY}
    out = call(tools.reply_story({"story": "s5", "text": "x" * 4001}))
    assert out["reason"] == threads.TOO_LONG.format(max=4000)
    assert tools.runtime.relay.messages() == []


def test_notify_user_cannot_post_a_reply(tools: po_tools.Tools) -> None:
    out = call(tools.notify_user({"text": "x", "kind": "reply"}))
    assert out == {"status": "refused", "reason": po_tools.USE_REPLY}
    assert po_tools.USE_REPLY == "use reply_story to answer on a story's thread"
    assert tools.runtime.relay.messages() == []


def test_reply_story_has_a_schema() -> None:
    desc, shape = po_tools.SCHEMAS["reply_story"]
    assert shape == {"story": str, "text": str} and "thread" in desc


# ----- H10: to the liaison -----


def test_a_post_to_the_liaison_is_an_inbox_line(fake: FakeSystem) -> None:
    box = Threads(RUN)
    first = box.post(Post("s5", Party.LIAISON, " x "))
    assert first == Entry("lp1", "s5", Party.HUMAN, Party.LIAISON, "x", fake.clock)
    assert lines_of(RUN / "liaison" / "inbox.jsonl") == [
        {"story": "s5", "text": "x", "at": fake.clock}
    ]
    assert box.post(Post("s5", Party.LIAISON, "y")).id == "lp2"
    assert Relay(RUN).told() == []


# ----- H12: the liaison replies -----


@pytest.fixture
def story_repo(make_runtime) -> Path:
    rt = make_runtime()
    add_story(rt, "s5")
    rt.save()
    return rt.config.repo


def reply(story_repo: Path, source: str) -> int:
    return cli.main(["--repo", str(story_repo), "reply", "s5", source])


def test_reply_is_a_registered_command_after_tell() -> None:
    names = [c.name for c in cli.COMMANDS]
    assert names.index("reply") > names.index("share")
    assert names.index("share") == names.index("tell") + 1


def test_reply_from_a_file(story_repo: Path, scratch: Path, capsys, fake: FakeSystem) -> None:
    src = scratch / "r.md"
    system.write_text(src, " the answer \n")
    assert reply(story_repo, str(src)) == 0
    assert capsys.readouterr().out.strip() == "replied lr1 on s5"
    path = story_repo / ".team" / "run" / "liaison" / "replies.jsonl"
    assert lines_of(path) == [{"story": "s5", "text": "the answer", "at": fake.clock}]


def test_reply_from_stdin(story_repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
    assert reply(story_repo, "-") == 0
    assert "replied lr1 on s5" in capsys.readouterr().out
    assert reply_file_lines(story_repo)[0]["text"] == "from stdin"


def reply_file_lines(story_repo: Path) -> list[dict]:
    return lines_of(story_repo / ".team" / "run" / "liaison" / "replies.jsonl")


@pytest.mark.parametrize(
    ("story", "text", "reason"),
    [
        ("s9", "x", "no story 's9'"),
        ("s5", "  \n", "the message is empty"),
        ("s5", "x" * 4001, "the message is longer than 4000 characters"),
    ],
)
def test_reply_refusals_write_nothing(
    story_repo: Path, scratch, capsys, story, text, reason
) -> None:
    src = scratch / "r.md"
    system.write_text(src, text)
    assert cli.main(["--repo", str(story_repo), "reply", story, str(src)]) == 1
    assert capsys.readouterr().err.strip() == f"agile-team reply: {reason}"
    assert not system.exists(story_repo / ".team" / "run" / "liaison" / "replies.jsonl")


def test_reply_refuses_an_unreadable_file(story_repo: Path, scratch: Path, capsys) -> None:
    missing = scratch / "nope.md"
    assert reply(story_repo, str(missing)) == 1
    assert capsys.readouterr().err.startswith(f"agile-team reply: cannot read {missing}")


def test_replies_number_on_and_need_no_running_run(story_repo: Path, monkeypatch, capsys) -> None:
    for text in ("one", "two"):
        monkeypatch.setattr("sys.stdin", io.StringIO(text))
        reply(story_repo, "-")
    assert capsys.readouterr().out.splitlines() == ["replied lr1 on s5", "replied lr2 on s5"]


# ----- H13: reading the thread -----


def test_all_merges_the_four_files_by_time(fake: FakeSystem) -> None:
    box, relay = Threads(RUN), Relay(RUN)
    fake.clock += 40
    po_reply = relay.post(Note(REPLY, "from po", ["s5"]))
    fake.clock -= 30
    mine = box.post(Post("s5", Party.PO, "to po"))
    fake.clock += 5
    lp = box.post(Post("s5", Party.LIAISON, "to li"))
    fake.clock += 20
    lr = box.reply("s5", "from li")
    assert lr.id == "lr1" and (lr.author, lr.to) == (Party.LIAISON, Party.HUMAN)
    got = box.all()
    assert [e.id for e in got] == [mine.id, lp.id, lr.id, po_reply.id]
    assert [(e.author, e.to) for e in got] == [
        (Party.HUMAN, Party.PO),
        (Party.HUMAN, Party.LIAISON),
        (Party.LIAISON, Party.HUMAN),
        (Party.PO, Party.HUMAN),
    ]
    assert got[-1].story == "s5" and got[-1].text == "from po"


def test_a_torn_last_line_is_skipped_and_ids_hold(fake: FakeSystem) -> None:
    box = Threads(RUN)
    box.post(Post("s5", Party.LIAISON, "a"))
    box.reply("s5", "b")
    for path in (box.inbox, box.replies):
        system.append_text(path, '{"story": "s5", "te')
    assert [e.id for e in box.all()] == ["lp1", "lr1"]
    assert [e.id for e in box.liaison_replies()] == ["lr1"]


def test_bad_records_are_skipped(fake: FakeSystem) -> None:
    box = Threads(RUN)
    system.make_dirs(box.inbox.parent)
    good = {"story": "s5", "text": "ok", "at": 1.0}
    junk = ["", "[1]", '"s"', json.dumps({**good, "story": 5}), json.dumps({**good, "text": 5})]
    junk.append(json.dumps({**good, "at": "now"}))
    system.write_text(box.inbox, "\n".join([*junk, json.dumps(good)]) + "\n")
    [entry] = box.liaison_posts()
    assert (entry.story, entry.text, entry.at) == ("s5", "ok", 1.0)


def test_outbox_replies_need_stories_and_other_kinds_are_not_entries(fake: FakeSystem) -> None:
    relay = Relay(RUN)
    relay.post(Note(REPLY, "no stories"))
    relay.post(Note("update", "plain", ["s5"]))
    relay.post(Note(REPLY, "yes", ["s5", "s6"]))
    [entry] = Threads(RUN).all()
    assert (entry.id, entry.story, entry.text) == ("m3", "s5", "yes")


def test_a_told_file_without_a_head_is_not_an_entry(fake: FakeSystem) -> None:
    Relay(RUN).tell("plain")
    assert Threads(RUN).all() == []
    assert Threads(RUN / "none").all() == []


def test_entry_as_dict_has_plain_values() -> None:
    entry = Entry("t1", "s5", Party.HUMAN, Party.PO, "x", 2.0)
    assert entry.as_dict() == {
        "id": "t1",
        "story": "s5",
        "author": "human",
        "to": "product-owner",
        "text": "x",
        "at": 2.0,
    }
    json.dumps(entry.as_dict())


# ----- H11: the watch trigger -----


def seeded(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    remember(run_dir, 0, "running")


def test_triggers_table_has_liaison_message_after_message() -> None:
    assert tuple(n for n, _ in watch.TRIGGERS) == ("message", "liaison_message", "status", "health")


def test_a_post_to_the_liaison_fires_once(scratch: Path) -> None:
    run_dir = scratch / "run"
    system.make_dirs(run_dir)
    seeded(run_dir)
    Threads(run_dir).post(Post("s5", Party.LIAISON, "hello"))
    out = until(run_dir, FakePace())
    assert out["triggers"] == ["liaison_message"]
    [one] = out["posts"]
    assert (one["id"], one["story"], one["text"]) == ("lp1", "s5", "hello")
    again = until(run_dir, FakePace(), timeout=0)
    assert again["triggers"] == ["heartbeat"] and again["posts"] == []


def test_a_second_post_reports_only_the_new_one(scratch: Path) -> None:
    run_dir = scratch / "run"
    system.make_dirs(run_dir)
    seeded(run_dir)
    box = Threads(run_dir)
    box.post(Post("s5", Party.LIAISON, "a"))
    until(run_dir, FakePace())
    box.post(Post("s5", Party.LIAISON, "b"))
    assert [p["id"] for p in until(run_dir, FakePace())["posts"]] == ["lp2"]


def test_a_shorter_inbox_reports_every_entry(scratch: Path) -> None:
    run_dir = scratch / "run"
    system.make_dirs(run_dir)
    seeded(run_dir)
    watch.Seen(0, "running", None, posts=5).save(run_dir / "liaison" / "watch.json")
    box = Threads(run_dir)
    box.post(Post("s5", Party.LIAISON, "a"))
    assert [p["id"] for p in until(run_dir, FakePace())["posts"]] == ["lp1"]


def test_memory_without_posts_loads_as_zero(scratch: Path) -> None:
    path = scratch / "watch.json"
    system.write_text(path, json.dumps({"messages": 2, "status": "running"}))
    seen = watch.Seen.load(path)
    assert seen is not None and seen.posts == 0 and seen.messages == 2


def test_a_first_watch_takes_existing_posts_as_seen(scratch: Path) -> None:
    run_dir = scratch / "run"
    system.make_dirs(run_dir)
    put(run_dir, RunStatus.RUNNING)
    Threads(run_dir).post(Post("s5", Party.LIAISON, "old"))
    out = until(run_dir, FakePace(), timeout=0)
    assert out["triggers"] == ["heartbeat"] and out["posts"] == []
    assert json.loads(system.read_text(run_dir / "liaison" / "watch.json"))["posts"] == 1


def test_a_heartbeat_has_no_posts(scratch: Path) -> None:
    run_dir = scratch / "run"
    system.make_dirs(run_dir)
    seeded(run_dir)
    out = until(run_dir, FakePace(), timeout=0)
    assert out["posts"] == []


def test_an_outbox_reply_still_fires_message(scratch: Path) -> None:
    run_dir = scratch / "run"
    system.make_dirs(run_dir)
    seeded(run_dir)
    Relay(run_dir).post(Note(REPLY, "r", ["s5"]))
    out = until(run_dir, FakePace())
    assert "message" in out["triggers"] and out["posts"] == []


# ----- H14, H15: snapshot -----


@pytest.fixture
def thread_rt(make_runtime, fake: FakeSystem):
    """s5 with one entry of each kind, written out of time order."""
    rt = make_runtime()
    add_story(rt, "s5")
    rt.save()
    box, run_dir = Threads(rt.config.run_dir), rt.config.run_dir
    fake.clock += 10
    box.post(Post("s5", Party.PO, "q"))
    fake.clock += 10
    Relay(run_dir).post(Note(REPLY, "a", ["s5"]))
    fake.clock += 10
    box.post(Post("s5", Party.LIAISON, "q2"))
    fake.clock += 10
    box.reply("s5", "a2")
    return rt


def build(rt) -> dict[str, Any]:
    book = RoleBook.for_repo(rt.config.repo, rt.config.roles)
    return json.loads(json.dumps(snapshot.build(rt.config, book)))


def test_snapshot_has_the_thread(thread_rt) -> None:
    snap = build(thread_rt)
    assert [t["id"] for t in snap["thread"]] == ["t1", "m1", "lp1", "lr1"]
    assert [(t["author"], t["to"]) for t in snap["thread"]][1] == ("product-owner", "human")
    assert set(snap["thread"][0]) == {"id", "story", "author", "to", "text", "at"}


def test_snapshot_thread_events(thread_rt) -> None:
    events = [e for e in build(thread_rt)["events"] if e["kind"] == "thread"]
    assert [e["id"] for e in events] == ["thread-t1", "thread-m1", "thread-lp1", "thread-lr1"]
    assert [e["role"] for e in events] == [None, "product-owner", None, None]
    assert all(e["story"] == "s5" for e in events)
    assert events[1]["data"] == {"entry": "m1", "author": "product-owner", "to": "human"}
    assert events[1]["at"] == build(thread_rt)["thread"][1]["at"]


def test_a_reply_is_not_also_a_message_event(thread_rt) -> None:
    Relay(thread_rt.config.run_dir).post(Note("update", "plain"))
    events = build(thread_rt)["events"]
    assert [e["kind"] for e in events if e["kind"] == "message"] == ["message"]
    ats = [e["at"] for e in events]
    assert ats == sorted(ats)


def test_watched_files_cover_the_thread_files(thread_rt) -> None:
    files = snapshot.watched_files(thread_rt.config)
    run_dir = thread_rt.config.run_dir
    assert run_dir / "liaison" / "inbox.jsonl" in files
    assert run_dir / "liaison" / "replies.jsonl" in files
    assert run_dir / "liaison" / "messages" / "t1.md" in files
    assert threads.watched(run_dir) == [
        run_dir / "liaison" / "inbox.jsonl",
        run_dir / "liaison" / "replies.jsonl",
        run_dir / "liaison" / "messages" / "t1.md",
    ]


def test_no_thread_means_an_empty_list(make_runtime) -> None:
    assert build(make_runtime())["thread"] == []


# ----- H4: the write gate -----


@pytest.fixture
def gate(make_runtime):
    rt = make_runtime()
    add_story(rt, "s5")
    rt.save()
    app = Dashboard(
        lambda: {},
        lambda: [],
        token=TOKEN,
        post=partial(threads.post_known, rt.config.run_dir),
    )
    return app, rt


def thread_post(wire: PostWire) -> PostWire:
    return post(wire)


def told_files(rt) -> list:
    return Relay(rt.config.run_dir).told()


def test_limits_table() -> None:
    assert server.MAX_POST_BODY == 32768
    assert server.BODY_LIMITS == {
        "/api/reorder": 4096,
        "/api/thread": 32768,
        "/api/review": 4096,
        "/api/opinion": 4096,
    }


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_localhost_with_the_token_posts(gate, host) -> None:
    app, rt = gate
    wire = thread_post(PostWire(app, body(), host=host, path="/api/thread"))
    assert wire.status == 202
    assert json.loads(wire.body) == {"id": "t1", "status": "posted"}
    assert len(told_files(rt)) == 1


def test_a_post_to_the_liaison_goes_through_the_gate(gate) -> None:
    app, rt = gate
    wire = thread_post(PostWire(app, body(to="liaison"), path="/api/thread"))
    assert json.loads(wire.body) == {"id": "lp1", "status": "posted"}
    assert told_files(rt) == []


@pytest.mark.parametrize(
    "kw",
    [{"host": "10.0.0.5"}, {"token": "wrong"}, {"token": None}, {"token": ""}],
)
def test_refused_writers_get_403_and_no_read(gate, kw) -> None:
    app, rt = gate
    wire = thread_post(PostWire(app, body(), path="/api/thread", **kw))
    assert wire.status == 403 and wire.reads == []
    assert told_files(rt) == []


def test_an_empty_app_token_never_matches(gate) -> None:
    app, _ = gate
    app = dataclasses.replace(app, token="")
    wire = thread_post(PostWire(app, body(), token="", path="/api/thread"))
    assert wire.status == 403 and wire.reads == []


@pytest.mark.parametrize(
    ("data", "length"),
    [
        (b"not json", None),
        (body(story="s9"), None),
        (body(to="manager"), None),
        (body(), "0"),
        (body(), "32769"),
        (body(), "abc"),
    ],
)
def test_bad_posts_are_400_and_write_nothing(gate, data, length) -> None:
    app, rt = gate
    wire = thread_post(PostWire(app, data, length=length, path="/api/thread"))
    assert wire.status == 400
    assert told_files(rt) == []
    assert not system.exists(rt.config.run_dir / "liaison" / "inbox.jsonl")


def test_an_oversize_length_is_never_read(gate) -> None:
    app, _ = gate
    wire = thread_post(PostWire(app, body(), length="32769", path="/api/thread"))
    assert wire.status == 400 and wire.reads == []


def test_a_big_post_under_the_limit_is_read(gate) -> None:
    app, _ = gate
    big = body(pad="x" * 10000)
    assert thread_post(PostWire(app, big, path="/api/thread")).status == 202


def test_no_post_callable_is_400(gate) -> None:
    app, _ = gate
    app = dataclasses.replace(app, post=None)
    assert thread_post(PostWire(app, body(), path="/api/thread")).status == 400


def test_reorder_keeps_its_small_limit(gate) -> None:
    app, _ = gate
    wire = thread_post(PostWire(app, b"{}", length="4097", path="/api/reorder"))
    assert wire.status == 400 and wire.reads == []


def test_the_token_is_in_no_thread_file(gate) -> None:
    app, rt = gate
    thread_post(PostWire(app, body(), path="/api/thread"))
    thread_post(PostWire(app, body(to="liaison"), path="/api/thread"))
    assert TOKEN not in json.dumps(build(rt))
    for path in [*told_files(rt), rt.config.run_dir / "liaison" / "inbox.jsonl"]:
        target = getattr(path, "path", path)
        assert TOKEN not in system.read_text(target)


def test_post_known_binds_state_stories(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s5")
    rt.save()
    assert threads.post_known(rt.config.run_dir, Post("s9", Party.PO, "x")) is None
    entry = threads.post_known(rt.config.run_dir, Post("s5", Party.PO, "x"))
    assert entry is not None and entry.id == "t1"


# ----- the page (H16-H19): static checks; behaviour runs under node in e2e -----


@pytest.fixture
def page() -> str:
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_the_page_defines_the_thread_functions(page: str) -> None:
    for name in ("threadEntries", "threadHtml", "postThread", "keepFocus"):
        assert f"function {name}(" in page, name


def test_the_page_texts_and_hooks(page: str) -> None:
    for text in (
        "write a message first",
        "No messages yet.",
        "api/thread",
        "data-thread-text",
        "data-thread-to",
        "data-thread-send",
        'maxlength="4000"',
        "TIMELINE.thread",
        "post failed: HTTP",
    ):
        assert text in page, text
