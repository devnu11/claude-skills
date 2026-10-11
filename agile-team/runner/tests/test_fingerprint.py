"""s30 F5: content fingerprints ignore whitespace and comments."""

import pytest
from agile_team import fingerprint

PY = (
    "import pytest\n\n\n@pytest.mark.parametrize('n', [1, 2])\n"
    "def test_a(n):\n    assert f(n) == n\n"
)


def same(path: str, a: str, b: str) -> bool:
    return fingerprint.of(path, a) == fingerprint.of(path, b)


def test_of_is_a_deterministic_sha256_hex_digest() -> None:
    h = fingerprint.of("t.py", PY)
    assert h == fingerprint.of("t.py", PY)
    assert len(h) == 64 and int(h, 16) >= 0


@pytest.mark.parametrize(
    "edited",
    [
        "# new comment\n" + PY,
        PY.replace("    assert", "    # why\n    assert"),
        PY.replace("\n\n\n", "\n\n\n\n\n"),
        PY.replace("f(n) == n", "f( n )   ==   n"),
        PY.replace("== n", "== n  # trailing"),
    ],
)
def test_python_cosmetic_edits_keep_the_hash(edited) -> None:
    assert same("t.py", PY, edited)


def test_python_re_indent_keeps_the_hash() -> None:
    a = "def t():\n    if x:\n        y()\n"
    b = "def t():\n  if x:\n      y()\n"
    assert same("t.py", a, b)


@pytest.mark.parametrize(
    "edited",
    [
        PY.replace("== n", "== n + 1"),
        PY.replace("[1, 2]", "[1, 3]"),
        PY.replace("test_a", "test_b"),
        PY.replace("'n'", "'m'"),
        PY.replace("def test_a(n):\n", 'def test_a(n):\n    """doc"""\n'),
    ],
)
def test_python_real_edits_change_the_hash(edited) -> None:
    assert not same("t.py", PY, edited)


def test_python_that_does_not_tokenize_falls_back_to_lines() -> None:
    a = "x = (1,\n  2\n"
    assert same("t.py", a, "# c\n" + a + "\n\n")
    assert same("t.py", a, "x   =  (1,\n 2\n")
    assert not same("t.py", a, "x = (1,\n  3\n")


def test_pyi_is_python() -> None:
    assert same("t.pyi", "x: int  # c\n", "x: int\n")


@pytest.mark.parametrize(
    "path,mark", [("a.ts", "//"), ("a.go", "//"), ("a.sql", "--"), ("a.sh", "#"), ("a.yml", "#")]
)
def test_comment_lines_do_not_count_in_other_languages(path, mark) -> None:
    code = "one  two\nthree\n"
    assert same(path, code, f"{mark} note\n{code}\n\n")
    assert not same(path, code, code.replace("three", "four"))


def test_a_suffix_is_matched_case_insensitively() -> None:
    assert same("A.TS", "a\n", "// c\na\n")


def test_unknown_suffix_ignores_whitespace_but_not_hash_lines() -> None:
    assert same("a.txt", "a  b\n\n c\n", "a b\nc\n")
    assert not same("a.txt", "a b\n", "# c\na b\n")
    assert not same("Makefile", "a\n", "# c\na\n")


def test_trailing_and_block_comments_count_outside_python() -> None:
    assert not same("a.ts", "a\n", "a // c\n")
    assert not same("a.ts", "a\n", "/* c */\na\n")
