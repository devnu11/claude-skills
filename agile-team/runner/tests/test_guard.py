"""PreToolUse guard decisions, the async hook, and the post-step quarantine."""

import asyncio
from pathlib import Path

import pytest
from agile_team import guard, system
from agile_team.guard import Scope, ToolCall

from .fake_system import FAKE_HEAD, Done, FakeSystem


def use(scope: Scope, name: str, tool_input: dict) -> str | None:
    return guard.check_tool_use(scope, ToolCall(name, tool_input))


def dev_scope(repo: Path) -> Scope:
    return Scope("developer", repo, ["src/**", "!tests/**"])


def proxy_scope(repo: Path) -> Scope:
    sandbox = repo / ".team/run/customer/cli"
    system.make_dirs(sandbox)
    return Scope(
        "customer-proxy",
        repo,
        [".team/run/customer/cli/**"],
        read=[".team/run/customer/cli/**", ".team/stories/**"],
        cwd=sandbox,
        bash_forbidden=["src", "tests"],
    )


def test_developer_write_to_tests_blocked(repo: Path) -> None:
    s = dev_scope(repo)
    reason = use(s, "Write", {"file_path": "tests/test_x.py"})
    assert reason and "may not write tests/test_x.py" in reason
    assert use(s, "Edit", {"file_path": str(repo / "src/a.py")}) is None
    assert "outside the repo" in use(s, "Write", {"file_path": "/etc/x"})
    assert use(s, "NotebookEdit", {"notebook_path": "n.ipynb"})


def test_unrestricted_reads_and_other_tools(repo: Path) -> None:
    s = dev_scope(repo)
    assert use(s, "Read", {"file_path": "tests/x"}) is None
    assert use(s, "Bash", {"command": "cat tests/x"}) is None
    assert use(s, "WebFetch", {}) is None


def test_proxy_reads_limited(repo: Path) -> None:
    s = proxy_scope(repo)
    assert "may not read src/x.py" in use(s, "Read", {"file_path": "../../../../src/x.py"})
    assert use(s, "Read", {"file_path": "README.md"}) is None  # in sandbox
    assert use(s, "Grep", {}) is None  # cwd = sandbox
    assert use(s, "Glob", {"path": str(repo / ".team/stories")}) is None
    assert use(s, "Grep", {"path": str(repo)})
    assert use(s, "Read", {"file_path": "/etc/hosts"}) is None
    assert use(s, "Glob", {"pattern": "../../src/**"})
    assert use(s, "Glob", {"pattern": "/abs/**"})
    assert use(s, "Glob", {"pattern": "**/*.md"}) is None


def test_proxy_bash_denied_for_source(repo: Path) -> None:
    s = proxy_scope(repo)
    assert use(s, "Bash", {"command": "cat ../../src/x"})
    assert use(s, "Bash", {"command": f"cat {system.resolve(repo)}/src/x"})
    assert use(s, "Bash", {"command": "ls ./tests"})
    assert use(s, "Bash", {"command": f"ls {system.resolve(s.cwd)}/bin"}) is None
    assert use(s, "Bash", {"command": "todo add 'milk"}) is None  # bad quoting


def test_bash_allowlist(repo: Path) -> None:
    s = Scope("customer-proxy", repo, [], bash_allowed=["curl", "harness"])
    assert guard.check_bash(s, "curl -s http://x && harness run") is None
    assert "is not on this step's command list" in guard.check_bash(s, "curl x | sh")
    assert guard.check_bash(s, "") is None


def test_hook_denies_and_allows(repo: Path) -> None:
    hook = guard.pre_tool_hook(dev_scope(repo))
    denied = asyncio.run(
        hook({"tool_name": "Write", "tool_input": {"file_path": "tests/a"}}, None, None)
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (
        asyncio.run(hook({"tool_name": "Write", "tool_input": {"file_path": "src/a"}}, None, None))
        == {}
    )


def test_bash_write_by_developer_is_quarantined_then_reverted(repo: Path, fake: FakeSystem) -> None:
    from agile_team.git_ops import Git

    g = Git(repo)
    fake.reply(("git", "status"), Done(0, "?? tests/x\0 M src/app.py\0"))
    fake.reply(
        ("git", "log"), Done(0, "chore(team): quarantine out-of-scope changes by developer\n")
    )
    audit = guard.audit_step(g, dev_scope(repo))
    assert audit.out_of_scope == ["tests/x"] and audit.in_scope == ["src/app.py"]
    sha = guard.quarantine(g, audit)
    assert sha == FAKE_HEAD
    argvs = [c.argv for c in fake.commands]
    (add,) = [a for a in argvs if "add" in a]
    assert add[-1] == "tests/x" and "src/app.py" not in add
    (commit,) = [a for a in argvs if "commit" in a and "-m" in a and "Revert" not in a[-1]]
    assert "quarantine out-of-scope changes by developer" in commit[-1]
    assert ("git", "revert", "--no-commit", FAKE_HEAD) in argvs
    assert g.changed_paths() == ["tests/x", "src/app.py"]  # git's own answer is scripted


def secret_scope(repo: Path) -> Scope:
    secrets = [repo / "home/secrets", repo / ".team/run/api-key"]
    return Scope("developer", repo, ["**"], secrets=secrets)


def test_key_files_unreadable_by_any_tool(repo: Path) -> None:
    s = secret_scope(repo)
    assert use(s, "Read", {"file_path": str(repo / "home/secrets/k")})
    assert use(s, "Read", {"file_path": ".team/run/api-key"})
    assert use(s, "Grep", {"path": str(repo / "home/secrets")})
    assert use(s, "Write", {"file_path": ".team/run/api-key"})
    assert use(s, "Read", {"file_path": "src/a.py"}) is None


def test_bash_may_not_mention_the_key(repo: Path) -> None:
    s = secret_scope(repo)
    assert guard.check_bash(s, "echo $ANTHROPIC_API_KEY")
    assert guard.check_bash(s, "cat ~/secrets/anthropic-api-key")
    assert guard.check_bash(s, f"cat {repo}/.team/run/api-key")
    assert guard.check_bash(s, "ls src") is None


def test_no_writes_inside_git(repo: Path) -> None:
    s = Scope("devops", repo, ["**"])
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
def test_only_read_only_git(repo: Path, command: str, allowed: bool) -> None:
    assert (guard.check_bash(Scope("developer", repo, ["**"]), command) is None) is allowed


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("g\\\nit commit -m x", False),
        ("git \\\ncommit -m x", False),
        ("git pu\\\nsh", False),
        ("git st\\\natus", True),
        ("git \\\nstatus", True),
    ],
)
def test_line_continuation_joined_for_git(repo: Path, command: str, allowed: bool) -> None:
    """W0: every role's git check sees the command the shell runs."""
    assert (guard.check_bash(Scope("developer", repo, ["**"]), command) is None) is allowed


