"""s7: forbidden roots are the deepest literal prefixes; the Proxy hook and deny rules use them."""

from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import guard, sandbox
from agile_team.config import Delivery
from agile_team.guard import Scope, ToolCall

REPO_GLOBS = {
    "source": ["agile-team/runner/agile_team/**", "agile-team/runner/scripts/**"],
    "tests": ["agile-team/runner/tests/**", "!agile-team/runner/tests/e2e/**"],
    "e2e": ["agile-team/runner/tests/e2e/**"],
}
REPO_ROOTS = [
    "agile-team/runner/agile_team",
    "agile-team/runner/scripts",
    "agile-team/runner/tests",
]


def nested_config(tmp_path: Path) -> cfg.Config:
    raw = {
        "team": {"docs_dir": "agile-team/docs"},
        "toolchain": {"globs": REPO_GLOBS},
        "delivery": [{"name": "cli", "kind": "package"}],
    }
    return cfg.from_raw(tmp_path, raw)


def scope_with(tmp_path: Path, roots: list[str]) -> Scope:
    return Scope("customer-proxy", tmp_path, [], cwd=tmp_path, bash_forbidden=roots)


def bash(scope: Scope, command: str) -> str | None:
    return guard.check_bash(scope, command)


def test_repo_roots(tmp_path: Path) -> None:
    assert sandbox.forbidden_roots(nested_config(tmp_path)) == REPO_ROOTS


def test_python_preset_roots(tmp_path: Path) -> None:
    globs = {"source": ["src/**"], "tests": ["tests/**", "!tests/e2e/**"], "e2e": ["tests/e2e/**"]}
    c = cfg.from_raw(tmp_path, {"toolchain": {"globs": globs}})
    assert sandbox.forbidden_roots(c) == ["src", "tests"]


def test_duplicate_globs_give_one_root(tmp_path: Path) -> None:
    globs = {"source": ["src/**", "src/**", "src/a/*.py"]}
    c = cfg.from_raw(tmp_path, {"toolchain": {"globs": globs}})
    assert sandbox.forbidden_roots(c) == ["src"]


def test_deny_rules_are_per_root_and_skip_docs(tmp_path: Path) -> None:
    c = nested_config(tmp_path)
    d = Delivery("cli", "package")
    c.deliveries = [d]
    s = sandbox.os_sandbox_settings(c, sandbox.Preparer().prepare(c, d))
    repo = str(tmp_path.resolve())
    expected = [
        rule for r in REPO_ROOTS for rule in (f"Read(/{repo}/{r})", f"Read(/{repo}/{r}/**)")
    ]
    assert s["permissions"]["deny"] == expected
    assert f"Read(/{repo}/agile-team/**)" not in s["permissions"]["deny"]
    assert str(Path(repo) / "agile-team/docs/customer") in s["sandbox"]["filesystem"]["allowRead"]


@pytest.mark.parametrize(
    ("token", "allowed"),
    [
        ("agile-team", True),
        ("agile-team/docs/customer/x.md", True),
        ("agile-team/runner", True),
        ("agile-team/runner/agile_team/cli.py", False),
        ("agile-team/runner/agile_team", False),
        ("./agile-team/runner/tests", False),
        ("agile-team/runner/tests/", False),
        ("agile-team//runner/agile_team/x", False),
        ("agile-team/./runner/scripts/x", False),
        ("agile-team/runner/testsuite", True),
    ],
)
def test_nested_bash_tokens(tmp_path: Path, token: str, allowed: bool) -> None:
    assert (bash(scope_with(tmp_path, REPO_ROOTS), f"cat {token}") is None) is allowed


def test_bare_cli_commands_allowed(tmp_path: Path) -> None:
    s = scope_with(tmp_path, REPO_ROOTS)
    assert bash(s, "agile-team status") is None
    assert bash(s, "which agile-team") is None
    assert bash(s, "ls agile-team/runner/tests")


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("cat src/x", False),
        ("ls ./tests", False),
        ("ls tests/", False),
        ("cat src//x", False),
        ("cat tests.txt", True),
        ("ls srcfoo", True),
    ],
)
def test_flat_layout_parity(tmp_path: Path, command: str, allowed: bool) -> None:
    assert (bash(scope_with(tmp_path, ["src", "tests"]), command) is None) is allowed


def test_proxy_end_to_end_in_nested_layout(tmp_path: Path) -> None:
    c = nested_config(tmp_path)
    d = Delivery("cli", "package")
    c.deliveries = [d]
    scope = sandbox.proxy_scope(c, sandbox.Preparer().prepare(c, d))
    read = lambda p: guard.check_tool_use(scope, ToolCall("Read", {"file_path": str(tmp_path / p)}))  # noqa: E731
    run = lambda cmd: guard.check_tool_use(scope, ToolCall("Bash", {"command": cmd}))  # noqa: E731
    assert read("agile-team/docs/customer/x.md") is None
    assert read("agile-team/runner/agile_team/cli.py")
    assert run("agile-team status") is None
    assert run("cat agile-team/runner/tests/test_x.py")
