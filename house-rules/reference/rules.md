# house-rules reference

The rules, how each one measures, the settings, suppressions and the baseline.
The rule table in code is `house_rules/rules.py` (`RULES`); `house-rules rules`
prints it with the current repo's limits.

## Levels

Every finding is `warn` or `fail`.

- **`warn`:** reported, never fails a run, never recorded in the baseline.
- **`fail`:** fails the run (exit 1), unless the baseline covers it.

Measured rules have two thresholds. A value above `warn` warns, and above `fail` it fails.

## Rules

| Rule | Default | Ruff counterpart |
|---|---|---|
| `global-scope` | fail on any | — |
| `function-length` | warn > 8, fail > 12 | `PLR0915` (counts every statement, default 50) |
| `parameters` | warn > 2, fail > 3 | `PLR0913`/`PLR0917` (default 5, no factory exemption) |
| `boolean-parameter` | fail on any | `FBT001`/`FBT002` (positional only; here keyword-only too) |
| `verb-name` | fail | — |
| `query-property` | fail | — |
| `verb-synonym` | warn | — |
| `suppression-reason` | fail | — |
| `suppression-excuse` | fail | — |

Leave ruff's `FBT` and `PLR09xx` rules off (ruff's default) so nothing is reported twice.

### global-scope

A module's top level may hold only:
- the module docstring;
- imports, and `if TYPE_CHECKING:` blocks of imports;
- assignments to constants: every target is UPPER_CASE or a `__dunder__`;
- type aliases (`type X = ...`, or `X: TypeAlias = ...`);
- function and class definitions;
- `if __name__ == "__main__":` around one call, such as `main()`, `sys.exit(main())` or `raise SystemExit(main())`.

Anything else is top-level code: calls, loops, `with`, `try`, and assignments
to lower-case names (`logger = getLogger()`).

One finding per module. Its value is the number of offending statements, and
the message lists their lines. A suppression goes on the offending line.

### function-length

Statements in the function body are counted through nested blocks (`if`,
`for`, `while`, `with`, `match` cases, the body and `else` of `try`).

Not counted:
- the docstring;
- nested functions and classes, which are checked on their own;
- `raise` and `pass`;
- guard clauses: an `if` with no `else` whose body only raises or returns;
- `except` and `finally` blocks, and the `try` line itself;
- data declarations: assignments of a pure literal (a constant, or a list, tuple, set or dict of literals).

**Case chains are exempt.** If the body, apart from the docstring, is one
`match` or one `if`/`elif`/`else` chain, the function is not measured.

### parameters

Every parameter counts, except `self` or `cls`. `*args` and `**kwargs` count
one each.

Exempt:
- dunders (constructors and protocol methods);
- functions decorated `@override`, `@overload`, `@abstractmethod` or `@fixture`;
- factories (below).

**Factories are recognised by naming convention only.** A factory is a
`@staticmethod` or `@classmethod` on a class whose name matches
`factory_names`. The defaults are:
- `create`;
- `create_<class>`, where the class name is written in snake_case (`Shape.create_shape`);
- `from_*` (`Shape.from_dict`).

The logic inside a factory is free. An abstract factory that picks an
implementation from its arguments is still a factory. A free-standing builder
function is not one: move it onto its class.

### boolean-parameter

A parameter annotated `bool` (alone, in a union, or as a string), or one that
defaults to `True` or `False`, keyword-only parameters included. Use an enum.

Exempt: protocol dunders with fixed signatures (`__exit__`, `__eq__`, …), property setters
and deleters, and overrides. `__init__`, `__new__`, `__post_init__` and `__call__` are
checked: constructors are exempt from the parameter count, not from this rule.

### verb-name

- **Functions and methods:** the first word of the name must be a verb.
  - Only the first word is checked. The name is split on snake_case or camelCase, and leading `_` is ignored.
  - The third-person form of a listed verb counts (`returns_value`), and so does a British `-ise` spelling (`normalise`).
- **Properties are the reverse:** they are nouns. A property may not start
  with a verb, except a question word (`is_empty`, `has_children`).
- **The word list** combines several sources, as data in `house_rules/verbs.py`:
  - the human's verbs;
  - PowerShell's approved verbs, including the reserved `foreach`, `ping`, `sort`, `tee` and `where`;
  - common programming verbs;
  - the conversion and handler prefixes `to_`, `as_` and `on_`;
  - every synonym in the synonym map.

A noun-named function such as `area(shape)` fails. In object-oriented code,
the question belongs on the object, as a property (`shape.area`).

Exempt:
- dunders;
- `main` and `just_do_it` (in any casing);
- `test_*`;
- property setters;
- overrides and fixtures;
- factories;
- names matching `allow_names` (framework callbacks such as `do_GET` or `setUp`).

### query-property

A method that takes only `self`, returns a value, and changes nothing should
be a property named with a noun: `shape.area`, not `shape.get_area()`.

"Changes nothing" means it never assigns to, augments or deletes anything
rooted at `self`, and never calls a method on `self` (or on one of its
attributes) whose first word is a mutating verb (`set`, `add`, `append`,
`pop`, `update`, …). Two more cases count as a change:

