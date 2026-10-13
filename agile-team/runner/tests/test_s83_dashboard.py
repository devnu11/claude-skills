"""s83: the Backlog tab's dashboard side: file route, write gate, snapshot, CLI, page."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tomli_w
from agile_team import cli, system
from agile_team import config as config_mod
from agile_team.backlog import Ask, order_version
from agile_team.dashboard import server, snapshot, story_files
from agile_team.dashboard.server import Dashboard
from agile_team.dashboard.story_files import FOLDERS, FileAsk
from agile_team.gates import StoryStatus
from agile_team.reorders import APPLIED, Request, Requests
from agile_team.roles import RoleBook

from .fake_system import FREE_PORT, FakeSystem
from .pipeline_helpers import add_story
from .test_cli import dashboard_args
from .test_server import Wire
from .test_snapshot import FIXTURE_TEXT

TOKEN = "secret-token-1"


# ----- B6, B7: the file route -----


@pytest.fixture
def team(make_runtime):
    """A runtime with stories s1 (sprint) and s2 (done) saved, and files on the fake disk."""
    rt = make_runtime()
    add_story(rt, "s1")
    add_story(rt, "s2", status=StoryStatus.DONE)
    rt.save()
    return rt


def folder_of(rt, kind: str) -> Path:
    return FOLDERS[kind](rt.config)


def test_folders_are_the_four_named_ones_in_order(team) -> None:
    assert list(FOLDERS) == ["story", "design", "review", "acceptance"]
    cfg = team.config
    assert FOLDERS["story"](cfg) == cfg.stories_dir
    assert FOLDERS["design"](cfg) == cfg.repo / cfg.team.docs_dir / "design"
    assert FOLDERS["review"](cfg) == cfg.repo / ".team" / "reviews"
    assert FOLDERS["acceptance"](cfg) == cfg.repo / ".team" / "acceptance"


def test_path_of_and_read_serve_a_known_story_file(team) -> None:
    path = folder_of(team, "story") / "s1.md"
    system.make_dirs(path.parent)
    system.write_text(path, "# s1\n")
    ask = FileAsk("story", "s1")
    assert story_files.path_of(team.config, ask) == path
    assert story_files.read(team.config, ask) == "# s1\n"


def test_a_done_story_is_still_served(team) -> None:
    path = folder_of(team, "design") / "s2.md"
    system.make_dirs(path.parent)
    system.write_text(path, "design")
    assert story_files.read(team.config, FileAsk("design", "s2")) == "design"


@pytest.mark.parametrize(
    "ask",
    [
        FileAsk("secrets", "s1"),
        FileAsk("", "s1"),
        FileAsk("story", "../state"),
        FileAsk("story", "/etc/passwd"),
        FileAsk("story", "s1/.."),
        FileAsk("story", "s999"),
        FileAsk("story", ""),
        FileAsk("story", "s1.md"),
        FileAsk("story", "a" * 65),
    ],
)
def test_bad_asks_get_none(team, ask) -> None:
    path = folder_of(team, "story") / "s1.md"
    system.make_dirs(path.parent)
    system.write_text(path, "x")
    assert story_files.path_of(team.config, ask) is None
    assert story_files.read(team.config, ask) is None


def test_a_missing_file_and_a_directory_get_none(team) -> None:
    assert story_files.read(team.config, FileAsk("review", "s1")) is None
    system.make_dirs(folder_of(team, "design") / "s1.md")
    assert story_files.read(team.config, FileAsk("design", "s1")) is None


def test_existing_lists_kinds_with_regular_files_in_table_order(team) -> None:
    for kind in ("acceptance", "story"):
        path = folder_of(team, kind) / "s1.md"
        system.make_dirs(path.parent)
        system.write_text(path, "x")
    system.make_dirs(folder_of(team, "design") / "s1.md")  # a directory is not a file
    assert story_files.existing(team.config, "s1") == ["story", "acceptance"]
    assert story_files.existing(team.config, "nothing") == []


# ----- B6: GET /api/file through the server -----


def test_routes_now_include_the_file_route() -> None:
    assert set(server.ROUTES) == {"/", "/api/snapshot", "/api/stream", "/api/file"}
    assert set(server.POSTS) == {"/api/reorder", "/api/thread", "/api/review", "/api/opinion"}


def file_app(rt) -> Dashboard:
    from functools import partial

    return Dashboard(lambda: {}, lambda: [], read_file=partial(story_files.read, rt.config))


def get_file(app: Dashboard, query: str) -> Wire:
    wire = Wire(f"/api/file{query}", app)
    server.Handler.do_GET(wire)  # type: ignore[arg-type]
    return wire


def test_file_route_serves_text_plain(team) -> None:
    path = folder_of(team, "story") / "s1.md"
    system.make_dirs(path.parent)
    system.write_text(path, "# hello é\n")
    wire = get_file(file_app(team), "?kind=story&id=s1")
    assert wire.status == 200
    assert wire.header("Content-Type") == "text/plain; charset=utf-8"
    assert wire.header("X-Content-Type-Options") == "nosniff"
    assert wire.body == "# hello é\n".encode()


@pytest.mark.parametrize(
    "query",
    [
        "?kind=secrets&id=s1",
        "?kind=story&id=../state",
        "?kind=story&id=/etc/passwd",
        "?kind=story&id=s1/..",
        "?kind=story&id=s999",
        "?kind=story&id=s1",  # no such file
        "?kind=story",
        "?id=s1",
        "",
        "?kind=design&id=s1",  # a directory named s1.md
    ],
)
def test_file_route_refusals_are_404(team, query) -> None:
    system.make_dirs(folder_of(team, "design") / "s1.md")
    wire = get_file(file_app(team), query)
    assert wire.status == 404


def test_the_team_files_are_not_served_by_path(team) -> None:
    path = folder_of(team, "story") / "s1.md"
    system.make_dirs(path.parent)
    system.write_text(path, "x")
    wire = Wire("/.team/stories/s1.md", file_app(team))
    server.Handler.do_GET(wire)  # type: ignore[arg-type]
    assert wire.status == 404


def test_file_route_uses_the_first_value_and_empty_when_missing() -> None:
    seen: list[FileAsk] = []
    app = Dashboard(lambda: {}, lambda: [], read_file=lambda a: seen.append(a))  # type: ignore[arg-type,func-returns-value]
    get_file(app, "?kind=story&kind=design&id=s1&id=s2")
    get_file(app, "")
    assert seen == [FileAsk("story", "s1"), FileAsk("", "")]


def test_the_default_dashboard_reads_no_files() -> None:
    app = Dashboard(lambda: {}, lambda: [])
    assert app.read_file(FileAsk("story", "s1")) is None
    assert app.queue is None and app.token == ""


# ----- B18: the write gate -----


class _Headers(list):
    """The response-header list of Wire that also answers request-header lookups."""

    def __init__(self, lookup: Any) -> None:
        super().__init__()
        self.get = lookup


class PostWire(Wire):
    """A POST without a socket: peer address, headers and a recording body reader."""

    def __init__(
        self,
        app: Dashboard,
        body: bytes = b"",
        host: str = "127.0.0.1",
        token: str | None = TOKEN,
        length: str | None = None,
        path: str = "/api/reorder",
    ) -> None:
        super().__init__(path, app)
        self.client_address = (host, 5555)
        # Request headers are read with .get; response headers are appended to the same list.
        self.headers = _Headers(self._header)
        size = str(len(body)) if length is None else length
        self.sent = {server.TOKEN_HEADER: token, "Content-Length": size}
        self.reads: list[int] = []
        self.rfile = SimpleNamespace(read=lambda n: self._read(body, n))

    def _read(self, body: bytes, n: int) -> bytes:
        self.reads.append(n)
        return body[:n]

    def _header(self, name: str, default: Any = None) -> Any:
        value = self.sent.get(name)
        return default if value is None else value


GOOD = json.dumps({"story": "s5", "position": 1, "version": "abc123"}).encode()


@pytest.fixture
def gate(team):
    """A dashboard whose queue publishes real request files on the fake disk."""
    queue = Requests(team.config.run_dir).queue
    return Dashboard(lambda: {}, lambda: [], queue=queue, token=TOKEN), team


def post(wire: PostWire) -> PostWire:
    server.Handler.do_POST(wire)  # type: ignore[arg-type]
    return wire


def request_files(rt) -> list[Request]:
    return Requests(rt.config.run_dir).all()


def test_constants() -> None:
    assert {"127.0.0.1", "::1"} == server.WRITE_HOSTS
    assert server.TOKEN_HEADER == "X-Agile-Team-Token"
    assert server.MAX_BODY == 4096


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_localhost_with_the_token_is_accepted(gate, host) -> None:
    app, rt = gate
    wire = post(PostWire(app, GOOD, host=host))
    assert wire.status == 202
    assert json.loads(wire.body) == {"id": "r1", "status": "queued"}
    assert wire.header("Content-Type") == "application/json"
    [req] = request_files(rt)
    assert req.ask == Ask("s5", 1, "abc123")


def test_a_second_request_gets_the_next_id(gate) -> None:
    app, _ = gate
    post(PostWire(app, GOOD))
    assert json.loads(post(PostWire(app, GOOD)).body)["id"] == "r2"


@pytest.mark.parametrize(
    "kw",
    [
        {"host": "10.0.0.5"},
        {"host": "192.168.1.9"},
        {"host": "::ffff:127.0.0.1"},
        {"token": "wrong"},
        {"token": None},
        {"token": ""},
    ],
)
def test_other_hosts_and_bad_tokens_are_403_and_leave_no_trace(gate, kw) -> None:
    app, rt = gate
    wire = post(PostWire(app, GOOD, **kw))
    assert wire.status == 403
    assert wire.reads == [] and request_files(rt) == []


def test_an_empty_app_token_never_matches_an_empty_header(team) -> None:
    app = Dashboard(lambda: {}, lambda: [], queue=Requests(team.config.run_dir).queue, token="")
    for header in ("", None):
        wire = post(PostWire(app, GOOD, token=header))
        assert wire.status == 403 and wire.reads == []
    assert request_files(team) == []


def test_a_non_ascii_token_is_compared_without_error(team) -> None:
    app = Dashboard(
        lambda: {}, lambda: [], queue=Requests(team.config.run_dir).queue, token="tøken"
    )
    assert post(PostWire(app, GOOD, token="tøken")).status == 202
    assert post(PostWire(app, GOOD, token="token")).status == 403


@pytest.mark.parametrize(
    ("body", "length"),
    [
        (b"not json", None),
        (b"[]", None),
        (json.dumps({"story": "../x", "position": 1, "version": "v"}).encode(), None),
        (GOOD, "0"),
        (GOOD, "-1"),
        (GOOD, "abc"),
        (GOOD, ""),
        (GOOD, "4097"),
        (GOOD, "99999999"),
        (b"", None),
    ],
)
def test_bad_bodies_and_lengths_are_400(gate, body, length) -> None:
    app, rt = gate
    wire = post(PostWire(app, body, length=length))
    assert wire.status == 400
    assert request_files(rt) == []


def test_oversize_length_is_never_read(gate) -> None:
    app, _ = gate
    wire = post(PostWire(app, GOOD, length="4097"))
    assert wire.status == 400 and wire.reads == []


def test_a_body_of_max_size_is_read_whole(gate) -> None:
    app, _ = gate
    big = json.dumps({"story": "s5", "position": 1, "version": "v", "pad": "x" * 4000}).encode()
    assert len(big) <= server.MAX_BODY
    assert post(PostWire(app, big)).status == 202


def test_a_post_to_another_path_is_404(gate) -> None:
    app, rt = gate
    for path in ("/", "/api/snapshot", "/api/reorder/x", "/api/file"):
        assert post(PostWire(app, GOOD, path=path)).status == 404
    assert request_files(rt) == []


def test_reads_need_no_token(gate) -> None:
    app, _ = gate
    wire = Wire("/api/snapshot", app)
    server.Handler.do_GET(wire)  # type: ignore[arg-type]
    assert wire.status == 200


def test_may_write_checks_host_then_token() -> None:
    app = Dashboard(lambda: {}, lambda: [], token=TOKEN)
    assert server.may_write(PostWire(app)) is True  # type: ignore[arg-type]
    assert server.may_write(PostWire(app, host="1.2.3.4")) is False  # type: ignore[arg-type]
    assert server.may_write(PostWire(app, token="x")) is False  # type: ignore[arg-type]


def test_with_token() -> None:
    assert server.with_token("http://localhost:1/", "abc") == "http://localhost:1/?token=abc"


def test_for_run_binds_the_file_reader_and_the_queue_and_no_token(team) -> None:
    app = Dashboard.for_run(team.config, RoleBook.for_repo(team.config.repo, {}))
    assert app.token == "" and app.queue is not None
    path = folder_of(team, "story") / "s1.md"
    system.make_dirs(path.parent)
    system.write_text(path, "body")
    assert app.read_file(FileAsk("story", "s1")) == "body"
    assert app.queue(Ask("s5", 1, "v")).id == "r1"


# ----- the token never leaks (AC7) -----


def test_the_token_is_in_no_snapshot_event_request_or_crash_log(gate) -> None:
    app, rt = gate
    post(PostWire(app, GOOD))
    snap = snapshot.build(rt.config, RoleBook.for_repo(rt.config.repo, rt.config.roles))
    assert TOKEN not in json.dumps(snap)
    run_dir = rt.config.run_dir
    for path in system.list_dir(run_dir):
        if system.is_file(path):
            assert TOKEN not in system.read_text(path)
    for path in system.list_dir(run_dir / "reorders"):
        assert TOKEN not in system.read_text(path)
    assert not system.exists(run_dir / "crash.log") or TOKEN not in system.read_text(
        run_dir / "crash.log"
    )


def test_the_handler_log_stays_silent(capsys) -> None:
    server.Handler.log_message(Wire(), "%s", TOKEN)  # type: ignore[arg-type]
    assert capsys.readouterr().err == ""


# ----- snapshot (B1-B3, B5, B16) -----


@pytest.fixture
def run(make_runtime):
    """Sprint 1: s1 (started), s2; backlog: s5 (held), s6 (cancelled), s7; s9 done."""
    rt = make_runtime()
    add_story(
        rt, "s1", "implement", commit="c1", code_commits=["c1", "c2"], developer="dev", disputes=2
    )
    add_story(rt, "s2")
    add_story(rt, "s5", sprint=None, hold="waiting on s2")
    add_story(rt, "s6", sprint=None, hold="cancelled by the human (t15); not built")
    add_story(rt, "s7", sprint=None)
    add_story(rt, "s9", sprint=None, status=StoryStatus.DONE)
    rt.state.order = ["s1", "s2", "s5", "s6", "s7", "s9"]
    rt.save()
    return rt


def build(rt) -> dict[str, Any]:
    book = RoleBook.for_repo(rt.config.repo, rt.config.roles)
    return json.loads(json.dumps(snapshot.build(rt.config, book)))


def by_id(snap: dict[str, Any]) -> dict[str, Any]:
    return {s["id"]: s for s in snap["stories"]}


def test_run_carries_the_queue_the_backlog_and_the_version(run) -> None:
    snap = build(run)
    queue = run.priority().queue(run.state.stories.values())
    assert snap["run"]["order"] == queue
    assert snap["run"]["backlog"] == [i for i in queue if i in ("s5", "s6", "s7")]
    assert "s9" not in snap["run"]["order"]
    assert snap["run"]["order_version"] == order_version(queue, snap["run"]["backlog"])


def test_labels(run) -> None:
    stories = by_id(build(run))
    assert stories["s6"]["label"] == "cancelled"
    assert stories["s5"]["label"] == "held"
    assert stories["s7"]["label"] == "" and stories["s2"]["label"] == ""


def test_story_fields(run) -> None:
    for kind in ("story", "acceptance"):
        path = folder_of(run, kind) / "s7.md"
        system.make_dirs(path.parent)
        system.write_text(path, "x")
    stories = by_id(build(run))
    s1 = stories["s1"]
    assert s1["disputes"] == 2 and s1["developer"] == "dev"
    assert s1["commits"] == ["c1", "c2"]
    assert stories["s2"]["commits"] == []
    assert stories["s7"]["files"] == ["story", "acceptance"]
    assert stories["s2"]["files"] == []


def test_commits_are_deduped_and_have_no_none(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", commit=None, code_commits=["a", "b", "a"])
    add_story(rt, "s2", commit="z", code_commits=["z"])
    rt.save()
    stories = by_id(build(rt))
    assert stories["s1"]["commits"] == ["a", "b"] and stories["s2"]["commits"] == ["z"]


def test_reorders_status_pending_applied_refused(run) -> None:
    reqs = Requests(run.config.run_dir)
    for pos in (1, 2, 3):
        reqs.queue(Ask("s7", pos, "v"))
    run.state.reorders = {
        "r1": APPLIED,
        "r2": "the order changed since the dashboard showed it; reload",
    }
    run.save()
    rows = build(run)["reorders"]
    assert [r["id"] for r in rows] == ["r1", "r2", "r3"]
    assert [r["status"] for r in rows] == ["applied", "refused", "pending"]
    assert [r["reason"] for r in rows] == ["", run.state.reorders["r2"], ""]
    assert rows[0]["story"] == "s7" and rows[0]["position"] == 1 and "at" in rows[0]
    assert set(rows[0]) == {"id", "story", "position", "at", "status", "reason"}


def test_reorders_are_the_last_twenty(run) -> None:
    reqs = Requests(run.config.run_dir)
    for _ in range(25):
        reqs.queue(Ask("s7", 1, "v"))
    rows = build(run)["reorders"]
    assert len(rows) == 20 and rows[0]["id"] == "r6" and rows[-1]["id"] == "r25"


def test_no_requests_means_no_reorders(run) -> None:
    assert build(run)["reorders"] == []


def test_snapshot_has_the_reorders_key(run) -> None:
    assert "reorders" in build(run)


def test_watched_files_include_the_request_files(run) -> None:
    Requests(run.config.run_dir).queue(Ask("s7", 1, "v"))
    watched = snapshot.watched_files(run.config)
    assert any(p.name == "r1.json" for p in watched)


def test_the_fixture_has_the_new_contract() -> None:
    fixture = json.loads(FIXTURE_TEXT)
    assert len(fixture["run"]["order_version"]) == 12
    assert fixture["run"]["backlog"] == ["s5", "s6"]
    for s in fixture["stories"]:
        assert {"disputes", "developer", "commits", "files", "label"} <= set(s)
    statuses = {r["status"] for r in fixture["reorders"]}
    assert statuses == {"applied", "refused"}
    refused = next(r for r in fixture["reorders"] if r["status"] == "refused")
    assert refused["reason"] == "the order changed since the dashboard showed it; reload"
    prios = [e for e in fixture["events"] if e["kind"] == "priority"]
    assert prios and all("source" in e["data"] for e in prios)
    human = [e for e in prios if e["data"]["source"] == "human (dashboard)"]
    assert human and all(e["role"] is None for e in human)
    assert all(e["role"] == "product-owner" for e in prios if e not in human)


# ----- CLI (B19) -----


def test_dashboard_has_a_token_option() -> None:
    args = cli.build_parser().parse_args(["dashboard"])
    assert args.token is None
    assert cli.build_parser().parse_args(["dashboard", "--token", "abc"]).token == "abc"


def test_dashboard_prints_and_opens_the_tokened_url(configured, capsys, fake: FakeSystem) -> None:
    args = dashboard_args(configured, "--host", "127.0.0.1", "--port", "0")
    assert cli.cmd_dashboard(args) == 0
    url = f"http://localhost:{FREE_PORT}/?token=tok1"
    assert capsys.readouterr().out == f"dashboard: {url}\n"
    assert fake.opened == [url]
    assert fake.servers[0].app.token == "tok1"


def test_a_fixed_token_is_used_as_given(configured, capsys, fake: FakeSystem) -> None:
    args = dashboard_args(configured, "--host", "127.0.0.1", "--port", "0", "--token", "abc")
    cli.cmd_dashboard(args)
    assert capsys.readouterr().out == f"dashboard: http://localhost:{FREE_PORT}/?token=abc\n"
    assert fake.servers[0].app.token == "abc"


def set_config_token(repo: Path, token: str) -> None:
    from .conftest import PY_CONFIG

    raw = {**PY_CONFIG, "dashboard": {"token": token}}
    system.write_text(repo / config_mod.CONFIG_NAME, tomli_w.dumps(raw))


@pytest.mark.parametrize(
    ("cli_args", "config_token", "shown"),
    [
        ((), "cfg", "cfg"),
        (("--token", "abc"), "cfg", "abc"),
        ((), "", "tok1"),
    ],
)
def test_the_token_comes_from_the_flag_then_the_config_then_random(
    configured, capsys, fake: FakeSystem, cli_args, config_token, shown
) -> None:
    set_config_token(configured, config_token)
    args = dashboard_args(configured, "--host", "127.0.0.1", "--port", "0", *cli_args)
    cli.cmd_dashboard(args)
    assert capsys.readouterr().out == f"dashboard: http://localhost:{FREE_PORT}/?token={shown}\n"
    assert fake.servers[0].app.token == shown


def test_a_config_token_never_reaches_the_snapshot_or_the_run_files(gate) -> None:
    app, rt = gate
    app = replace(app, token="presentation")
    post(PostWire(app, GOOD, token="presentation"))
    assert len(request_files(rt)) == 1
    snap = snapshot.build(rt.config, RoleBook.for_repo(rt.config.repo, rt.config.roles))
    assert "presentation" not in json.dumps(snap)
    for path in system.list_dir(rt.config.run_dir):
        if system.is_file(path):
            assert "presentation" not in system.read_text(path)


def test_dashboard_config_defaults_to_an_empty_token(scratch: Path) -> None:
    assert config_mod.from_raw(scratch, {}).dashboard.token == ""
    assert config_mod.from_raw(scratch, {"dashboard": {"token": "x"}}).dashboard.token == "x"


def test_a_non_string_dashboard_token_is_a_config_error(scratch: Path) -> None:
    with pytest.raises(config_mod.ConfigError) as err:
        config_mod.from_raw(scratch, {"dashboard": {"token": 1}})
    assert str(err.value) == config_mod.DASHBOARD_TOKEN


def test_the_lan_line_carries_no_token(configured, capsys, fake: FakeSystem) -> None:
    args = dashboard_args(configured, "--host", "0.0.0.0", "--port", "0", "--no-open")
    cli.cmd_dashboard(args)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].endswith("?token=tok1")
    assert lines[1].startswith("from other machines: ") and "token" not in lines[1]


# ----- the page (B2, B4, B5, B8, B20): static checks; behaviour runs under node in e2e -----


@pytest.fixture
def page() -> str:
    from importlib import resources

    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_the_page_has_a_backlog_tab(page: str) -> None:
    assert '["backlog", "Backlog"]' in page
    assert 'id="tab-backlog"' in page and 'id="backlog-note"' in page and 'id="backlog"' in page
    assert "RENDER.backlog" in page or "backlog: renderBacklog" in page


def test_the_page_defines_the_backlog_functions(page: str) -> None:
    for name in (
        "backlogGroups",
        "storyLabel",
        "backlogRow",
        "storyDetails",
        "backlogHtml",
        "renderBacklog",
        "toggleRow",
        "loadFile",
        "moveTarget",
        "postReorder",
        "reorderNote",
    ):
        assert f"function {name}(" in page, name


def test_the_page_sends_the_token_header_and_reads_it_from_the_link(page: str) -> None:
    assert 'PARAMS.get("token")' in page
    assert "X-Agile-Team-Token" in page
    assert "api/reorder" in page and "api/file?kind=" in page


def test_the_page_texts(page: str) -> None:
    assert "waiting for the runner: moves apply between steps" in page
    assert (
        "read-only: open the link the dashboard printed (it carries the token), on this machine"
        in page
    )
    assert "no story file" in page and "loading…" in page
    assert "Current sprint" in page and "data-reload" in page
    assert "noopener noreferrer" in page
    assert 'draggable="true"' in page and "data-move" in page and "data-expand" in page


def test_the_page_shows_a_priority_events_source(page: str) -> None:
    assert "data.source" in page
