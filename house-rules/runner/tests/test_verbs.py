"""The verb tables."""

from house_rules import verbs


def test_human_verbs_are_all_known() -> None:
    assert verbs.HUMAN_VERBS <= verbs.VERBS


def test_create_is_not_a_synonym() -> None:
    assert "create" not in verbs.SYNONYMS


def test_synonyms_point_away_from_approved_verbs() -> None:
    assert not set(verbs.SYNONYMS) & verbs.POWERSHELL_VERBS


def test_predicates_are_verbs_for_functions() -> None:
    assert {"is", "has", "can", "should"} <= verbs.VERBS
