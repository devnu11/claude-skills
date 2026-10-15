"""s133: share requests are validated on load, confined to the design folder, carry their story."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from agile_team import cli, sandbox, shares, system
from agile_team import state as state_mod
from agile_team.gates import Verdict
from agile_team.roles import Handoff
from agile_team.sharing import Sharer, Shares
from agile_team.state import RunState

from .test_s120_gates import at, pipe, prepared_with
from .test_s120_sharer import apply, queue, share_events, told_texts, world
from .test_s120_shares import BYTES, DESIGN, SHA, STORY, make_config, write_story

GOOD = f"{DESIGN}s1-x.html"


def story_listing(repo: Path, *paths: str) -> shares.Listed:
    items = "".join(f'  - path: "{p}"\n    sha256: "{SHA}"\n' for p in paths)
    write_story(repo, f"---\nid: s1\nshared:\n{items}---\nb\n")
    return shares.listed_of(make_config(repo), "s1")


def request(**changes) -> str:
    data = {
        "story": "s1",
        "name": "m.html",
        "sha256": SHA,
        "data": base64.b64encode(BYTES).decode(),
        "at": 1.0,
    }
    data.update(changes)
    return json.dumps({k: v for k, v in data.items() if v is not ...})


def reason(text: str) -> str:
    bad = shares.Share.from_json("f1", text)
    assert isinstance(bad, shares.BadRequest) and bad.id == "f1"
    return bad.reason


def prefix(problem: str) -> str:
    return f"bad request file f1.json: {problem}"


# ----- AC1: resolve, then check -----------------------------------------------------


def test_a_dotdot_path_is_refused_with_its_resolved_form(configured: Path) -> None:
    bad = f"{DESIGN}../../.team/run/liaison/x"
    out = story_listing(configured, bad)
    assert out.files == () and out.paths() == ()
    [problem] = out.problems
    assert "shared item 1: path " + bad + " resolves to .team/run/liaison/x;" in problem
    assert "a shared file must sit directly in docs/design/" in problem


def test_a_dotdot_path_that_leaves_the_repo_names_the_outside(configured: Path) -> None:
    out = story_listing(configured, f"{DESIGN}../../../../etc/x")
    assert out.files == () and "resolves to a place outside the repo;" in out.problems[0]


def test_an_absolute_path_outside_is_refused(configured: Path) -> None:
    out = story_listing(configured, "/etc/passwd")
    assert out.paths() == ()
    assert "resolves to a place outside the repo; a shared file must sit" in out.problems[0]


def test_an_absolute_path_into_the_design_folder_is_refused(configured: Path) -> None:
    out = story_listing(configured, f"{configured}/{GOOD}")
    assert out.paths() == () and len(out.problems) == 1


def test_a_symlink_out_of_the_folder_is_refused(configured: Path, monkeypatch) -> None:
    real = system.resolve
    link = real(configured) / GOOD
    target = real(configured) / ".team" / "run" / "secret"
    monkeypatch.setattr(system, "resolve", lambda p: target if p == link else real(p))
    out = story_listing(configured, GOOD)
    assert out.paths() == ()
    assert "resolves to .team/run/secret;" in out.problems[0]


def test_a_symlink_inside_the_folder_is_refused(configured: Path, monkeypatch) -> None:
    real = system.resolve
    link = real(configured) / GOOD
    target = real(configured) / DESIGN / "other.html"
    monkeypatch.setattr(system, "resolve", lambda p: target if p == link else real(p))
    assert story_listing(configured, GOOD).paths() == ()


def test_a_nested_path_is_refused_and_a_plain_one_passes(configured: Path) -> None:
    out = story_listing(configured, f"{DESIGN}sub/s1-x.html", GOOD)
    assert out.paths() == (GOOD,) and len(out.problems) == 1
    assert "shared item 1:" in out.problems[0]


def test_a_non_string_path_says_so() -> None:
    meta = {"shared": [{"path": 5, "sha256": SHA}]}
    out = shares.listed(shares.Where("f", DESIGN), meta)
    assert out.problems == ("f: shared item 1: path must be a string",)


def test_only_the_good_item_reaches_paths(configured: Path) -> None:
    out = story_listing(configured, f"{DESIGN}../../.team/x", GOOD)
    assert out.files == (shares.SharedFile(GOOD, SHA),) and out.paths() == (GOOD,)


def test_with_entry_stays_lexical_for_paths_outside_the_folder() -> None:
    other = shares.SharedFile("elsewhere/x", SHA)
    text = shares.with_entry(STORY, other)
    assert text is not None and "elsewhere/x" in text
    again = shares.with_entry(text, shares.SharedFile("elsewhere/x", "0" * 64))
    assert again is not None and again.count("elsewhere/x") == 1


# ----- AC2: from_json validates -----------------------------------------------------


def test_a_good_request_loads_and_an_int_at_becomes_float() -> None:
    share = shares.Share.from_json("f1", request(at=3))
    assert isinstance(share, shares.Share) and share.at == 3.0 and isinstance(share.at, float)


def test_extra_keys_are_ignored() -> None:
    assert isinstance(shares.Share.from_json("f1", request(extra=1)), shares.Share)


def test_not_json() -> None:
    got = reason("{nope")
    assert got.startswith(prefix("not JSON ("))


def test_a_json_array() -> None:
    assert reason("[]") == prefix("not a JSON object")


@pytest.mark.parametrize("field", ["story", "name", "sha256", "data", "at"])
def test_each_missing_field(field: str) -> None:
    assert reason(request(**{field: ...})) == prefix(f"missing field '{field}'")


@pytest.mark.parametrize(
    ("changes", "field", "word"),
    [
        ({"story": 7}, "story", "a string"),
        ({"name": None}, "name", "a string"),
        ({"sha256": [SHA]}, "sha256", "a string"),
        ({"data": 5}, "data", "a string"),
        ({"at": "now"}, "at", "a number"),
        ({"at": True}, "at", "a number"),
    ],
)
def test_each_wrong_type(changes: dict, field: str, word: str) -> None:
    assert reason(request(**changes)) == prefix(f"field '{field}' must be {word}")


def test_the_first_problem_wins_in_table_order() -> None:
    assert reason(request(story=1, at="x")) == prefix("field 'story' must be a string")


def test_bad_base64() -> None:
    assert reason(request(data="!!!")) == prefix("field 'data' is not base64")


def test_a_hash_mismatch() -> None:
    assert reason(request(sha256="0" * 64)) == prefix("field 'sha256' does not match the data")


def test_an_unreadable_request_file_is_a_bad_request(configured: Path, monkeypatch) -> None:
    run_dir = configured / ".team" / "run"
    Shares(run_dir).queue(shares.Share("", "s1", "m.html", BYTES))

    def broken(path: Path) -> str:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(system, "read_text", broken)
    [bad] = Shares(run_dir).all()
    assert isinstance(bad, shares.BadRequest)
    assert bad.reason == "bad request file f1.json: cannot read it (Input/output error)"


# ----- AC2: a bad request is settled once -------------------------------------------


def put_raw(rt, name: str, text: str) -> None:
    folder = rt.config.run_dir / "liaison" / "shares"
    system.make_dirs(folder)
    system.write_text(folder / name, text)


def test_a_bad_request_is_refused_once_and_a_good_one_still_applies(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    queue(rt)  # f1 → overwritten below
    put_raw(rt, "f1.json", request(story=7))
    queue(rt, name="n.html")  # f2, good
    commits = len(fake.tree.commits)
    apply(rt)
    assert rt.state.shares["f1"] == "refused: " + prefix("field 'story' must be a string")
    assert rt.state.shares["f2"].startswith("applied ")
    assert len(fake.tree.commits) == commits + 1
    [bad_ev, _] = share_events(rt)
    assert bad_ev.role == "liaison" and bad_ev.story is None
    assert bad_ev.data == {
        "request": "f1",
        "path": None,
        "sha256": None,
        "commit": None,
        "outcome": "refused",
        "reason": prefix("field 'story' must be a string"),
    }
    assert len(told_texts(rt)) == 1


def test_a_second_apply_emits_nothing_more(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    put_raw(rt, "f1.json", "garbage")
    apply(rt)
    apply(rt)
    assert len(share_events(rt)) == 1 and told_texts(rt) == []
    assert Shares(rt.config.run_dir).pending(rt.state.shares) == []
    assert state_mod.load(rt.config.run_dir).shares["f1"].startswith("refused: bad request file")


def test_a_bad_request_alone_commits_nothing(make_runtime, fake) -> None:
    rt = make_runtime()
    world(rt, fake)
    put_raw(rt, "f1.json", "[]")
    commits = len(fake.tree.commits)
    Sharer(rt).apply()
    assert len(fake.tree.commits) == commits


def test_status_lists_a_pending_bad_request(configured: Path, capsys) -> None:
    run_dir = configured / ".team" / "run"
    system.make_dirs(run_dir / "liaison" / "shares")
    system.write_text(run_dir / "liaison" / "shares" / "f1.json", "garbage")
    state_mod.save(run_dir, RunState())
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["queued_shares"] == ["f1"]


def test_all_and_pending_keep_bad_files_in_number_order(configured: Path) -> None:
    run_dir = configured / ".team" / "run"
    Shares(run_dir).queue(shares.Share("", "s1", "m.html", BYTES))
    system.write_text(run_dir / "liaison" / "shares" / "f2.json", "garbage")
    kinds = [type(r) for r in Shares(run_dir).all()]
    assert kinds == [shares.Share, shares.BadRequest]
    assert [r.id for r in Shares(run_dir).pending({"f1": "x"})] == ["f2"]


# ----- AC3: the story id is passed in -----------------------------------------------


def test_the_section_names_the_given_story_not_the_file_name() -> None:
    listed = shares.Listed((shares.SharedFile("docs/design/s1-x.html", SHA),))
    out = shares.brief_section(listed, shares.Brief("s7", "architect"))
    assert "for s7." in out and "for s1." not in out


def test_the_brief_parameter_object() -> None:
    brief = shares.Brief("s7", "architect")
    assert (brief.story, brief.role) == ("s7", "architect")
    assert not hasattr(shares, "_story_of")


def test_other_roles_and_no_files_still_give_nothing() -> None:
    listed = shares.Listed((shares.SharedFile(GOOD, SHA),))
    assert shares.brief_section(listed, shares.Brief("s7", "developer-cli")) == ""
    assert shares.brief_section(shares.Listed(), shares.Brief("s7", "architect")) == ""


def test_attach_shares_passes_the_plan_story_id(monkeypatch) -> None:
    from types import SimpleNamespace

    from agile_team import dispatch

    seen: list[shares.Brief] = []
    monkeypatch.setattr(
        shares, "listed_of", lambda cfg, story: shares.Listed((shares.SharedFile(GOOD, SHA),))
    )
    monkeypatch.setattr(shares, "brief_section", lambda found, brief: seen.append(brief) or "")
    plan = SimpleNamespace(
        story=SimpleNamespace(id="s7"), role=SimpleNamespace(name="architect"), prompt="p"
    )
    dispatch.Runtime._attach_shares(SimpleNamespace(config=None), plan)
    assert seen == [shares.Brief("s7", "architect")]


def test_digest_helper_still_matches() -> None:
    assert shares.digest(BYTES) == hashlib.sha256(BYTES).hexdigest()


# ----- AC1: a NUL path, and the bad item kept out of every scope ---------------------


def test_a_nul_path_is_refused_not_a_crash(configured: Path, monkeypatch) -> None:
    nul = f"{DESIGN}a\\u0000b.md"
    real = system.resolve

    def resolve(path: Path) -> Path:
        if "\x00" in str(path):  # what Path.resolve does with a NUL byte
            raise ValueError("embedded null byte")
        return real(path)

    monkeypatch.setattr(system, "resolve", resolve)
    out = story_listing(configured, nul, GOOD)
    assert out.paths() == (GOOD,)
    [problem] = out.problems
    assert "shared item 1: path " in problem and "outside the repo" in problem


def test_one_bad_item_leaves_the_good_one_in_the_scopes_and_holds_the_gate(
    configured: Path,
) -> None:
    from agile_team import config as config_mod
    from agile_team import story_spec

    out = story_listing(configured, f"{DESIGN}../../.team/x", GOOD)
    config = config_mod.load(configured)
    prepared = prepared_with(config, out.paths())
    globs = sandbox.proxy_read_globs(config, prepared)
    assert GOOD in globs and not any(".team/x" in g for g in globs)
    allowed = sandbox._allowed_reads(config, prepared)
    assert str(config.repo / GOOD) in allowed and not any(a.endswith("/.team/x") for a in allowed)
    held = pipe(shares.Check(out)).evaluate(at("acceptance"), Handoff("done"))
    assert held.verdict is Verdict.HOLD
    assert held.reason == story_spec.STORY_FILE_HOLD.format(refusal="\n".join(out.problems))
