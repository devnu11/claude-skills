"""s134 end to end: the CLI's tell and share queue through one NumberedQueue."""

from __future__ import annotations

from pathlib import Path

from .test_liaison_e2e import run_cli


def _story(repo: Path) -> None:
    folder = repo / ".team" / "stories"
    folder.mkdir(parents=True, exist_ok=True)
    head = 'id: s1\ntitle: "A"\nacceptance:\n  - id: AC1\n    text: "x"\n    environment: cli\n'
    (folder / "s1.md").write_text(f"---\n{head}---\nbody\n")


def test_tell_skips_a_taken_number_and_leaves_no_draft(configured: Path) -> None:
    """AC1, AC2: t1 and t5 exist, so the next tell is t6; names stay t<N>.md."""
    folder = configured / ".team" / "run" / "liaison" / "messages"
    folder.mkdir(parents=True)
    (folder / "t1.md").write_text("one")
    (folder / "t5.md").write_text("five")
    told = run_cli(configured, "tell", "-", stdin="six\n")
    assert told.returncode == 0 and "queued t6 for the PO" in told.stdout
    assert (folder / "t6.md").read_text() == "six\n"
    assert sorted(p.name for p in folder.iterdir()) == ["t1.md", "t5.md", "t6.md"]


def test_share_queues_f_numbers_through_the_cli(configured: Path, tmp_path: Path) -> None:
    """AC1, AC2: two shares become f1.json and f2.json, no draft left."""
    _story(configured)
    source = tmp_path / "a.html"
    source.write_text("hi")
    for n in (1, 2):
        done = run_cli(configured, "share", str(source), "--story", "s1")
        assert done.returncode == 0 and f"f{n}" in done.stdout
    names = sorted(p.name for p in (configured / ".team" / "run" / "liaison" / "shares").iterdir())
    assert names == ["f1.json", "f2.json"]
