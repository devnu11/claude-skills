"""Hard enforcement of each role's file scope.

Layers:

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
from .paths import could_climb, matches, reaches, repo_relative, resolve_in

WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path"}
READ_TOOLS = {"Read": "file_path", "Grep": "path", "Glob": "path"}
PATH_KEYS = {**WRITE_TOOLS, **READ_TOOLS}
ALWAYS_IGNORED = [".team/run/**"]
PROTECTED = [".git", ".git/**"]
SAFE_GIT = frozenset(
    {"status", "diff", "log", "show", "blame", "grep", "ls-files", "rev-parse", "describe"}
)
NO_COMMIT_FLAGS = frozenset({"-n", "--no-commit"})
SECRET_WORDS = ("ANTHROPIC_API_KEY", "anthropic-api-key")
QUARANTINE = "chore(team): quarantine out-of-scope changes by {role}"
LINE_CONTINUATION = "\\\n"
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|&\n]")
UNQUOTE = str.maketrans("", "", "'\"\\")

# The SDK fixes the hook signature at (input, tool_use_id, context).
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

    @property
    def base(self) -> Path:
        """Directory relative paths resolve from: the step's cwd, else the repo."""
        return self.cwd or self.repo

    @property
    def reads_everything(self) -> bool:
        """True when the scope places no restriction on reads."""
        return self.read == ["**"]

    def relative(self, raw: str) -> str | None:
        """``raw`` resolved from the step's cwd, relative to the repo (``None`` if outside)."""
        return repo_relative(self.repo, resolve_in(self.base, raw))

    def is_secret(self, raw: str) -> bool:
        """True when ``raw`` resolves to, or into, one of the secret paths."""
        path = resolve_in(self.base, raw)
        return any(path == s.resolve() or s.resolve() in path.parents for s in self.secrets)


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation as the hook sees it."""

    name: str
    input: dict[str, Any]

    @property
    def path(self) -> str:
        """The path argument of this call, or ``""`` when the tool has none."""
        return self.input.get(PATH_KEYS.get(self.name, ""), "") or ""


def check_tool_use(scope: Scope, call: ToolCall) -> str | None:
    """Reason to deny this tool call, or ``None`` to allow it."""
    return _check_secret_path(scope, call) or _check_by_tool(scope, call)


def _check_secret_path(scope: Scope, call: ToolCall) -> str | None:
    if call.path and scope.is_secret(call.path):
        return f"{scope.role} may not access {call.path}"
    return None


def _check_by_tool(scope: Scope, call: ToolCall) -> str | None:
    if call.name in WRITE_TOOLS:
        return _check_write(scope, call.path)
    if call.name in READ_TOOLS:
        return _check_read(scope, call.path or ".") or _check_pattern(scope, call)
    if call.name == "Bash":
        return check_bash(scope, call.input.get("command", ""))
    return None


def _check_write(scope: Scope, raw: str) -> str | None:
    rel = scope.relative(raw)
    if rel is None:
        return f"{scope.role} may not write outside the repo ({raw})"
    if matches(rel, PROTECTED):
        return f"{scope.role} may not write inside .git"
    if not matches(rel, scope.write):
        return f"{scope.role} may not write {rel}; allowed: {', '.join(scope.write) or 'nothing'}"
    return None


def _check_read(scope: Scope, raw: str) -> str | None:
    rel = scope.relative(raw)
    if rel is None or scope.reads_everything:
        return None
    probe = "" if rel == "." else rel
    if matches(probe, scope.read) or matches(f"{probe}/x".lstrip("/"), scope.read):
        return None
    return f"{scope.role} may not read {rel}"


def _check_pattern(scope: Scope, call: ToolCall) -> str | None:
    """A restricted reader's Glob pattern may not climb out with ``..`` or go absolute."""
    pattern = call.input.get("pattern", "") if call.name == "Glob" else ""
    if scope.reads_everything or not pattern:
        return None
    if pattern.startswith("/") or ".." in pattern.split("/"):
        return f"{scope.role} may not glob {pattern}"
    return None


