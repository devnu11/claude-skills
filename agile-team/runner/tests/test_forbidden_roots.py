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


NESTED_ALLOW = [
    "cat agile-team",
    "cat agile-team/runner",
    "cat agile-team/runner/testsuite",
    "agile-team status",
    "agile-team --help",
    "which agile-team",
    "cat agile-team/docs/customer/x.md",
    "cat agile-team/docs/*.md",
    "cat agile-team/docs/customer/*",
    "cat agile-team/docs/customer/{a,b}.md",
    "cat agile-team/README*",
    "ls agile-team/*",
    "cat .team/stories/*",
    "cat *.txt",
    "cat ./*.txt",
    "echo {1..3}",
    "ls *",
    "ls ?",
    "ls **",
    'cat "agile-team/docs/x.md" # it\'s',
]
NESTED_DENY = [
    # literal words (W4, W6)
    "cat agile-team/runner/agile_team/cli.py",
    "cat agile-team/runner/agile_team",
    "ls ./agile-team/runner/tests",
    "ls agile-team/runner/tests/",
    "cat agile-team//runner/agile_team/x",
    "cat agile-team/./runner/scripts/x",
    "cat 'agile-team/runner/agile_team'/cli.py",
    "cat AGILE-TEAM/runner/agile_team/cli.py",
    # fallback when shlex cannot parse (W1)
    'cat "agile-team/runner/agile_team/cli.py" # it\'s',
    # wildcards (D1)
    "cat agile-team/runner/agile_*/cli.py",
    "cat agile-team/runner/agile_tea?/x",
    "cat agile-team/runner/agile_tea[m]/x",
    "cat agile-team/*/agile_team/x",
    "ls agile-team/**",
    "cat agile-team/**/cli.py",
    "cat agile-team/runner/*",
    "cat agile-team/runner/tests/*",
    "cat agile-team/runner/scripts?",
    "cat a*/runner/agile_team/x",
    "cat agile-team/run*/agile_team/x",
    # braces and groups (W2)
    "cat agile-team/runner/agile_team{,}/x",
    "cat agile-team/runner/{agile_team,x}/cli.py",
    "cat {agile-team/runner,x}/agile_team/cli.py",
    "cat agile-team/docs/{..,x}/runner/agile_team/cli.py",
    "cat agile-team/docs/.*/runner/agile_team/cli.py",
    "cat agile-team/runner/(agile_team|x)/cli.py",
    "cat agile-team/runner/agile_tea(m)",
    # normalisation before wildcards (B1)
    "cat ./agile-team/runner/agile_*/x",
    "cat agile-team//runner/agile_*/x",
    "cat .//agile-team/runner/agile_*",
    "cat agile-team/./runner/agile_*/cli.py",
    "cat agile-team/runner/./agile_*/cli.py",
    "cat ./agile-team/./runner/agile_t*/cli.py",
    # quoted and escaped globs (W1)
    "cat 'agile-team/runner/agile_'*/cli.py",
    "cat agile-team/runner/agile_\\*/x",
    # leading wildcards and braces (B2)
    "cat {,}agile-team/runner/agile_team/cli.py",
    "cat */runner/agile_team/cli.py",
    "cat */*/agile_*/cli.py",
    "cat ?gile-team/runner/agile_team/cli.py",
    "cat [a]gile-team/runner/agile_team/x",
    # deliberate over-denies
    "cat {docs,x}/a.md",
    "ls **/*.md",
    "cat .*/x",
    "cat agile-team/runner/agile_tea[x]/y",
]


NESTED_CASES = [(c, True) for c in NESTED_ALLOW] + [(c, False) for c in NESTED_DENY]


@pytest.mark.parametrize(("command", "allowed"), NESTED_CASES)
def test_nested_bash_tokens(tmp_path: Path, command: str, allowed: bool) -> None:
    assert (bash(scope_with(tmp_path, REPO_ROOTS), command) is None) is allowed


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
        ("ls *", True),
        ("ls ?", True),
        ("cat *.txt", True),
        ("ls .*", True),
        ("cat SRC/x", False),
        ("cat s*/x", False),
        ("cat src*", False),
        ("cat */x", False),
        ("cat ?rc/x", False),
        ("cat [s]rc", False),
        ("cat {,}src", False),
        ("cat {,}src/x", False),
        ("echo {1..3}", False),
        ("ls [a-z]*", False),
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
