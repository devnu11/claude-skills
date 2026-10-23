"""The rules, as a table, and the check behind each one."""

from __future__ import annotations

import ast
import fnmatch
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import verbs
from .measure import count_statements, is_case_chain, is_docstring, strip_docstring
from .model import Limits, Suppression
from .names import get_first_word, is_dunder, is_exempt, to_snake_case
from .syntax import FUNCTION_TYPES, FunctionSite, Kind, walk_functions

if TYPE_CHECKING:
    from .config import Settings

MODULE = "<module>"
SUPPRESSIONS = "<suppressions>"
NEVER = 2**31
CONSTANT_NAME = re.compile(r"^_*[A-Z][A-Z0-9_]*$")
TOP_LEVEL_DEFINITIONS = (
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.TypeAlias,
)
OWN_BODY_STOPS = (*FUNCTION_TYPES, ast.ClassDef, ast.Lambda)
# Dunders whose signature the class chooses: a boolean there is still a flag.
USER_SIGNATURE_DUNDERS = frozenset({"__init__", "__new__", "__post_init__", "__call__"})


@dataclass(frozen=True)
class Measure:
    """What a check saw: a symbol, where it starts, the measured value and a detail."""

    symbol: str
    line: int
    value: int
    detail: str

    def merge(self, later: Measure) -> Measure:
        """One measure for both: values summed, this line kept, details joined."""
        detail = f"{self.detail}, {later.detail}"
        return Measure(self.symbol, self.line, self.value + later.value, detail)


@dataclass(frozen=True)
class ParsedModule:
    """A parsed file, with its path and the settings and suppressions that apply to it."""

    path: str
    tree: ast.Module
    settings: Settings
    suppressions: tuple[Suppression, ...] = ()


type Check = Callable[[ParsedModule], Iterable[Measure]]


@dataclass(frozen=True)
class Rule:
    """One rule: its name, what it checks, its default limits and its message."""

    name: str
    summary: str
    limits: Limits
    check: Check
    message: str
    ruff: tuple[str, ...] = ()


def check_global_scope(module: ParsedModule) -> Iterator[Measure]:
    """Top-level statements that are not imports, constants, definitions or the entry guard."""
    for index, statement in enumerate(module.tree.body):
        if not is_allowed_at_top(statement) and not (index == 0 and is_docstring(statement)):
            yield Measure(MODULE, statement.lineno, 1, f"line {statement.lineno}")


def is_allowed_at_top(statement: ast.stmt) -> bool:
    """A definition, a constant, the ``__main__`` guard or a ``TYPE_CHECKING`` import block."""
    if isinstance(statement, TOP_LEVEL_DEFINITIONS):
        return True
    return (
        is_constant_assignment(statement)
        or is_entry_guard(statement)
        or is_type_checking_block(statement)
    )


def is_constant_assignment(statement: ast.stmt) -> bool:
    """An assignment to UPPER_CASE or ``__dunder__`` names, or an ``X: TypeAlias = ...``."""
    if isinstance(statement, ast.Assign):
        return all(is_constant_target(target) for target in statement.targets)
    if not isinstance(statement, ast.AnnAssign):
        return False
    alias = ast.unparse(statement.annotation).endswith("TypeAlias")
    return alias or is_constant_target(statement.target)


def is_constant_target(target: ast.expr) -> bool:
    """``NAME``, ``__all__`` or a tuple of them."""
    if isinstance(target, ast.Tuple | ast.List):
        return all(is_constant_target(element) for element in target.elts)
    if not isinstance(target, ast.Name):
        return False
    return bool(CONSTANT_NAME.match(target.id)) or is_dunder(target.id)


def is_entry_guard(statement: ast.stmt) -> bool:
    """``if __name__ == "__main__":`` around one call, such as ``main()``."""
    if not isinstance(statement, ast.If) or statement.orelse or len(statement.body) != 1:
        return False
    test, only = statement.test, statement.body[0]
    calls = isinstance(only, ast.Expr | ast.Raise) and isinstance(
        get_statement_value(only), ast.Call
    )
    return calls and ast.unparse(test).replace("'", '"') == '__name__ == "__main__"'


