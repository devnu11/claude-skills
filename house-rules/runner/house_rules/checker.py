"""Running the rules over sources and sorting the findings against the baseline."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field

from .baseline import Baseline
from .config import Settings
from .model import Finding, Level, Suppression
from .rules import MODULE, RULES, Measure, ParsedModule, Rule
from .source import Source
from .suppress import parse_suppressions

PARSE_ERROR = "parse-error"


@dataclass(frozen=True)
class Outcome:
    """Every finding and suppression of a run, sorted against the baseline."""

    findings: tuple[Finding, ...] = ()
    suppressions: tuple[Suppression, ...] = ()
    baseline: Baseline = field(default_factory=Baseline)
    paths: tuple[str, ...] = ()

    @property
    def failures(self) -> list[Finding]:
        """Failing findings the baseline does not cover: these fail the run."""
        return [item for item in self.failing if not self.baseline.covers(item)]

    @property
    def baselined(self) -> list[Finding]:
        """Failing findings the baseline already knows."""
        return [item for item in self.failing if self.baseline.covers(item)]

    @property
    def failing(self) -> list[Finding]:
        """Every finding at the failing level, baselined or not."""
        return [item for item in self.findings if item.level is Level.FAIL]

    @property
    def warnings(self) -> list[Finding]:
        """Findings that only warn."""
        return [item for item in self.findings if item.level is Level.WARN]

    @property
    def stale(self) -> list[str]:
        """Baseline entries for checked files that no longer fail."""
        return self.baseline.list_stale(self.findings, self.paths)

    @property
    def status(self) -> int:
        """0 when nothing new fails, 1 otherwise."""
        return 1 if self.failures else 0


@dataclass(frozen=True)
class RuleRun:
    """One rule applied to one module."""

    rule: Rule
    module: ParsedModule

    @property
    def findings(self) -> list[Finding]:
        """Measure, drop suppressed lines, merge per symbol, then grade."""
        allowed = {item.line for item in self.module.suppressions if self.rule.name in item.rules}
        kept = [measure for measure in self.rule.check(self.module) if measure.line not in allowed]
        graded = (self.grade(measure) for measure in merge_measures(kept))
        return [finding for finding in graded if finding]

    def grade(self, measure: Measure) -> Finding | None:
        """The finding a measure makes under the repo's limits and severity, if any."""
        settings = self.module.settings
        limits = settings.limits.get(self.rule.name, self.rule.limits)
        level = limits.classify(measure.value)
        if level is None:
            return None
        limit = limits.fail if level is Level.FAIL else limits.warn
        text = self.rule.message.format(**vars(measure), limit=limit)
        level = settings.severity.get(self.rule.name, level)
        return Finding(self.rule.name, level, self.module.path, measure.line, measure.symbol,
                       measure.value, limit, text)  # fmt: skip


def check_sources(sources: Iterable[Source], settings: Settings) -> Outcome:
    """Run every enabled rule over every source."""
    sources = list(sources)
    findings = [found for source in sources for found in check_source(source, settings)]
    suppressions = [
        item for source in sources for item in parse_suppressions(source.text, source.path)
    ]
    paths = tuple(source.path for source in sources)
    baseline = Baseline.from_file(settings.baseline_path)
    return Outcome(tuple(findings), tuple(suppressions), baseline, paths)


def check_source(source: Source, settings: Settings) -> list[Finding]:
    """The findings of one file."""
    try:
        tree = ast.parse(source.text, filename=source.path)
    except SyntaxError as error:
        return [describe_parse_error(source.path, error)]
    suppressions = parse_suppressions(source.text, source.path)
    module = ParsedModule(source.path, tree, settings, suppressions)
    rules = [rule for rule in RULES if rule.name not in settings.disable]
    return [finding for rule in rules for finding in RuleRun(rule, module).findings]


def describe_parse_error(path: str, error: SyntaxError) -> Finding:
    """A file that does not parse fails, at the line Python names."""
    return Finding(PARSE_ERROR, Level.FAIL, path, error.lineno or 1, MODULE, 1, 0, str(error.msg))


def merge_measures(measures: list[Measure]) -> list[Measure]:
    """One measure per symbol, in the order symbols first appear."""
    merged: dict[str, Measure] = {}
    for measure in measures:
        earlier = merged.get(measure.symbol)
        merged[measure.symbol] = earlier.merge(measure) if earlier else measure
    return list(merged.values())