def check_bash(scope: Scope, command: str) -> str | None:
    """Deny key mentions, write-side git, commands off the allowlist and forbidden paths.

    Checks run after joining ``\\``-newline line continuations as the shell does.
    """
    command = command.replace(LINE_CONTINUATION, "")
    segments = [_tokens(s) for s in _SEGMENT_SPLIT.split(command)]
    checks = (
        lambda: _check_secret_mention(scope, command),
        lambda: _check_git(segments),
        lambda: _check_allowlist(scope, segments),
        lambda: _check_tokens(scope, _tokens(command)),
    )
    return next((reason for reason in (c() for c in checks) if reason), None)


def _check_secret_mention(scope: Scope, command: str) -> str | None:
    needles = [*SECRET_WORDS, *(str(s) for s in scope.secrets)]
    hit = next((n for n in needles if n in command), None)
    return f"{scope.role} may not reference the API key ({hit})" if hit else None


def _check_git(segments: list[list[str]]) -> str | None:
    """Only read-only git subcommands (and ``cherry-pick -n``) are allowed."""
    for words in segments:
        sub = words[1] if len(words) > 1 else ""
        if words[:1] == ["git"] and not _git_allowed(sub, words):
            return f"`git {sub}` is not allowed; the runner commits for you"
    return None


def _git_allowed(sub: str, words: list[str]) -> bool:
    return sub in SAFE_GIT or (sub == "cherry-pick" and bool(NO_COMMIT_FLAGS & set(words)))


def _check_allowlist(scope: Scope, segments: list[list[str]]) -> str | None:
    if scope.bash_allowed is None:
        return None
    bad = next((w[0] for w in segments if w and w[0] not in scope.bash_allowed), None)
    allowed = ", ".join(scope.bash_allowed)
    return f"`{bad}` is not an allowed command; allowed: {allowed}" if bad else None


def _check_tokens(scope: Scope, tokens: list[str]) -> str | None:
    bad = next((t for t in tokens if _token_forbidden(scope, t)), None)
    return f"{scope.role} may not reference {bad!r} from Bash" if bad else None


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return [w.translate(UNQUOTE) for w in command.split()]


def _token_forbidden(scope: Scope, token: str) -> bool:
    """For a sandboxed role: climbing up, naming the repo, or naming a source root."""
    if not scope.bash_forbidden:
        return False
    return could_climb(token) or _names_repo(scope, token) or _names_forbidden_root(scope, token)


def _names_repo(scope: Scope, token: str) -> bool:
    in_sandbox = bool(scope.cwd) and token.startswith(str(scope.base.resolve()))
    return token.startswith(str(scope.repo.resolve())) and not in_sandbox


def _names_forbidden_root(scope: Scope, token: str) -> bool:
    return any(reaches(token, root) for root in scope.bash_forbidden)


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
        call = ToolCall(input_data.get("tool_name", ""), input_data.get("tool_input", {}))
        reason = check_tool_use(scope, call)
        return deny(reason) if reason else {}

    return hook


@dataclass
class Audit:
    """Changed paths after a step, split by whether the role may write them."""

    role: str
    in_scope: list[str]
    out_of_scope: list[str]


def audit_step(git: Git, scope: Scope) -> Audit:
    """Split the tree's changes into in-scope and out-of-scope paths."""
    changed = [p for p in git.changed_paths() if not matches(p, ALWAYS_IGNORED)]
    return Audit(
        role=scope.role,
        in_scope=[p for p in changed if matches(p, scope.write)],
        out_of_scope=[p for p in changed if not matches(p, scope.write)],
    )


def quarantine(git: Git, audit: Audit) -> str:
    """Commit the out-of-scope paths alone, revert that commit, return its sha."""
    sha = git.commit(audit.out_of_scope, QUARANTINE.format(role=audit.role))
    git.revert(sha)
    return sha
