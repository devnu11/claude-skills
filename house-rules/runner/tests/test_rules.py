"""Each rule against its samples: `# expect: <rule> <level>` marks every finding."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from house_rules.checker import check_source
from house_rules.config import Settings
from house_rules.model import Level, Limits
from house_rules.rules import RUFF_ALIASES, RULE_IDS, RULES
from house_rules.source import Source

from .conftest import SAMPLES, CheckText

EXPECT = re.compile(r"# expect: (?P<rule>[\w-]+) (?P<level>warn|fail)")
SAMPLE_RULES = sorted(
    path.stem.rsplit("_", 1)[0].replace("_", "-") for path in SAMPLES.glob("*_fail.py")
)


def read_expected(path: Path) -> set[tuple[str, str, int]]:
    lines = path.read_text().splitlines()
    return {(match["rule"], match["level"], number) for number, line in enumerate(lines, 1)
            for match in [EXPECT.search(line)] if match}  # fmt: skip


def check_sample(path: Path, rule: str) -> set[tuple[str, str, int]]:
    settings = Settings(SAMPLES, disable=RULE_IDS - {rule}, allow_names=("do_*",))
    findings = check_source(Source(path.name, path.read_text()), settings)
    return {(finding.rule, str(finding.level), finding.line) for finding in findings}


def test_every_rule_has_samples() -> None:
    assert set(SAMPLE_RULES) == RULE_IDS


@pytest.mark.parametrize("rule", SAMPLE_RULES)
def test_failing_sample(rule: str) -> None:
    path = SAMPLES / f"{rule.replace('-', '_')}_fail.py"
    assert check_sample(path, rule) == read_expected(path)


@pytest.mark.parametrize("rule", SAMPLE_RULES)
def test_passing_sample(rule: str) -> None:
    assert check_sample(SAMPLES / f"{rule.replace('-', '_')}_pass.py", rule) == set()


def test_global_scope_counts_every_offending_statement(check_text: CheckText) -> None:
    [finding] = check_text(
        (SAMPLES / "global_scope_fail.py").read_text(), disable=RULE_IDS - {"global-scope"}
    )
    assert (finding.value, finding.line) == (3, 6)
    assert finding.message == "top-level code at line 6, line 7, line 15"


def test_function_length_counts_the_same_with_handling(check_text: CheckText) -> None:
    findings = check_text((SAMPLES / "function_length_fail.py").read_text())
    values = {f.symbol: f.value for f in findings if f.rule == "function-length"}
    assert values == {"run_nine": 9, "run_nine_with_handling": 9, "run_thirteen": 13}


def test_parameters_limits_are_configurable(check_text: CheckText) -> None:
    text = "def add(a, b, c, d):\n    return a\n"
    [finding] = check_text(text, limits={"parameters": Limits(3, 5)})
    assert (finding.level, finding.limit) == (Level.WARN, 3)


def test_severity_overrides_the_level(check_text: CheckText) -> None:
    findings = check_text(
        "def area(shape):\n    return shape\n", severity={"verb-name": Level.WARN}
    )
    assert [(f.rule, f.level) for f in findings] == [("verb-name", Level.WARN)]


def test_extra_verbs_are_accepted(check_text: CheckText) -> None:
    assert check_text("def frobnicate(x):\n    return x\n", verbs=frozenset({"frobnicate"})) == []


def test_extra_synonyms_warn(check_text: CheckText) -> None:
    findings = check_text("def zap(x):\n    return x\n", synonyms={"zap": "remove"})
    assert [f.message for f in findings] == ["`zap` starts with `zap`: prefer `remove`"]


def test_nested_functions_are_checked_with_dotted_names(check_text: CheckText) -> None:
    text = "def run():\n    def add_up(a, b, c, d):\n        return a\n    return add_up\n"
    [finding] = check_text(text)
    assert (finding.symbol, finding.rule) == ("run.add_up", "parameters")


def test_functions_inside_compound_statements_are_found(check_text: CheckText) -> None:
    text = "try:\n    import x\nexcept ImportError:\n    def area(s):\n        return s\n"
    rules = {f.rule for f in check_text(text)}
    assert rules == {"global-scope", "verb-name"}


def test_mutation_through_subscript_and_delete_is_not_a_query(check_text: CheckText) -> None:
    text = (
        "class A:\n"
        "    def take_first(self):\n        del self.items[0]\n        return 1\n"
        "    def bump_count(self):\n        self.count += 1\n        return self.count\n"
        "    def get_size(self):\n        return len(self.items)\n"
    )
    assert [f.symbol for f in check_text(text) if f.rule == "query-property"] == ["A.get_size"]


def test_bool_annotation_as_a_string(check_text: CheckText) -> None:
    findings = check_text("def show(rows, compact: 'bool'):\n    return rows\n")
    assert [f.rule for f in findings] == ["boolean-parameter"]


def test_ruff_aliases_map_to_rules() -> None:
    assert RUFF_ALIASES == {
        "PLR0915": "function-length",
        "PLR0913": "parameters",
        "PLR0917": "parameters",
        "FBT001": "boolean-parameter",
        "FBT002": "boolean-parameter",
    }


def test_rule_names_are_unique() -> None:
    assert len(RULE_IDS) == len(RULES)


def excuse_findings(check_text: CheckText, text: str, **overrides: object) -> list:
    return [f for f in check_text(text, **overrides) if f.rule == "suppression-excuse"]


def test_the_excuse_sample_merges_into_one_failing_finding(check_text: CheckText) -> None:
    text = (SAMPLES / "suppression_excuse_fail.py").read_text()
    [finding] = excuse_findings(check_text, text)
    assert (finding.level, finding.line, finding.path) == (Level.FAIL, 4, "sample.py")
    for reason in ("tests use it", "s163 design name", "NAME FIXED BY THE DESIGN"):
        assert reason in finding.message


def test_an_excuse_still_hides_the_rule_it_names(check_text: CheckText) -> None:
    text = (
        "def fetch(x):  # house-rules: allow verb-name -- name fixed by the tests\n    return x\n"
    )
    assert {f.rule for f in check_text(text)} == {"suppression-excuse"}


def test_a_repo_can_disable_the_excuse_rule(check_text: CheckText) -> None:
    text = (
        "def fetch(x):  # house-rules: allow verb-name -- name fixed by the tests\n    return x\n"
    )
    assert excuse_findings(check_text, text, disable=frozenset({"suppression-excuse"})) == []


def test_unpacked_assignment_targets_are_a_change_q1(check_text: CheckText) -> None:
    text = (
        "class A:\n"
        "    def drain(self):\n        queued, self.q = self.q, []\n        return len(queued)\n"
        "    def flush(self):\n        [a, self.q] = [1, []]\n        return a\n"
    )
    assert [f for f in check_text(text) if f.rule == "query-property"] == []


def test_a_method_reaching_a_change_through_self_calls_is_not_a_query_q2(
    check_text: CheckText,
) -> None:
    text = (
        "class A:\n"
        "    def deliver_news(self):\n        return self._step()\n"
        "    def _step(self):\n        return self._save()\n"
        "    def _save(self):\n        self.x = 1\n        return 1\n"
    )
    assert [f for f in check_text(text) if f.rule == "query-property"] == []


def test_a_method_calling_a_pure_sibling_is_still_a_query_q2(check_text: CheckText) -> None:
    text = (
        "class A:\n"
        "    def get_size(self):\n        return self._count()\n"
        "    def _count(self):\n        return len(self.items)\n"
    )
    assert "A.get_size" in [f.symbol for f in check_text(text) if f.rule == "query-property"]


def test_a_same_named_changer_in_another_class_does_not_count_q2(check_text: CheckText) -> None:
    text = (
        "class A:\n"
        "    def get_size(self):\n        return self._count()\n"
        "    def _count(self):\n        return len(self.items)\n"
        "class B:\n"
        "    def _count(self):\n        self.n = 1\n        return 1\n"
    )
    assert "A.get_size" in [f.symbol for f in check_text(text) if f.rule == "query-property"]