def get_statement_value(statement: ast.stmt) -> ast.expr | None:
    """The expression an ``Expr`` evaluates or a ``raise`` raises."""
    return statement.exc if isinstance(statement, ast.Raise) else getattr(statement, "value", None)


def is_type_checking_block(statement: ast.stmt) -> bool:
    """``if TYPE_CHECKING:`` holding only imports."""
    if not isinstance(statement, ast.If) or statement.orelse:
        return False
    imports_only = all(isinstance(inner, ast.Import | ast.ImportFrom) for inner in statement.body)
    return imports_only and ast.unparse(statement.test).endswith("TYPE_CHECKING")


def check_function_length(module: ParsedModule) -> Iterator[Measure]:
    """Counted statements per function; a case chain is left alone."""
    for site in walk_functions(module.tree):
        if not is_case_chain(site.node.body):
            value = count_statements(strip_docstring(site.node.body))
            yield Measure(site.qualname, site.node.lineno, value, "statements")


def check_parameters(module: ParsedModule) -> Iterator[Measure]:
    """Parameters per function, leaving out dunders, overrides and factories."""
    for site in walk_functions(module.tree):
        exempt = is_dunder(site.name) or site.overrides
        if not exempt and not is_factory(site, module.settings.factory_names):
            yield Measure(site.qualname, site.node.lineno, len(site.parameters), "parameters")


def is_factory(site: FunctionSite, patterns: tuple[str, ...]) -> bool:
    """A static or class method whose name follows a factory pattern for its class."""
    if site.owner is None or site.kind not in {Kind.STATIC, Kind.CLASS}:
        return False
    owner = to_snake_case(site.owner.name)
    names = [pattern.replace("{class}", owner) for pattern in patterns]
    return any(fnmatch.fnmatchcase(site.name, name) for name in names)


def check_boolean_parameters(module: ParsedModule) -> Iterator[Measure]:
    """Parameters typed ``bool`` or defaulting to ``True`` or ``False``."""
    for site in walk_functions(module.tree):
        fixed = is_dunder(site.name) and site.name not in USER_SIGNATURE_DUNDERS
        if fixed or site.overrides or site.kind is Kind.ACCESSOR:
            continue
        flagged = [
            argument.arg
            for argument, default in list_parameter_defaults(site)
            if is_flag(argument, default)
        ]
        if flagged:
            yield Measure(site.qualname, site.node.lineno, len(flagged), ", ".join(flagged))


def list_parameter_defaults(site: FunctionSite) -> list[tuple[ast.arg, ast.expr | None]]:
    """Each parameter with its default, or ``None`` where it has none."""
    arguments = site.node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    padding: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    pairs = list(zip(positional, [*padding, *arguments.defaults], strict=True))
    return pairs + list(zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True))


def is_flag(argument: ast.arg, default: ast.expr | None) -> bool:
    """Annotated ``bool`` (alone or in a union) or defaulting to a bool literal."""
    if isinstance(default, ast.Constant) and isinstance(default.value, bool):
        return True
    if argument.annotation is None:
        return False
    names = {node.id for node in ast.walk(argument.annotation) if isinstance(node, ast.Name)}
    return "bool" in names or ast.unparse(argument.annotation).strip("'\"") == "bool"


def check_verb_names(module: ParsedModule) -> Iterator[Measure]:
    """Functions start with a verb; properties are nouns (or questions such as ``is_empty``)."""
    settings = module.settings
    for site in walk_functions(module.tree):
        if not is_name_checked(site, settings):
            continue
        detail = describe_name_problem(site, settings)
        if detail:
            yield Measure(site.qualname, site.node.lineno, 1, detail)


def is_name_checked(site: FunctionSite, settings: Settings) -> bool:
    """Whether the naming rules apply: not exempt, not an override or a property accessor."""
    if site.overrides or site.kind is Kind.ACCESSOR:
        return False
    factory = is_factory(site, settings.factory_names)
    return not factory and not is_exempt(site.name, settings.allow_names)


def describe_name_problem(site: FunctionSite, settings: Settings) -> str:
    """What is wrong with the function's first word, or ``""``."""
    word = get_first_word(site.name)
    if site.kind is Kind.PROPERTY:
        noun = word not in settings.known_verbs or word in verbs.PREDICATES
        return "" if noun else f"property `{site.name}` should be a noun, not start with `{word}`"
    return "" if is_verb(word, settings) else f"`{site.name}` should start with a verb"


