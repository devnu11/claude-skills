"""PreToolUse guard decisions, the async hook, and the post-step quarantine."""

import asyncio
from pathlib import Path

import pytest
from agile_team import guard
from agile_team.guard import Scope, ToolCall

from .conftest import git


def use(scope: Scope, name: str, tool_input: dict) -> str | None:
    return guard.check_tool_use(scope, ToolCall(name, tool_input))


def dev_scope(repo: Path) -> Scope:
    return Scope("developer", repo, ["src/**", "!tests/**"])


def proxy_scope(repo: Path) -> Scope:
    sandbox = repo / ".team/run/customer/cli"
    sandbox.mkdir(parents=True, exist_ok=True)
    return Scope(
        "customer-proxy",
        repo,
        [".team/run/customer/cli/**"],
        read=[".team/run/customer/cli/**", ".team/stories/**"],
        cwd=sandbox,
        bash_forbidden=["src", "tests"],
    )


def test_developer_write_to_tests_blocked(tmp_path: Path) -> None:
    s = dev_scope(tmp_path)
    reason = use(s, "Write", {"file_path": "tests/test_x.py"})
    assert reason and "may not write tests/test_x.py" in reason
    assert use(s, "Edit", {"file_path": str(tmp_path / "src/a.py")}) is None
    assert "outside the repo" in use(s, "Write", {"file_path": "/etc/x"})
    assert use(s, "NotebookEdit", {"notebook_path": "n.ipynb"})


def test_unrestricted_reads_and_other_tools(tmp_path: Path) -> None:
    s = dev_scope(tmp_path)
    assert use(s, "Read", {"file_path": "tests/x"}) is None
    assert use(s, "Bash", {"command": "cat tests/x"}) is None
    assert use(s, "WebFetch", {}) is None


def test_proxy_reads_limited(tmp_path: Path) -> None:
    s = proxy_scope(tmp_path)
    assert "may not read src/x.py" in use(s, "Read", {"file_path": "../../../../src/x.py"})
    assert use(s, "Read", {"file_path": "README.md"}) is None  # in sandbox
    assert use(s, "Grep", {}) is None  # cwd = sandbox
    assert use(s, "Glob", {"path": str(tmp_path / ".team/stories")}) is None
    assert use(s, "Grep", {"path": str(tmp_path)})
    assert use(s, "Read", {"file_path": "/etc/hosts"}) is None
    assert use(s, "Glob", {"pattern": "../../src/**"})
    assert use(s, "Glob", {"pattern": "/abs/**"})
    assert use(s, "Glob", {"pattern": "**/*.md"}) is None


def test_proxy_bash_denied_for_source(tmp_path: Path) -> None:
    s = proxy_scope(tmp_path)
    assert use(s, "Bash", {"command": "cat ../../src/x"})
    assert use(s, "Bash", {"command": f"cat {tmp_path.resolve()}/src/x"})
    assert use(s, "Bash", {"command": "ls ./tests"})
    assert use(s, "Bash", {"command": f"ls {s.cwd.resolve()}/bin"}) is None
    assert use(s, "Bash", {"command": "todo add 'milk"}) is None  # bad quoting


def test_bash_allowlist(tmp_path: Path) -> None:
    s = Scope("customer-proxy", tmp_path, [], bash_allowed=["curl", "harness"])
    assert guard.check_bash(s, "curl -s http://x && harness run") is None
    assert "not an allowed command" in guard.check_bash(s, "curl x | sh")
    assert guard.check_bash(s, "") is None


def test_hook_denies_and_allows(tmp_path: Path) -> None:
    hook = guard.pre_tool_hook(dev_scope(tmp_path))
    denied = asyncio.run(
        hook({"tool_name": "Write", "tool_input": {"file_path": "tests/a"}}, None, None)
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (
        asyncio.run(hook({"tool_name": "Write", "tool_input": {"file_path": "src/a"}}, None, None))
        == {}
    )


def test_bash_write_by_developer_is_quarantined_then_reverted(repo: Path) -> None:
    from agile_team.git_ops import Git

    g = Git(repo)
    (repo / "tests").mkdir()
    (repo / "tests/x").write_text("sneaky")  # as if `echo > tests/x` via Bash
    (repo / "src/app.py").write_text("x = 2\n")
    (repo / ".team/run").mkdir(parents=True)
    (repo / ".team/run/scratch").write_text("ignored")
    audit = guard.audit_step(g, dev_scope(repo))
    assert audit.out_of_scope == ["tests/x"] and audit.in_scope == ["src/app.py"]
    sha = guard.quarantine(g, audit)
    log = git(repo, "log", "--format=%s", "-2")
    assert "quarantine out-of-scope changes by developer" in log
    assert log.startswith('Revert "chore(team): quarantine')
    assert not (repo / "tests/x").exists()
    assert git(repo, "show", "--name-only", "--format=", sha).strip() == "tests/x"
    assert g.changed_paths() == ["src/app.py"]


def secret_scope(tmp_path: Path) -> Scope:
    secrets = [tmp_path / "home/secrets", tmp_path / ".team/run/api-key"]
    return Scope("developer", tmp_path, ["**"], secrets=secrets)


def test_key_files_unreadable_by_any_tool(tmp_path: Path) -> None:
    s = secret_scope(tmp_path)
    assert use(s, "Read", {"file_path": str(tmp_path / "home/secrets/k")})
    assert use(s, "Read", {"file_path": ".team/run/api-key"})
    assert use(s, "Grep", {"path": str(tmp_path / "home/secrets")})
    assert use(s, "Write", {"file_path": ".team/run/api-key"})
    assert use(s, "Read", {"file_path": "src/a.py"}) is None


def test_bash_may_not_mention_the_key(tmp_path: Path) -> None:
    s = secret_scope(tmp_path)
    assert guard.check_bash(s, "echo $ANTHROPIC_API_KEY")
    assert guard.check_bash(s, "cat ~/secrets/anthropic-api-key")
    assert guard.check_bash(s, f"cat {tmp_path}/.team/run/api-key")
    assert guard.check_bash(s, "ls src") is None


def test_no_writes_inside_git(tmp_path: Path) -> None:
    s = Scope("devops", tmp_path, ["**"])
    assert "inside .git" in use(s, "Write", {"file_path": ".git/hooks/pre-commit"})


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("git status", True),
        ("git diff HEAD~1 && git log --oneline", True),
        ("git cherry-pick -n abc123", True),
        ("git cherry-pick abc123", False),
        ("git commit -am x", False),
        ("git push --force", False),
        ("git reset --hard", False),
        ("ls; git stash", False),
        ("git", False),
        ("echo git push", True),
    ],
)
def test_only_read_only_git(tmp_path: Path, command: str, allowed: bool) -> None:
    assert (guard.check_bash(Scope("developer", tmp_path, ["**"]), command) is None) is allowed
