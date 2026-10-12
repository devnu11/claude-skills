"""Walking a module's functions with the class that owns them."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
PROPERTY_DECORATORS = frozenset({"property", "cached_property"})
ACCESSOR_DECORATORS = frozenset({"setter", "deleter", "getter"})
OVERRIDE_DECORATORS = frozenset({"override", "overload", "abstractmethod", "fixture"})


class Kind(StrEnum):
    """What a function is to the class around it."""

    FUNCTION = "function"
    METHOD = "method"
    STATIC = "staticmethod"
    CLASS = "classmethod"
    PROPERTY = "property"
    ACCESSOR = "accessor"


SELF_KINDS = frozenset({Kind.METHOD, Kind.CLASS, Kind.PROPERTY, Kind.ACCESSOR})


@dataclass(frozen=True)
class Scope:
    """The class a definition sits in, if any, and its dotted prefix."""

    owner: ast.ClassDef | None = None
    prefix: str = ""


@dataclass(frozen=True)
class FunctionSite:
    """A function or method, with the class that owns it and its dotted name."""

    node: FunctionNode
    owner: ast.ClassDef | None
    qualname: str

    @property
    def name(self) -> str:
        """The function's own name."""
        return self.node.name

    @cached_property
    def decorators(self) -> frozenset[str]:
        """The last name of each decorator: ``@functools.cache`` -> ``cache``."""
        return frozenset(read_decorator_name(item) for item in self.node.decorator_list)

    @cached_property
    def kind(self) -> Kind:
        """Function, method, static or class method, property or property accessor."""
        if self.owner is None:
            return Kind.FUNCTION
        for kind, names in KIND_DECORATORS:
            if self.decorators & names:
                return kind
        return Kind.METHOD

    @cached_property
    def parameters(self) -> list[ast.arg]:
        """Every parameter, without the ``self`` or ``cls`` a method receives."""
        arguments = self.node.args
        every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        every += [extra for extra in (arguments.vararg, arguments.kwarg) if extra]
        positional = arguments.posonlyargs or arguments.args
        return every[1:] if self.kind in SELF_KINDS and positional else every

    @property
    def receiver(self) -> str:
        """The name of the first positional parameter (``self`` in a method), or ``""``."""
        positional = self.node.args.posonlyargs or self.node.args.args
        return positional[0].arg if positional else ""

    @property
    def overrides(self) -> bool:
        """Its signature or name is set elsewhere: an override, overload or fixture."""
        return bool(self.decorators & OVERRIDE_DECORATORS)


KIND_DECORATORS = (
    (Kind.STATIC, frozenset({"staticmethod"})),
    (Kind.CLASS, frozenset({"classmethod"})),
    (Kind.PROPERTY, PROPERTY_DECORATORS),
    (Kind.ACCESSOR, ACCESSOR_DECORATORS),
)


def read_decorator_name(decorator: ast.expr) -> str:
    """``@a.b(c)`` -> ``b``; ``@name`` -> ``name``."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr
    return target.id if isinstance(target, ast.Name) else ""


def walk_functions(tree: ast.Module) -> Iterator[FunctionSite]:
    """Every function in ``tree``, nested ones included, outermost first."""
    yield from walk_scope(tree.body, Scope())


def walk_scope(nodes: list[ast.stmt], scope: Scope) -> Iterator[FunctionSite]:
    """The functions defined in ``nodes`` and in everything nested in them."""
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            yield from walk_scope(node.body, Scope(node, f"{scope.prefix}{node.name}."))
        elif isinstance(node, FUNCTION_TYPES):
            site = FunctionSite(node, scope.owner, scope.prefix + node.name)
            yield site
            yield from walk_scope(node.body, Scope(None, f"{site.qualname}."))
        else:
            yield from walk_scope(list_nested_statements(node), scope)


def list_nested_statements(node: ast.AST) -> list[ast.stmt]:
    """The statements inside a compound statement: its blocks, handlers and cases."""
    nested: list[ast.stmt] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            nested.append(child)
        elif isinstance(child, ast.ExceptHandler | ast.match_case):
            nested.extend(child.body)
    return nested
