"""Suppression comments."""

from house_rules.suppress import parse_suppressions


def test_allow_with_reason_and_several_rules() -> None:
    [found] = parse_suppressions(
        "x = 1  # house-rules: allow parameters, verb-name -- legacy API\n", "a.py"
    )
    assert (found.line, found.rules, found.reason) == (
        1,
        frozenset({"parameters", "verb-name"}),
        "legacy API",
    )


def test_noqa_codes_map_to_rules_and_others_are_ignored() -> None:
    [found] = parse_suppressions(
        "def f(a: bool):  # noqa: FBT001, E501 -- callback\n    pass\n", "a.py"
    )
    assert (found.rules, found.reason) == (frozenset({"boolean-parameter"}), "callback")


def test_unrelated_comments_and_unmapped_noqa_are_ignored() -> None:
    assert parse_suppressions("x = 1  # noqa: E501\ny = 2  # a comment\n", "a.py") == ()


def test_missing_reason_is_empty() -> None:
    [found] = parse_suppressions("x = 1  # house-rules: allow global-scope\n", "a.py")
    assert found.reason == ""


def test_untokenizable_text_has_no_suppressions() -> None:
    assert parse_suppressions('x = """\n', "a.py") == ()
