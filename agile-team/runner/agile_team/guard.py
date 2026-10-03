"""Hard enforcement of each role's file scope.

Two layers:

* ``pre_tool_hook`` — an Agent SDK PreToolUse hook that denies Write/Edit/
  NotebookEdit outside the acting role's write globs, Read/Grep/Glob outside
  its read globs, and (for sandboxed roles) Bash commands that name source
  paths or fall outside an allowlist.
* Every role: no writes under ``.git/``, no tool or Bash access to the API key
  files, and Bash may only run read-only git subcommands (the runner owns
  commits, so a role cannot rewrite history or hide changes from the audit).
* ``audit_step`` / ``quarantine`` — after every step the runner diffs the tree.
  Bash cannot be path-guarded, so out-of-scope changes are committed on their
  own and immediately reverted: the work stays in history, the tree stays clean
  and the Product Owner gets the sha.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .git_ops import Git
from .paths import matches, repo_relative

WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path"}
READ_TOOLS = {"Read": "file_path", "Grep": "path", "Glob": "path"}
ALWAYS_IGNORED = (".team/run/**",)
PROTECTED = (".git", ".git/**")
SAFE_GIT = frozenset(
    {"status", "diff", "log", "show", "blame", "grep", "ls-files", "rev-parse", "describe"}
)
SECRET_WORDS = ("ANTHROPIC_API_KEY", "anthropic-api-key")
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|&\n]")

Hook = Callable[[dict[str, Any], str | None, Any], Awaitable[dict[str, Any]]]


@dataclass
class Scope:
    """What one role step may touch. Globs are repo-relative, already expanded."""

    role: str
    repo: Path
    write: list[str]
    read: list[str] = field(default_factory=lambda: ["**"])
    cwd: Path | None = None
    bash_forbidden: list[str] = field(default_factory=list)
    bash_allowed: list[str] | None = None
    secrets: list[Path] = field(default_factory=list)

    def allows_write(self, rel: str) -> bool:
        return matches(rel, self.write)

    def allows_read(self, rel: str) -> bool:
        return matches(rel, self.read)


def check_tool_use(scope: Scope, tool: str, tool_input: dict[str, Any]) -> str | None:
    """Reason to deny this tool call, or ``None`` to allow it."""
    raw = tool_input.get({**WRITE_TOOLS, **READ_TOOLS}.get(tool, ""), "") or ""
    if raw and _is_secret(scope, raw):
        return f"{scope.role} may not access {raw}"
    if tool in WRITE_TOOLS:
        return _check_write(scope, tool_input.get(WRITE_TOOLS[tool], ""))
    if tool in READ_TOOLS:
        return _check_read(scope, tool_input.get(READ_TOOLS[tool]) or ".") or _check_pattern(
            scope, tool_input.get("pattern", "") if tool == "Glob" else ""
        )
    if tool == "Bash":
        return check_bash(scope, tool_input.get("command", ""))
    return None


def _check_write(scope: Scope, raw: str) -> str | None:
    rel = repo_relative(scope.repo, raw, scope.cwd)
    if rel is None:
        return f"{scope.role} may not write outside the repo ({raw})"
    if matches(rel, list(PROTECTED)):
        return f"{scope.role} may not write inside .git"
    if not scope.allows_write(rel):
        return f"{scope.role} may not write {rel}; allowed: {', '.join(scope.write) or 'nothing'}"
    return None


def _check_read(scope: Scope, raw: str) -> str | None:
    rel = repo_relative(scope.repo, raw, scope.cwd)
    if rel is None or scope.read == ["**"]:
        return None
    probe = rel if rel != "." else ""
    if scope.allows_read(probe) or scope.allows_read(f"{probe}/x".lstrip("/")):
        return None
    return f"{scope.role} may not read {rel}"


def _is_secret(scope: Scope, raw: str) -> bool:
    """True when ``raw`` resolves to, or into, one of the scope's secret paths."""
    base = scope.cwd or scope.repo
    path = Path(raw).expanduser()
    resolved = (path if path.is_absolute() else base / path).resolve()
    return any(resolved == s.resolve() or s.resolve() in resolved.parents for s in scope.secrets)


