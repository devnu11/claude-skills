"""s76 AC5/J6: the kill-word check finds a code file that kills processes by name."""

import pytest

from . import kill_words
from .kill_words import ALLOWED, WORDS, is_code, offenders

PKILL = f"{WORDS[0]} -f x"
KILLALL = f"{WORDS[1]} python"


def test_the_pattern_names_every_word_whole() -> None:
    assert len(WORDS) == 2
    assert all(kill_words.PATTERN.search(f"run {w} -f") for w in WORDS)
    assert not any(kill_words.PATTERN.search(f"x{w}y") for w in WORDS)


def test_an_offending_script_is_reported_with_its_line() -> None:
    files = {"scripts/x.sh": f"#!/bin/sh\necho start\n{PKILL}\n"}
    assert offenders(files) == [f"scripts/x.sh:3: {WORDS[0]}"]


def test_every_use_on_a_line_and_every_file_is_reported() -> None:
    files = {"a.py": f"x = '{PKILL}; {KILLALL}'\n", "b.yml": f"run: {KILLALL}\n"}
    assert offenders(files) == [
        f"a.py:1: {WORDS[0]}",
        f"a.py:1: {WORDS[1]}",
        f"b.yml:1: {WORDS[1]}",
    ]


@pytest.mark.parametrize("path", sorted(ALLOWED))
def test_the_same_text_in_an_allowed_path_is_not_reported(path: str) -> None:
    assert offenders({path: PKILL}) == []


def test_the_allowed_paths_are_the_guard_tables_and_this_table() -> None:
    assert {p.rsplit("/", 1)[-1] for p in ALLOWED} == {
        "kill_check.py",
        "test_kill_check.py",
        "test_signal_own_groups_e2e.py",
        "kill_words.py",
    }


def test_prose_is_not_scanned() -> None:
    assert offenders({"docs/guide.md": PKILL, "notes.txt": PKILL}) == []


def test_a_suffixless_file_is_code_when_it_has_a_shebang() -> None:
    assert offenders({"bin/stop": f"#!/bin/sh\n{PKILL}\n"}) == [f"bin/stop:2: {WORDS[0]}"]
    assert offenders({"LICENSE": PKILL}) == []


def test_a_word_inside_another_word_is_not_a_use() -> None:
    assert offenders({"a.py": "skillall = 1\npkilled = 2\n"}) == []


def test_empty_input_has_no_offenders() -> None:
    assert offenders({}) == []
    assert offenders({"a.py": ""}) == []


@pytest.mark.parametrize(
    ("path", "text", "code"),
    [
        ("a.py", "", True),
        ("x/y.sh", "", True),
        ("ci.yml", "", True),
        ("pyproject.toml", "", True),
        ("index.html", "", True),
        ("README.md", "#!/bin/sh", False),
        ("Makefile", "all:\n", False),
        ("run", "#!/usr/bin/env bash\n", True),
    ],
)
def test_is_code(path: str, text: str, code: bool) -> None:
    assert is_code(path, text) is code
