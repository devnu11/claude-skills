"""Find module-level mutable state that test code writes to (s130, ADR-0067)."""

from __future__ import annotations

import ast
from collections.abc import Mapping

from .clock_scan import TESTS, Tree, tree_of

MUTABLE_CALLS = frozenset(
    {"list", "dict", "set", "bytearray", "defaultdict", "deque", "Counter", "OrderedDict"}
)
MUTATORS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "pop",
        "remove",
        "clear",
        "update",
        "setdefault",
        "add",
        "discard",
        "popitem",
        "sort",
        "reverse",
        "appendleft",
        "extendleft",
        "popleft",
    }
)
HOOK_PREFIX = "pytest_"  # pytest hooks are not tests
_COMPREHENSIONS = (ast.ListComp, ast.DictComp, ast.SetComp)
_LITERALS = (ast.List, ast.Dict, ast.Set)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def py_sources(tree: Tree) -> dict[str, str]:
    """{posix path relative to TESTS: text} for every *.py in `tree`, sorted; no exemptions."""
    found = sorted(p for p in TESTS.rglob("*.py") if tree_of(p) is tree)
    return {p.relative_to(TESTS).as_posix(): p.read_text() for p in found}


def _callee_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def mutable_value(node: ast.expr) -> bool:
    """A list/dict/set literal or comprehension, a mutable constructor call, or a sum with one."""
    if isinstance(node, _LITERALS + _COMPREHENSIONS):
        return True
    if isinstance(node, ast.Call):
        return _callee_name(node) in MUTABLE_CALLS
    if isinstance(node, ast.BinOp):
        return mutable_value(node.left) or mutable_value(node.right)
    return False


def _bound_names(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, ast.Assign) and mutable_value(stmt.value):
        return [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    if isinstance(stmt, ast.AnnAssign) and stmt.value and mutable_value(stmt.value):
        return [stmt.target.id] if isinstance(stmt.target, ast.Name) else []
    return []


def module_mutables(module: ast.Module) -> frozenset[str]:
    """Names bound at the top level to a mutable value."""
    return frozenset(name for stmt in module.body for name in _bound_names(stmt))


def root_name(node: ast.expr) -> str | None:
    """The base Name's id under any chain of subscripts and attributes; else None."""
    while isinstance(node, ast.Subscript | ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _mutator_call(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return root_name(node.func.value) if node.func.attr in MUTATORS else None
    return None


def written_name(node: ast.AST) -> str | None:
    """The root name a node writes through (item/attribute store or delete, mutator call)."""
    if isinstance(node, ast.Subscript | ast.Attribute):
        return root_name(node) if isinstance(node.ctx, ast.Store | ast.Del) else None
    return _mutator_call(node)


def local_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """The function's parameters and every Name it stores."""
    args = func.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    stored = {
        n.id for n in ast.walk(func) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }
    return frozenset(stored | {a.arg for a in params if a})


def function_hits(
    func: ast.FunctionDef | ast.AsyncFunctionDef, mutables: frozenset[str]
) -> list[tuple[int, str]]:
    """(line, name) for each write to a module mutable, and for each `global` name."""
    watched = mutables - local_names(func)
    hits = []
    for node in ast.walk(func):
        if isinstance(node, ast.Global):
            hits += [(node.lineno, name) for name in node.names]
        elif (name := written_name(node)) in watched:
            hits.append((node.lineno, name))
    return hits


def write_lines(source: str) -> list[tuple[int, str]]:
    """Sorted, deduplicated hits in every non-hook function of `source`."""
    module = ast.parse(source)
    mutables = module_mutables(module)
    funcs = [n for n in ast.walk(module) if isinstance(n, _FUNCTIONS)]
    funcs = [f for f in funcs if not f.name.startswith(HOOK_PREFIX)]
    return sorted({hit for f in funcs for hit in function_hits(f, mutables)})


def state_hits(sources: Mapping[str, str]) -> list[str]:
    """["path:line: NAME", ...] over the .py entries of sources."""
    return [
        f"{rel}:{line}: {name}"
        for rel, text in sources.items()
        if rel.endswith(".py")
        for line, name in write_lines(text)
    ]