def _check_pattern(scope: Scope, pattern: str) -> str | None:
    """A restricted reader's Glob pattern may not climb out with ``..`` or go absolute."""
    if scope.read == ["**"] or not pattern:
        return None
    if pattern.startswith("/") or ".." in pattern.split("/"):
        return f"{scope.role} may not glob {pattern}"
    return None


def check_bash(scope: Scope, command: str) -> str | None:
    """Deny commands outside the allowlist or that mention forbidden paths."""
    reason = _check_secret_mention(scope, command) or _check_git(command)
    if reason:
        return reason
    if scope.bash_allowed is not None:
        reason = _check_allowlist(command, scope.bash_allowed)
        if reason:
            return reason
    for token in _tokens(command):
        if _token_forbidden(scope, token):
            return f"{scope.role} may not reference {token!r} from Bash"
    return None


def _check_secret_mention(scope: Scope, command: str) -> str | None:
    needles = [*SECRET_WORDS, *(str(s) for s in scope.secrets)]
    hit = next((n for n in needles if n in command), None)
    return f"{scope.role} may not reference the API key ({hit})" if hit else None


def _check_git(command: str) -> str | None:
    """Only read-only git subcommands (and ``cherry-pick -n``) are allowed."""
    for segment in _SEGMENT_SPLIT.split(command):
        words = _tokens(segment)
        if not words or words[0] != "git":
            continue
        sub = words[1] if len(words) > 1 else ""
        no_commit = sub == "cherry-pick" and ({"-n", "--no-commit"} & set(words))
        if sub not in SAFE_GIT and not no_commit:
            return f"`git {sub}` is not allowed; the runner commits for you"
    return None


def _check_allowlist(command: str, allowed: list[str]) -> str | None:
    for segment in _SEGMENT_SPLIT.split(command):
        words = _tokens(segment)
        if words and words[0] not in allowed:
            return f"`{words[0]}` is not an allowed command; allowed: {', '.join(allowed)}"
    return None


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _token_forbidden(scope: Scope, token: str) -> bool:
    if not scope.bash_forbidden:
        return False
    if ".." in token.split("/"):
        return True
    repo = str(scope.repo.resolve())
    sandbox = str(scope.cwd.resolve()) if scope.cwd else None
    if token.startswith(repo) and not (sandbox and token.startswith(sandbox)):
        return True
    head = token.lstrip("./").split("/", 1)[0]
    return bool(head) and head in scope.bash_forbidden


def deny(reason: str) -> dict[str, Any]:
    """PreToolUse hook output that blocks the call with ``reason``."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def pre_tool_hook(scope: Scope) -> Hook:
    """An SDK PreToolUse hook bound to ``scope``."""

    async def hook(input_data: dict[str, Any], _tool_use_id: str | None, _ctx: Any) -> dict:
        reason = check_tool_use(
            scope, input_data.get("tool_name", ""), input_data.get("tool_input", {})
        )
        return deny(reason) if reason else {}

    return hook


@dataclass
class Audit:
    """Changed paths after a step, split by whether the role may write them."""

    in_scope: list[str]
    out_of_scope: list[str]


def audit_step(git: Git, scope: Scope) -> Audit:
    """Split the tree's changes into in-scope and out-of-scope paths."""
    changed = [p for p in git.changed_paths() if not matches(p, list(ALWAYS_IGNORED))]
    return Audit(
        in_scope=[p for p in changed if scope.allows_write(p)],
        out_of_scope=[p for p in changed if not scope.allows_write(p)],
    )


def quarantine(git: Git, role: str, paths: list[str]) -> str:
    """Commit ``paths`` alone, revert that commit, return the quarantine sha."""
    sha = git.commit(paths, f"chore(team): quarantine out-of-scope changes by {role}")
    git.revert(sha, f'Revert "chore(team): quarantine out-of-scope changes by {role}"')
    return sha
