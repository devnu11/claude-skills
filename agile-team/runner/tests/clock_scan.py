"""Find real-clock reads and exact duration compares in test files (s129, ADR-0066)."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from enum import Enum
from pathlib import Path

TESTS = Path(__file__).resolve().parent
E2E_DIR = "e2e"
SCANNED = (".py", ".js", ".mjs")
EXEMPT = frozenset({"clock.py", "clock_scan.py", "test_s129_clock_scan.py"})
REAL_CLOCK_READS = (
    re.compile(r"\bDate\.now\(\)"),
    re.compile(r"\bperformance\.now\(\)"),
    re.compile(r"\bnew Date\(\)"),
    re.compile(r"\btime\.(time|monotonic|perf_counter)(_ns)?\("),
    re.compile(r"\bdatetime\.(now|utcnow|today)\("),
    re.compile(r"\bdate\.today\("),
    re.compile(r"\bfrom time import\b[^\n]*\b(time|monotonic|perf_counter)\b"),
)
DURATION_NAMES = frozenset(
    {
        "seconds",
        "slept",
        "slept_s",
        "awake",
        "age",
        "beat_age",
        "quiet_for",
        "elapsed",
        "waiting",
        "duration",
    }
)
RECORDED_SLEEPS = frozenset({"fake.slept"})
TOLERANT_CALLS = frozenset({"about", "approx"})
_EQUALITY = (ast.Eq, ast.NotEq)


class Tree(Enum):
    """Which part of TESTS a scan covers; the two parts make all of it."""

    UNIT = "unit"
    E2E = "e2e"


def _tree_of(path: Path) -> Tree:
    first = path.relative_to(TESTS).parts[0]
    return Tree.E2E if first == E2E_DIR else Tree.UNIT


def files_in(tree: Tree) -> list[Path]:
    """Files under TESTS in `tree` with a SCANNED suffix, minus EXEMPT, sorted."""
    found = [
        p
        for p in TESTS.rglob("*")
        if p.is_file() and p.suffix in SCANNED and p.name not in EXEMPT and _tree_of(p) is tree
    ]
    return sorted(found)


def read_tree(tree: Tree) -> dict[str, str]:
    """`{path relative to TESTS, posix: text}` for files_in(tree)."""
    return {p.relative_to(TESTS).as_posix(): p.read_text() for p in files_in(tree)}


def clock_reads(text: str) -> list[str]:
    """`<line>: <match>` for each real-clock read in `text`."""
    return [
        f"{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)}"
        for pattern in REAL_CLOCK_READS
        for m in pattern.finditer(text)
    ]


def leaf(node: ast.expr) -> str | None:
    """The name a value goes by: `x.attr` → attr, `x["key"]` → key, `name` → name."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return str(node.slice.value)
    return None


def tolerant(node: ast.expr) -> bool:
    """A call to about/approx (by leaf name of the callee) or the constant None."""
    if isinstance(node, ast.Constant):
        return node.value is None
    return isinstance(node, ast.Call) and leaf(node.func) in TOLERANT_CALLS


def is_duration(node: ast.expr) -> bool:
    """leaf(node) in DURATION_NAMES and ast.unparse(node) not in RECORDED_SLEEPS."""
    return leaf(node) in DURATION_NAMES and ast.unparse(node) not in RECORDED_SLEEPS


def _one_sided(a: ast.expr, b: ast.expr) -> bool:
    return (is_duration(a) and not tolerant(b)) or (is_duration(b) and not tolerant(a))


def _dict_violation(node: ast.expr) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    return any(_dict_item_bad(k, v) for k, v in zip(node.keys, node.values, strict=True))


def _dict_item_bad(key: ast.expr | None, value: ast.expr) -> bool:
    named = isinstance(key, ast.Constant) and key.value in DURATION_NAMES
    return (named and not tolerant(value)) or _dict_violation(value)


def _sequence_violation(a: ast.expr, b: ast.expr) -> bool:
    kinds = (ast.Tuple, ast.List)
    if not (isinstance(a, kinds) and isinstance(b, kinds) and len(a.elts) == len(b.elts)):
        return False
    return any(_one_sided(x, y) for x, y in zip(a.elts, b.elts, strict=True))


def _pair_violation(a: ast.expr, b: ast.expr) -> bool:
    return _one_sided(a, b) or _sequence_violation(a, b) or _dict_violation(a) or _dict_violation(b)


def _compare_lines(node: ast.Compare) -> list[int]:
    sides = [node.left, *node.comparators]
    pairs = zip(sides, sides[1:], node.ops, strict=False)
    bad = [isinstance(op, _EQUALITY) and _pair_violation(a, b) for a, b, op in pairs]
    return [node.lineno] * sum(bad)


def exact_duration_compares(source: str) -> list[int]:
    """Line numbers of `==`/`!=` compares on a duration inside an `assert`."""
    lines: list[int] = []
    for stmt in ast.walk(ast.parse(source)):
        if isinstance(stmt, ast.Assert):
            compares = [n for n in ast.walk(stmt.test) if isinstance(n, ast.Compare)]
            lines += [line for c in compares for line in _compare_lines(c)]
    return sorted(lines)


def clock_read_hits(sources: Mapping[str, str]) -> list[str]:
    """`<rel>:<line>: <match>` for every read in every source."""
    return [f"{rel}:{hit}" for rel, text in sources.items() for hit in clock_reads(text)]


def duration_hits(sources: Mapping[str, str]) -> list[str]:
    """`<rel>:<line>` for every exact duration compare in every `.py` source."""
    return [
        f"{rel}:{line}"
        for rel, text in sources.items()
        if rel.endswith(".py")
        for line in exact_duration_compares(text)
    ]