- **Unpacked targets:** a tuple or list assignment writes each of its items,
  so `queued, self._queue = self._queue, []` changes `self._queue`.
- **Its own class's methods:** a method changes `self` when it calls, on
  `self` itself (`self._deliver()`), a method of the same class that changes
  `self`. That holds at any depth, and for private methods too. A call on
  another object (`self.runtime.x()`) only counts if its first word is a
  mutating verb.

The test is a heuristic. Mutation done through other objects can't be seen;
use a suppression with the reason.

Not checked:
- static and class methods, properties and async methods;
- generators;
- methods that return nothing;
- dunders, overrides and allowed names.

### verb-synonym (warn)

The first word is on PowerShell's "synonyms to avoid" list, so the canonical
verb is suggested: `delete` → `remove`, `fetch` → `get`, `validate` → `confirm`.

`create` is never flagged, because it names factories here. Words that are
approved verbs themselves are not in the map.

### suppression-reason

Every suppression must say why (see below). One finding per file, counting
the suppressions that have no reason.

### suppression-excuse

A suppression whose reason only says that tests, a test file or a design
fixed the name is refused: fix the name instead. One finding per file, at the
first such line; its message lists each one as `line <n>: <reason>`.

- **"Only says":** the reason is cut at its first `#` (a chained comment),
  stripped, and stripped of one trailing `.`. A pattern must then match all
  of it, ignoring case. `name fixed by the tests; it mirrors git's verb`
  passes, because it gives a reason too.
- **The default patterns** refuse reasons such as "name fixed by the tests",
  "name fixed by the s159 tests", "tool name fixed by the s163 design",
  "named by test_rewrite.py", "name fixed by a test file", "s163 design name",
  "the design's name", "the s159 tests use this name" and "the design named
  it".
- **A repo adds patterns** with `excuses` (see Settings). They extend the
  defaults and never replace them. To turn the rule off, `disable` it.
- **The excuse still suppresses** the rule it names; the finding is reported
  instead.

## Suppressions

Put the comment on the `def` line (or, for `global-scope`, on the offending
line):

```python
def show(rows, compact: bool):  # house-rules: allow boolean-parameter -- matches the CLI flag
```

- **Several rules:** separate them with commas.
- **A reason is required.** A suppression without one still suppresses, but
  it is a `suppression-reason` failure.
- **The reason can't be an excuse.** "Tests or a design fixed the name" is a
  `suppression-excuse` failure.
- **The two suppression rules can't be suppressed** on a line: a comment
  that names `suppression-reason` or `suppression-excuse` still gets that
  finding. Only `disable` turns them off.
- **Ruff's `noqa` codes work as aliases** for the rules ruff shares, and need
  a reason too: `# noqa: FBT001 -- callback signature`. Ruff itself accepts
  text after the codes (checked with ruff 0.16).
- **Reviewers see them all:** `check` lists every suppression with its reason.

## Baseline

`.house-rules-baseline.json` at the root (setting `baseline`) maps
`path::symbol::rule` to the measured value of each failing violation.

- **What fails a `check`:** a new key, or a value larger than its baseline.
- **Renames:** a renamed or moved function is a new key.
- **Fixes:** a fixed violation passes. Its entry is reported as stale until
  `baseline` drops it.
- **`baseline`:** rewrites the file and only ever shrinks it. It refuses new
  keys and larger values unless given `--accept-new`, which is for adopting
  the tool on a repo, with the human's OK.

## Settings

Settings live in `.house-rules.toml`, or `[tool.house-rules]` in
`pyproject.toml`. The nearest file above the working directory wins (or above
the edited file, for the hook), and its directory is the root. With no file,
the root is the git work tree. Unknown keys and rule names are errors.

| Key | Default | Meaning |
|---|---|---|
| `include` | `["**/*.py"]` | Files to check. `*` crosses directories; `**/` may match nothing. |
| `exclude` | `.venv`, `build`, `dist`, `node_modules` | Files to skip. |
| `tests` | `"skip"` | `"check"` to check test files too. |
| `test_globs` | `**/tests/**`, `**/test_*.py`, `**/*_test.py`, `**/conftest.py` | What counts as a test. |
| `limits` | as above | `[limits.parameters]` `warn = 3` `fail = 5`. Accepts `function_length` or `function-length`. |
| `severity` | — | `{verb-name = "warn"}` overrides a rule's level. |
| `disable` | — | Rules not to run. |
| `verbs` | — | Extra verbs. |
| `synonyms` | — | Extra synonyms: `{zap = "remove"}`. |
| `allow_names` | — | Name patterns exempt from naming rules (`do_*`, `setUp`). |
| `factory_names` | `create`, `create_{class}`, `from_*` | Factory name patterns. |
| `excuses` | — | Extra regex patterns for `suppression-excuse`, matched against the whole reason, ignoring case. A pattern that doesn't compile is a config error. |
| `baseline` | `.house-rules-baseline.json` | Baseline path, relative to the root. |
