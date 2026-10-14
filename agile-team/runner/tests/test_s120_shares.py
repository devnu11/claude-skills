"""s120: the share module and ``agile-team share`` (design S1-S3, S5, S6, S9; AC1, AC4)."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from agile_team import cli, config, shares, system
from agile_team.sharing import Shares

DOCS = "docs"
DESIGN = "docs/design/"
BYTES = b"<html>mock</html>\n"
SHA = hashlib.sha256(BYTES).hexdigest()
OTHER = hashlib.sha256(b"other").hexdigest()
STORY = "---\nid: s1\ntitle: T\nacceptance:\n  - id: AC1\n    text: x\n---\n\nBody text.\n"


def where(design_dir: str = DESIGN) -> shares.Where:
    return shares.Where(".team/stories/s1.md", design_dir)


def entry(name: str = "mock.html", sha: str = SHA) -> shares.SharedFile:
    return shares.SharedFile(f"{DESIGN}s1-{name}", sha)


def write_story(repo: Path, text: str = STORY, story: str = "s1") -> None:
    system.make_dirs(repo / ".team" / "stories")
    system.write_text(repo / ".team" / "stories" / f"{story}.md", text)


def run_share(repo: Path, source: str, story: str = "s1") -> int:
    return cli.main(["--repo", str(repo), "share", source, "--story", story])


def queued(repo: Path) -> list[str]:
    folder = repo / ".team" / "run" / "liaison" / "shares"
    return sorted(p.name for p in system.list_dir(folder)) if system.is_dir(folder) else []


# ----- constants and digest ---------------------------------------------------------


def test_constants() -> None:
    assert shares.MAX_BYTES == 5 * 1024 * 1024
    assert shares.KEY == "shared" and shares.SHORT == 12
    assert shares.SUBJECT == "chore({story}): share {name} ({id})"
    assert shares.QUEUED.startswith("queued {id}: {path} (sha256 {short})")


def test_digest_is_sha256_of_raw_bytes() -> None:
    assert shares.digest(BYTES) == SHA
    assert shares.digest(b"a\r\n") != shares.digest(b"a\n")


def test_target_path_keeps_the_name_even_with_the_story_prefix() -> None:
    share = shares.Share("", "s1", "s1-mock.html", BYTES)
    assert shares.target_of("docs", share) == "docs/design/s1-s1-mock.html"


def test_target_path_drops_a_trailing_slash_of_docs_dir() -> None:
    share = shares.Share("", "s1", "mock.html", BYTES)
    assert shares.target_of("agile-team/docs/", share) == "agile-team/docs/design/s1-mock.html"


# ----- Share json -------------------------------------------------------------------


def test_share_round_trips_through_json() -> None:
    share = shares.Share("f1", "s1", "mock.html", BYTES, 5.0)
    data = json.loads(share.to_json())
    assert data["story"] == "s1" and data["name"] == "mock.html" and data["sha256"] == SHA
    assert base64.b64decode(data["data"]) == BYTES
    assert shares.Share.from_json("f1", share.to_json()) == share


def test_share_sha256_method() -> None:
    assert shares.Share("", "s1", "m.html", BYTES).sha256() == SHA


def test_binary_bytes_survive_the_round_trip() -> None:
    raw = bytes(range(256))
    share = shares.Share("f2", "s1", "x.bin", raw, 1.0)
    assert shares.Share.from_json("f2", share.to_json()).data == raw


def test_a_tampered_sha256_reads_as_none() -> None:
    data = json.loads(shares.Share("f1", "s1", "m.html", BYTES).to_json())
    data["sha256"] = OTHER
    assert shares.Share.from_json("f1", json.dumps(data)) is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"story": "s1"}',
        json.dumps({"story": "s1", "name": "n", "sha256": SHA, "data": "!!!", "at": 1}),
    ],
)
def test_bad_json_shape_or_base64_reads_as_none(text: str) -> None:
    assert shares.Share.from_json("f1", text) is None


# ----- render and with_entry (S5) ---------------------------------------------------


def test_render_lists_path_and_sha256() -> None:
    text = shares.render((entry(),))
    assert text.startswith("shared:\n") and text.endswith("\n")
    assert f'  - path: "{DESIGN}s1-mock.html"' in text
    assert f'    sha256: "{SHA}"' in text


def test_with_entry_appends_to_a_file_with_no_shared_list() -> None:
    out = shares.with_entry(STORY, entry())
    assert out is not None
    assert out.endswith("\n---\n\nBody text.\n")
    head = out.split("\n---\n", 1)[0]
    assert head.startswith(STORY.split("\n---\n", 1)[0])
    assert shares.render((entry(),)) in out


def test_with_entry_replaces_the_same_path_in_place() -> None:
    first = shares.with_entry(STORY, entry("a.html", OTHER))
    second = shares.with_entry(first, entry("b.html"))
    third = shares.with_entry(second, entry("a.html", SHA))
    assert third is not None
    listed = shares.listed(where(""), _meta(third))
    assert listed.files == (entry("a.html", SHA), entry("b.html"))
    assert third.count("a.html") == 1


def test_with_entry_appends_a_new_path_after_existing_ones() -> None:
    first = shares.with_entry(STORY, entry("a.html"))
    both = shares.with_entry(first, entry("b.html"))
    assert shares.listed(where(""), _meta(both)).paths() == (
        f"{DESIGN}s1-a.html",
        f"{DESIGN}s1-b.html",
    )


def test_with_entry_keeps_other_keys_and_the_body_byte_for_byte() -> None:
    text = (
        "---\nid: s1\n# a comment\ntitle:   'T'\nshared:\n"
        '  - path: "docs/design/s1-a"\n    sha256: "'
        + SHA
        + '"\ndepends_on: []\n---\nBody\n\n\nmore  \n'
    )
    out = shares.with_entry(text, entry("b.html"))
    assert out is not None
    assert "# a comment\ntitle:   'T'\n" in out and "depends_on: []\n" in out
    assert out.endswith("---\nBody\n\n\nmore  \n")


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter\n",
        "---\n: : bad: [yaml\n---\nbody\n",
        "---\nid: s1\nshared: nope\n---\nbody\n",
        "---\nid: s1\nshared:\n  - 3\n---\nbody\n",
        "---\n- a\n- b\n---\nbody\n",
    ],
)
def test_with_entry_is_none_when_unsafe(text: str) -> None:
    assert shares.with_entry(text, entry()) is None


def _meta(text: str) -> dict:
    import yaml

    return yaml.safe_load(text.split("\n---\n", 1)[0].removeprefix("---\n"))


# ----- listed (S6) ------------------------------------------------------------------


def test_a_missing_key_is_an_empty_list() -> None:
    assert shares.listed(where(), {"id": "s1"}) == shares.Listed()


def test_a_good_list_is_read() -> None:
    meta = {"shared": [{"path": f"{DESIGN}s1-m.html", "sha256": SHA}]}
    out = shares.listed(where(), meta)
    assert out.files == (shares.SharedFile(f"{DESIGN}s1-m.html", SHA),) and out.problems == ()
    assert out.paths() == (f"{DESIGN}s1-m.html",)


def test_an_empty_design_dir_accepts_any_path() -> None:
    meta = {"shared": [{"path": "anywhere/x", "sha256": SHA}]}
    assert shares.listed(where(""), meta).problems == ()


@pytest.mark.parametrize(
    ("meta", "problem"),
    [
        ({"shared": "x"}, ".team/stories/s1.md: shared: "),
        ({"shared": {"path": "p"}}, ".team/stories/s1.md: shared: "),
        ({"shared": [3]}, ".team/stories/s1.md: shared item 1: "),
        ({"shared": [{"sha256": SHA}]}, ".team/stories/s1.md: shared item 1: "),
        ({"shared": [{"path": 5, "sha256": SHA}]}, ".team/stories/s1.md: shared item 1: "),
        (
            {"shared": [{"path": "docs/other/x", "sha256": SHA}]},
            ".team/stories/s1.md: shared item 1: ",
        ),
        ({"shared": [{"path": f"{DESIGN}x"}]}, ".team/stories/s1.md: shared item 1: "),
        (
            {"shared": [{"path": f"{DESIGN}x", "sha256": SHA.upper()}]},
            ".team/stories/s1.md: shared item 1: ",
        ),
        (
            {"shared": [{"path": f"{DESIGN}x", "sha256": "abc"}]},
            ".team/stories/s1.md: shared item 1: ",
        ),
    ],
)
def test_each_problem_is_reported_with_its_prefix(meta: dict, problem: str) -> None:
    out = shares.listed(where(), meta)
    assert len(out.problems) == 1 and out.problems[0].startswith(problem)
    assert out.problems[0] != problem


def test_a_path_listed_twice_is_a_problem_on_the_second_item() -> None:
    item = {"path": f"{DESIGN}x", "sha256": SHA}
    out = shares.listed(where(), {"shared": [item, dict(item)]})
    assert len(out.problems) == 1 and "shared item 2: " in out.problems[0]


# ----- Listed.unnamed / changed -----------------------------------------------------


def test_unnamed_lists_paths_missing_from_the_text() -> None:
    listed = shares.Listed((entry("a.html"), entry("b.html")))
    assert listed.unnamed(f"see {DESIGN}s1-a.html only") == [f"{DESIGN}s1-b.html"]
    assert listed.unnamed("") == [f"{DESIGN}s1-a.html", f"{DESIGN}s1-b.html"]


def test_changed_lists_differing_and_missing_files() -> None:
    listed = shares.Listed((entry("a.html"), entry("b.html"), entry("c.html")))
    found = {f"{DESIGN}s1-a.html": SHA, f"{DESIGN}s1-b.html": OTHER, f"{DESIGN}s1-c.html": None}
    assert listed.changed(found) == [
        shares.CHANGED_LINE.format(path=f"{DESIGN}s1-b.html", found=OTHER[:12], recorded=SHA[:12]),
        shares.MISSING_LINE.format(path=f"{DESIGN}s1-c.html", recorded=SHA[:12]),
    ]


def test_changed_treats_an_unlisted_found_path_as_missing() -> None:
    assert shares.Listed((entry(),)).changed({}) == [
        shares.MISSING_LINE.format(path=f"{DESIGN}s1-mock.html", recorded=SHA[:12])
    ]


def test_line_texts() -> None:
    assert shares.CHANGED_LINE == "- {path}: sha256 {found} (shared {recorded})"
    assert shares.MISSING_LINE == "- {path}: missing (shared {recorded})"


# ----- brief_section (S9) -----------------------------------------------------------


def test_architect_and_proxy_get_their_section() -> None:
    listed = shares.Listed((entry(),))
    arch = shares.brief_section(listed, "architect")
    assert arch.startswith("## Shared files\n\nThe liaison shared these files for s1.")
    assert "## Shared files" in arch
    assert "Read them; never edit them: acceptance checks each one's SHA-256." in arch
    assert (
        "Name each path in your design file under ## Shared files; the design gate checks it."
        in arch
    )
    assert f"- `{DESIGN}s1-mock.html` (sha256 {SHA[:12]})" in arch
    proxy = shares.brief_section(listed, "customer-proxy")
    assert "Where an AC refers to one, judge the product against it." in proxy


def test_the_section_names_the_story_from_the_path() -> None:
    assert "for s1." in shares.brief_section(shares.Listed((entry(),)), "architect")


@pytest.mark.parametrize("role", ["developer-cli", "code-reviewer", "product-owner", ""])
def test_other_roles_get_no_section(role: str) -> None:
    assert shares.brief_section(shares.Listed((entry(),)), role) == ""


def test_no_files_means_no_section() -> None:
    assert shares.brief_section(shares.Listed(), "architect") == ""


def test_brief_notes_cover_exactly_two_roles() -> None:
    assert set(shares.BRIEF_NOTES) == {"architect", "customer-proxy"}


# ----- story_refusal / data_refusal (S2) --------------------------------------------


def make_config(repo: Path) -> config.Config:
    return config.load(repo)


def test_story_refusal_bad_id(configured: Path) -> None:
    share = shares.Share("", "../x", "m.html", b"")
    assert shares.story_refusal(make_config(configured), share) == "no story '../x'"


def test_story_refusal_no_story_file(configured: Path) -> None:
    share = shares.Share("", "s9", "m.html", b"")
    assert shares.story_refusal(make_config(configured), share) == (
        "no story 's9': .team/stories/s9.md does not exist"
    )


def test_story_refusal_checks_the_story_before_the_name(configured: Path) -> None:
    share = shares.Share("", "s9", "bad name", b"")
    assert "no story 's9'" in shares.story_refusal(make_config(configured), share)


@pytest.mark.parametrize("name", ["-", "", ".hidden", "a b", "a/b", "x" * 101, "é.html"])
def test_story_refusal_bad_name(configured: Path, name: str) -> None:
    write_story(configured)
    out = shares.story_refusal(make_config(configured), shares.Share("", "s1", name, b""))
    assert out == (
        f"file name '{name}' must be letters, digits, '.', '_' or '-', at most 100, "
        "starting with a letter or digit; rename it"
    )


@pytest.mark.parametrize("name", ["mock.html", "a", "A_b-c.1", "x" * 100, "9.png"])
def test_story_refusal_good_name(configured: Path, name: str) -> None:
    write_story(configured)
    assert shares.story_refusal(make_config(configured), shares.Share("", "s1", name, b"")) is None


def test_data_refusal() -> None:
    assert shares.data_refusal(b"x") is None
    assert shares.data_refusal(b"x" * shares.MAX_BYTES) is None
    assert shares.data_refusal(b"") == "the file is empty"
    assert shares.data_refusal(b"x" * (shares.MAX_BYTES + 1)) == (
        "the file is 5242881 bytes; the limit is 5242880"
    )


# ----- listed_of / check (I/O) ------------------------------------------------------


def story_with_entry(repo: Path, name: str = "mock.html", sha: str = SHA) -> shares.Listed:
    write_story(repo, shares.with_entry(STORY, entry(name, sha)))
    return shares.listed_of(make_config(repo), "s1")


def test_listed_of_reads_the_story_file(configured: Path) -> None:
    out = story_with_entry(configured)
    assert out.files == (entry(),) and out.problems == ()


def test_listed_of_a_missing_story_file_is_empty(configured: Path) -> None:
    assert shares.listed_of(make_config(configured), "s9") == shares.Listed()


def test_listed_of_an_unparseable_story_file_is_empty(configured: Path) -> None:
    write_story(configured, "---\n: : [bad\n---\nbody\n")
    assert shares.listed_of(make_config(configured), "s1") == shares.Listed()


def test_listed_of_reports_a_malformed_list(configured: Path) -> None:
    write_story(configured, "---\nid: s1\nshared: nope\n---\nbody\n")
    out = shares.listed_of(make_config(configured), "s1")
    assert out.files == () and len(out.problems) == 1


def test_listed_of_rejects_paths_outside_the_design_dir(configured: Path) -> None:
    text = f'---\nid: s1\nshared:\n  - path: "elsewhere/x"\n    sha256: "{SHA}"\n---\nb\n'
    write_story(configured, text)
    assert shares.listed_of(make_config(configured), "s1").problems


def test_check_passes_an_intact_file(configured: Path) -> None:
    story_with_entry(configured)
    system.make_dirs(configured / DESIGN)
    system.write_bytes(configured / DESIGN / "s1-mock.html", BYTES)
    out = shares.check(make_config(configured), "s1")
    assert out.changed == () and out.listed.files == (entry(),)


def test_check_reports_a_changed_file(configured: Path) -> None:
    story_with_entry(configured)
    system.make_dirs(configured / DESIGN)
    system.write_bytes(configured / DESIGN / "s1-mock.html", BYTES + b"x")
    out = shares.check(make_config(configured), "s1")
    found = hashlib.sha256(BYTES + b"x").hexdigest()[:12]
    assert out.changed == (
        shares.CHANGED_LINE.format(path=f"{DESIGN}s1-mock.html", found=found, recorded=SHA[:12]),
    )


def test_check_reports_a_missing_file(configured: Path) -> None:
    story_with_entry(configured)
    out = shares.check(make_config(configured), "s1")
    assert out.changed == (
        shares.MISSING_LINE.format(path=f"{DESIGN}s1-mock.html", recorded=SHA[:12]),
    )


def test_check_with_nothing_shared_is_clean(configured: Path) -> None:
    write_story(configured)
    out = shares.check(make_config(configured), "s1")
    assert out == shares.Check(shares.Listed())


# ----- the queue (S1) ---------------------------------------------------------------


def test_queue_writes_numbered_files_whole_with_no_draft(configured: Path) -> None:
    run_dir = configured / ".team" / "run"
    one = Shares(run_dir).queue(shares.Share("", "s1", "m.html", BYTES))
    two = Shares(run_dir).queue(shares.Share("", "s1", "n.html", BYTES))
    assert (one.id, two.id) == ("f1", "f2")
    assert queued(configured) == ["f1.json", "f2.json"]
    assert Shares(run_dir).all() == [one, two]


def test_pending_leaves_out_the_settled(configured: Path) -> None:
    run_dir = configured / ".team" / "run"
    Shares(run_dir).queue(shares.Share("", "s1", "m.html", BYTES))
    two = Shares(run_dir).queue(shares.Share("", "s1", "n.html", BYTES))
    assert Shares(run_dir).pending({"f1": "unchanged"}) == [two]


def test_all_with_no_folder_is_empty(configured: Path) -> None:
    assert Shares(configured / ".team" / "run").all() == []


def test_all_skips_other_names_and_bad_files(configured: Path) -> None:
    run_dir = configured / ".team" / "run"
    Shares(run_dir).queue(shares.Share("", "s1", "m.html", BYTES))
    system.write_text(run_dir / "liaison" / "shares" / "notes.txt", "x")
    system.write_text(run_dir / "liaison" / "shares" / "f9.json", "garbage")
    assert [s.id for s in Shares(run_dir).all()] == ["f1"]


def test_queue_moves_on_when_the_number_is_taken(configured: Path, monkeypatch) -> None:
    run_dir = configured / ".team" / "run"
    Shares(run_dir).queue(shares.Share("", "s1", "m.html", BYTES))
    real = system.hard_link
    calls: list[str] = []

    def racing(link: Path, target: Path) -> None:
        calls.append(link.name)
        if link.name == "f2.json":
            raise FileExistsError
        real(link, target)

    monkeypatch.setattr(system, "hard_link", racing)
    assert Shares(run_dir).queue(shares.Share("", "s1", "n.html", BYTES)).id == "f3"
    assert calls == ["f2.json", "f3.json"]


# ----- cmd_share (AC1, AC4) ---------------------------------------------------------


def source_file(scratch: Path, name: str = "mock.html", data: bytes = BYTES) -> Path:
    path = scratch / name
    system.write_bytes(path, data)
    return path


def test_share_queues_a_request_and_prints_the_path(
    configured: Path, scratch: Path, capsys
) -> None:
    write_story(configured)
    assert run_share(configured, str(source_file(scratch))) == 0
    assert capsys.readouterr().out.strip() == (
        f"queued f1: docs/design/s1-mock.html (sha256 {SHA[:12]}); "
        "the runner commits it between steps"
    )
    [only] = Shares(configured / ".team" / "run").all()
    assert (only.story, only.name, only.data) == ("s1", "mock.html", BYTES)


def test_share_touches_neither_the_tree_nor_the_story_file(configured: Path, scratch: Path) -> None:
    write_story(configured)
    run_share(configured, str(source_file(scratch)))
    assert system.read_text(configured / ".team" / "stories" / "s1.md") == STORY
    assert not system.exists(configured / DESIGN / "s1-mock.html")


def test_a_second_share_queues_f2(configured: Path, scratch: Path, capsys) -> None:
    write_story(configured)
    run_share(configured, str(source_file(scratch)))
    run_share(configured, str(source_file(scratch, "spec.md")))
    assert queued(configured) == ["f1.json", "f2.json"]
    assert "queued f2: docs/design/s1-spec.md" in capsys.readouterr().out


def test_share_uses_the_docs_dir_of_the_config(configured: Path, scratch: Path, capsys) -> None:
    write_story(configured)
    run_share(configured, str(source_file(scratch)))
    assert "docs/design/s1-mock.html" in capsys.readouterr().out


def refused(capsys) -> str:
    return capsys.readouterr().err


def test_share_refuses_a_bad_story_id(configured: Path, scratch: Path, capsys) -> None:
    assert run_share(configured, str(source_file(scratch)), "../x") == 1
    assert "no story '../x'" in refused(capsys)
    assert queued(configured) == []


def test_share_refuses_an_unknown_story(configured: Path, scratch: Path, capsys) -> None:
    assert run_share(configured, str(source_file(scratch)), "s77") == 1
    assert "no story 's77': .team/stories/s77.md does not exist" in refused(capsys)
    assert queued(configured) == []


def test_an_unknown_story_with_an_empty_file_reports_the_story(
    configured: Path, scratch: Path, capsys
) -> None:
    assert run_share(configured, str(source_file(scratch, data=b"")), "s77") == 1
    assert "no story 's77'" in refused(capsys)


def test_share_refuses_a_bad_name(configured: Path, scratch: Path, capsys) -> None:
    write_story(configured)
    assert run_share(configured, str(source_file(scratch, "bad name.html"))) == 1
    assert "file name 'bad name.html' must be letters" in refused(capsys)
    assert queued(configured) == []


def test_share_refuses_stdin(configured: Path, capsys) -> None:
    write_story(configured)
    assert run_share(configured, "-") == 1
    assert "file name '-' must be letters" in refused(capsys)


def test_share_refuses_an_unreadable_source(configured: Path, scratch: Path, capsys) -> None:
    write_story(configured)
    missing = scratch / "gone.html"
    assert run_share(configured, str(missing)) == 1
    assert f"cannot read {missing}: " in refused(capsys)
    assert queued(configured) == []


def test_share_refuses_an_empty_file(configured: Path, scratch: Path, capsys) -> None:
    write_story(configured)
    assert run_share(configured, str(source_file(scratch, data=b""))) == 1
    assert "the file is empty" in refused(capsys)
    assert queued(configured) == []


def test_share_refuses_an_oversize_file(configured: Path, scratch: Path, capsys) -> None:
    write_story(configured)
    big = source_file(scratch, data=b"x" * (shares.MAX_BYTES + 1))
    assert run_share(configured, str(big)) == 1
    assert "the file is 5242881 bytes; the limit is 5242880" in refused(capsys)
    assert queued(configured) == []


def test_share_accepts_a_file_of_exactly_the_limit(configured: Path, scratch: Path) -> None:
    write_story(configured)
    assert run_share(configured, str(source_file(scratch, data=b"x" * shares.MAX_BYTES))) == 0


def test_share_is_a_registered_command_right_after_tell() -> None:
    names = [c.name for c in cli.COMMANDS]
    assert names.index("share") == names.index("tell") + 1