def is_verb(word: str, settings: Settings) -> bool:
    """A known verb, its third-person form (``returns``) or British spelling (``normalise``)."""
    american = word[:-3] + "ize" if word.endswith("ise") else word
    stems = (word, american, word.removesuffix("s"), word.removesuffix("es"))
    return any(stem in settings.known_verbs for stem in stems)


def check_query_properties(module: ParsedModule) -> Iterator[Measure]:
    """Methods that take nothing, return a value and change nothing should be properties."""
    changing = list_changing_methods(module.tree)
    for site in walk_functions(module.tree):
        if site.qualname not in changing and is_query(site, module.settings):
            detail = f"`{site.qualname}` only reads: make it a property named with a noun"
            yield Measure(site.qualname, site.node.lineno, 1, detail)


def is_query(site: FunctionSite, settings: Settings) -> bool:
    """A plain synchronous method without parameters that returns a value and mutates nothing."""
    plain = site.kind is Kind.METHOD and site.receiver and not site.parameters
    if not plain or site.overrides or isinstance(site.node, ast.AsyncFunctionDef):
        return False
    if is_exempt(site.name, settings.allow_names):
        return False
    nodes = list(walk_own_body(site.node))
    return returns_value(nodes) and not mutates_self(nodes, site.receiver)


def list_changing_methods(tree: ast.Module) -> frozenset[str]:
    """Qualnames of methods that change ``self``, directly or through their own class's methods."""
    sites = [s for s in walk_functions(tree) if s.kind is Kind.METHOD and s.receiver]
    direct = frozenset(
        s.qualname for s in sites if mutates_self(list(walk_own_body(s.node)), s.receiver)
    )
    return extend_changing(sites, direct)


def extend_changing(sites: list[FunctionSite], changing: frozenset[str]) -> frozenset[str]:
    """Add the methods that call a changing method on ``self``, until nothing is added."""
    for _ in range(len(sites)):
        grown = changing | {s.qualname for s in sites if calls_changing(s, changing)}
        if grown == changing:
            break
        changing = grown
    return changing


def calls_changing(site: FunctionSite, changing: frozenset[str]) -> bool:
    """The method calls, on ``self``, a method of its own class that changes ``self``."""
    owner = site.qualname.rpartition(".")[0]
    return any(f"{owner}.{name}" in changing for name in list_self_calls(site))


def list_self_calls(site: FunctionSite) -> set[str]:
    """The names of the methods the body calls as ``self.<name>(...)``."""
    calls = (n for n in walk_own_body(site.node) if isinstance(n, ast.Call))
    return {
        call.func.attr
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == site.receiver
    }


def walk_own_body(node: ast.AST) -> Iterator[ast.AST]:
    """Every node inside ``node``'s body, not descending into nested functions or classes."""
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, OWN_BODY_STOPS):
            yield child
            yield from walk_own_body(child)


def returns_value(nodes: list[ast.AST]) -> bool:
    """A ``return`` with a value and no ``yield``: a generator is not a query."""
    if any(isinstance(node, ast.Yield | ast.YieldFrom) for node in nodes):
        return False
    returns = [node for node in nodes if isinstance(node, ast.Return)]
    return any(not is_none(node.value) for node in returns)


def is_none(value: ast.expr | None) -> bool:
    """No value, or the constant ``None``."""
    return value is None or (isinstance(value, ast.Constant) and value.value is None)


def mutates_self(nodes: list[ast.AST], receiver: str) -> bool:
    """Assigns to or deletes from ``self``, or calls a mutating method on it or its parts."""
    for node in nodes:
        targets = list_targets(node)
        if any(read_root_name(target) == receiver for target in targets):
            return True
        if isinstance(node, ast.Call) and is_mutating_call(node.func, receiver):
            return True
    return False


def list_targets(node: ast.AST) -> list[ast.expr]:
    """The targets an assignment or ``del`` writes to, tuples and lists unpacked."""
    if isinstance(node, ast.Assign | ast.Delete):
        found = list(node.targets)
    else:
        found = [node.target] if isinstance(node, ast.AugAssign | ast.AnnAssign) else []
    return [leaf for target in found for leaf in list_target_leaves(target)]


