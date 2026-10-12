"""Splitting names into words, and exemptions."""

import pytest
from house_rules.names import get_first_word, is_dunder, is_exempt, split_words, to_snake_case


@pytest.mark.parametrize(
    ("name", "words"),
    [("_load_ConfigFile", ["load", "config", "file"]), ("getArea", ["get", "area"]),
     ("HTTPServer", ["httpserver"]), ("__", [])],
)  # fmt: skip
def test_split_words(name: str, words: list[str]) -> None:
    assert split_words(name) == words


def test_first_word_of_an_empty_name() -> None:
    assert get_first_word("__") == ""


def test_dunder() -> None:
    assert is_dunder("__init__") and not is_dunder("__") and not is_dunder("_init")


@pytest.mark.parametrize("name", ["__repr__", "main", "justDoIt", "test_area", "do_GET"])
def test_exempt_names(name: str) -> None:
    assert is_exempt(name, ("do_*",))


def test_not_exempt() -> None:
    assert not is_exempt("area", ())


def test_snake_case() -> None:
    assert to_snake_case("CreateShape") == "create_shape"
