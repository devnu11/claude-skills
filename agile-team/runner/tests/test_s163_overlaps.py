"""s163 F4: which files overlap, with the ignored ones dropped."""

from __future__ import annotations

from agile_team import overlaps
from agile_team.overlaps import drop_ignored, match_pairs


def test_ignored_entries_are_dropped_on_all_four_patterns() -> None:
    entries = [
        ".team/stories/s1.md",
        "docs/architecture.md",
        "docs/design/s1.md",
        "docs/requirements/REQ-1.md",
        "src/a.py",
    ]
    assert drop_ignored(entries, "docs") == ["src/a.py"]


def test_ignored_follows_the_docs_dir() -> None:
    assert drop_ignored(["docs/design/s1.md", "x/design/s1.md"], "x") == ["docs/design/s1.md"]


def test_ignored_has_four_patterns() -> None:
    assert len(overlaps.IGNORED) == 4


def test_equal_paths_overlap_and_are_listed_once() -> None:
    assert match_pairs(["a.py", "b.py"], ["a.py"]) == ["a.py"]


def test_a_glob_on_our_side_matches_their_path() -> None:
    assert match_pairs(["src/**"], ["src/a/b.py"]) == ["src/** ~ src/a/b.py"]


def test_a_glob_on_their_side_matches_our_path() -> None:
    assert match_pairs(["src/a/b.py"], ["src/**"]) == ["src/a/b.py ~ src/**"]


def test_star_crosses_slashes() -> None:
    assert match_pairs(["a/*"], ["a/b/c.py"]) == ["a/* ~ a/b/c.py"]


def test_no_overlap_is_empty() -> None:
    assert match_pairs(["a.py"], ["b.py"]) == []
    assert match_pairs([], ["b.py"]) == []


def test_the_result_is_sorted_and_de_duplicated() -> None:
    out = match_pairs(["z.py", "a.py", "a.py"], ["a.py", "z.py", "a.py"])
    assert out == ["a.py", "z.py"]