def list_target_leaves(target: ast.expr) -> list[ast.expr]:
    """``a, (b, c)`` -> ``[a, b, c]``."""
    if isinstance(target, ast.Tuple | ast.List):
        return [leaf for item in target.elts for leaf in list_target_leaves(item)]
    return [target]


def is_mutating_call(function: ast.expr, receiver: str) -> bool:
    """``self.set_x(...)`` or ``self.items.append(...)``."""
    if not isinstance(function, ast.Attribute):
        return False
    owned = read_root_name(function.value) == receiver
    return owned and get_first_word(function.attr) in verbs.MUTATING_VERBS


def read_root_name(node: ast.expr) -> str:
    """The name at the root of ``a.b[c].d``: ``a``."""
    while isinstance(node, ast.Attribute | ast.Subscript | ast.Starred):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def check_verb_synonyms(module: ParsedModule) -> Iterator[Measure]:
    """Function names starting with a synonym PowerShell asks to avoid."""
    synonyms = module.settings.known_synonyms
    for site in walk_functions(module.tree):
        word = get_first_word(site.name)
        if word in synonyms and is_name_checked(site, module.settings):
            detail = f"`{site.name}` starts with `{word}`: prefer `{synonyms[word]}`"
            yield Measure(site.qualname, site.node.lineno, 1, detail)


def check_suppression_reasons(module: ParsedModule) -> Iterator[Measure]:
    """Suppressions that give no reason."""
    for suppression in module.suppressions:
        if not suppression.reason:
            yield Measure(SUPPRESSIONS, suppression.line, 1, f"line {suppression.line}")


def check_suppression_excuses(module: ParsedModule) -> Iterator[Measure]:
    """Suppressions whose reason only says that tests or a design fixed the name."""
    for suppression in module.suppressions:
        if module.settings.is_excuse(suppression.reason):
            detail = f"line {suppression.line}: {suppression.reason}"
            yield Measure(SUPPRESSIONS, suppression.line, 1, detail)


RULES = (
    Rule(
        "global-scope",
        "A module's top level holds only imports, constants, definitions and the entry guard.",
        Limits(0, 0),
        check_global_scope,
        "top-level code at {detail}",
    ),
    Rule(
        "function-length",
        "Statements per function, not counting data, error handling or the docstring.",
        Limits(8, 12),
        check_function_length,
        "`{symbol}` has {value} statements (limit {limit})",
        ("PLR0915",),
    ),
    Rule(
        "parameters",
        "Parameters per function; constructors, dunders and factories are exempt.",
        Limits(2, 3),
        check_parameters,
        "`{symbol}` takes {value} parameters (limit {limit})",
        ("PLR0913", "PLR0917"),
    ),
    Rule(
        "boolean-parameter",
        "No parameter typed bool or defaulting to True or False: use an enum.",
        Limits(0, 0),
        check_boolean_parameters,
        "`{symbol}` takes boolean parameters: {detail}",
        ("FBT001", "FBT002"),
    ),
    Rule(
        "verb-name",
        "Function names start with a verb; properties are nouns.",
        Limits(0, 0),
        check_verb_names,
        "{detail}",
    ),
    Rule(
        "query-property",
        "A method that takes nothing, returns a value and changes nothing is a property.",
        Limits(0, 0),
        check_query_properties,
        "{detail}",
    ),
    Rule(
        "verb-synonym",
        "A verb PowerShell lists as a synonym to avoid; the canonical verb is suggested.",
        Limits(0, NEVER),
        check_verb_synonyms,
        "{detail}",
    ),
    Rule(
        "suppression-reason",
        "Every suppression says why: `# house-rules: allow <rule> -- <reason>`.",
        Limits(0, 0),
        check_suppression_reasons,
        "suppression without a reason at {detail}",
    ),
    Rule(
        "suppression-excuse",
        'A suppression gives a reason, not "tests or a design fixed the name": fix the name.',
        Limits(0, 0),
        check_suppression_excuses,
        "suppression excuses a name instead of giving a reason: {detail}",
    ),
)
RULE_IDS = frozenset(rule.name for rule in RULES)
RUFF_ALIASES = {code: rule.name for rule in RULES for code in rule.ruff}