def test_line_continuation_joined_for_key_name(repo: Path) -> None:
    s = secret_scope(repo)
    assert guard.check_bash(s, "echo ANTHROPIC_API_\\\nKEY")
    assert guard.check_bash(s, "echo $ANTHROPIC_API_\\\nKEY")
    assert guard.check_bash(s, "echo hello\\\n world") is None


def test_line_continuation_through_check_tool_use(repo: Path) -> None:
    s = dev_scope(repo)
    assert use(s, "Bash", {"command": "g\\\nit commit -m x"})
    assert use(s, "Bash", {"command": "echo ANTHROPIC_API_\\\nKEY"})
    assert use(s, "Bash", {"command": "git st\\\natus"}) is None


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("echo hi \\\\\ngit commit -m x", False),  # run of 2: even, newline kept
        ("echo hi \\\\\\\\\ngit commit -m x", False),  # run of 4: even, newline kept
        ("echo hi \\\\\\\ngit commit -m x", True),  # run of 3: odd, joined into one echo
    ],
)
def test_even_backslash_run_is_not_a_continuation(repo: Path, command: str, allowed: bool) -> None:
    """W0 (review D3): only a newline after an odd run of backslashes is joined."""
    assert (use(dev_scope(repo), "Bash", {"command": command}) is None) is allowed


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("echo hi # note \\\ngit commit -m x", False),  # D4: comment ends in `\`, not joined
        ("echo hi # x \\\ng\\\nit commit -m x", False),  # D5: continuation after the comment
        ("# \\\ng\\\nit commit -m x", False),
        ("echo a \\\nb \\\n# c \\\ng\\\nit commit", False),  # joins before the comment line
        ("# c \\\necho '#'; \\\ng\\\nit commit", False),  # real comment plus a fake `#`
        ("echo a#b \\\ngit status", True),  # mid-word `#` is no comment
        ("echo a#b \\\ng\\\nit status", True),
        ("git status # done \\", True),
        ("g\\\nit commit -m x # done \\", False),
    ],
)
def test_comment_aware_continuation(repo: Path, command: str, allowed: bool) -> None:
    """D4/D5: a `#` comment ending in `\\` is not a continuation, whatever follows it."""
    assert (use(dev_scope(repo), "Bash", {"command": command}) is None) is allowed


# ----- a story worktree step (s159 B3) and the main checkout's run dir -----


def worktree_scope(repo: Path) -> Scope:
    """An integration-tester step in s1's worktree; the presentation is in ``repo``'s run dir."""
    worktree = repo / ".team/run/worktrees/s1"
    scope = Scope("integration-tester", worktree, ["tests/e2e/**", ".team/run/presentation/**"])
    scope.run_home = repo
    return scope


def test_a_worktree_step_writes_the_main_run_dir_within_its_globs(repo: Path) -> None:
    s = worktree_scope(repo)
    guide = repo / ".team/run/presentation/s1/cli/PRESENTATION.md"
    assert s.relative(str(guide)) == ".team/run/presentation/s1/cli/PRESENTATION.md"
    assert use(s, "Write", {"file_path": str(guide)}) is None
    assert use(s, "Write", {"file_path": "tests/e2e/test_s1.py"}) is None
    assert "may not write .team/run/state.json" in use(
        s, "Write", {"file_path": str(repo / ".team/run/state.json")}
    )


def test_a_worktree_step_may_not_write_the_main_checkout_outside_its_run_dir(repo: Path) -> None:
    s = worktree_scope(repo)
    for path in ("src/a.py", ".team/acceptance/s1.md", "tests/e2e/test_s1.py"):
        assert "outside the repo" in use(s, "Write", {"file_path": str(repo / path)})
    assert s.relative(str(repo / "src/a.py")) is None


def test_without_a_run_home_the_main_run_dir_is_outside_the_repo(repo: Path) -> None:
    s = Scope("integration-tester", repo / ".team/run/worktrees/s1", [".team/run/presentation/**"])
    guide = repo / ".team/run/presentation/s1/cli/PRESENTATION.md"
    assert "outside the repo" in use(s, "Write", {"file_path": str(guide)})
