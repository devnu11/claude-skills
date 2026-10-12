"""A tiny working tree and commit list behind the fake's ``git`` commands (s77, opt-in).

``FakeSystem.track()`` turns it on. From then on the git commands the runner uses
for its own bookkeeping (status, add, commit, revert, rev-parse HEAD, log, show,
check-ignore) answer from the fake's files: a file written through ``system`` shows
up in ``status`` until a commit takes it. Scripted ``fake.reply`` rules still win,
and every other git command gets the default (success, no output).

It is a test double, not git: it knows paths and whole-file contents, nothing else.
Real git behaviour is proved in ``tests/e2e/``.
"""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from .fake_system import FakeSystem

Tree = dict[str, bytes]
IGNORE_FILE = ".gitignore"
NO_CHANGE = "nothing to commit, working tree clean"


class Commit(NamedTuple):
    """One commit: its sha, message, and the tree before and after it."""

    sha: str
    message: str
    before: Tree
    after: Tree

    def paths(self) -> set[str]:
        """The paths this commit changed."""
        both = {*self.before, *self.after}
        return {p for p in both if self.before.get(p) != self.after.get(p)}

    def subject(self) -> str:
        """The first line of the message."""
        return self.message.splitlines()[0] if self.message else ""


class Reply(NamedTuple):
    """A git answer before it becomes a ``Done``."""

    code: int = 0
    out: str = ""
    err: str = ""


def _sha(number: int) -> str:
    return f"{0xFEED0000 + number:040x}"


def _subcommand(args: list[str]) -> tuple[str, list[str]]:
    """The git subcommand and its arguments, past any ``-c key=value`` options."""
    rest = list(args)
    while rest and rest[0] in ("-c", "-C"):
        del rest[:2]
    return (rest[0], rest[1:]) if rest else ("", [])


class FakeTree:
    """Files under the fake repo against the last commit, and the commits made."""

    def __init__(self, fake: FakeSystem, head: str) -> None:
        self.fake = fake
        self.root = str(fake.workdir)
        self.commits: list[Commit] = [Commit(head, "init", {}, self._working())]
        self.staged: set[str] = set()
        self.branch: str | None = "main"
        self.moves: list[str] = []

    # -- the trees ----------------------------------------------------------

    @property
    def head(self) -> str:
        """The sha of the last commit."""
        return self.commits[-1].sha

    @property
    def committed(self) -> Tree:
        """The tree of the last commit."""
        return self.commits[-1].after

    def _ignored(self, path: str) -> bool:
        key = posixpath.join(self.root, IGNORE_FILE)
        lines = self.fake.files.get(key, b"").decode().splitlines()
        rules = [line.strip().strip("/") for line in lines if line.strip()]
        return path.startswith(".git/") or any(
            path == rule or path.startswith(rule + "/") for rule in rules
        )

    def _working(self) -> Tree:
        prefix = self.root + "/"
        found = {k[len(prefix) :]: v for k, v in self.fake.files.items() if k.startswith(prefix)}
        return {p: v for p, v in found.items() if not self._ignored(p)}

    def _matching(self, specs: list[str], universe: set[str]) -> set[str]:
        def hit(path: str, spec: str) -> bool:
            return spec in (".", "") or path == spec or path.startswith(spec + "/")

        return {p for p in universe if any(hit(p, s) for s in specs)}

    # -- commands -------------------------------------------------------------

    def answer(self, args: list[str]) -> Reply | None:
        """The reply to ``git <args>`` for the commands modelled here, else ``None``."""
        name, rest = _subcommand(args)
        handler = getattr(self, f"_{name.replace('-', '_')}", None)
        return handler(rest) if handler else None

    def _status(self, rest: list[str]) -> Reply:
        working, committed = self._working(), self.committed
        entries = []
        for path in sorted(set(working) | set(committed)):
            if path not in committed:
                entries.append(f"?? {path}")
            elif path not in working:
                entries.append(f" D {path}")
            elif working[path] != committed[path]:
                entries.append(f" M {path}")
        sep = "\0" if "-z" in rest else "\n"
        return Reply(0, "".join(e + sep for e in entries))

    def _reset(self, rest: list[str]) -> Reply:
        self.staged = set()
        if "--hard" in rest:
            target = rest[-1]
            back = int(target.split("~")[1]) if "~" in target else 0
            self._reset_hard(back)
            self._moved(self.branch or "HEAD", f"reset {target}")
        return Reply()

    def _add(self, rest: list[str]) -> Reply:
        specs = rest[rest.index("--") + 1 :] if "--" in rest else ["."]
        universe = set(self._working()) | set(self.committed)
        self.staged |= self._matching(specs or ["."], universe)
        return Reply()

    def _message_of(self, rest: list[str]) -> str:
        for i, arg in enumerate(rest):
            if arg == "-m" or (
                arg.startswith("-") and not arg.startswith("--") and arg.endswith("m")
            ):
                return rest[i + 1]
        return ""

    def _commit(self, rest: list[str]) -> Reply:
        everything = any(a.startswith("-") and not a.startswith("--") and "a" in a for a in rest)
        working, before = self._working(), self.committed
        pending = set(working) | set(before) if everything else set(self.staged)
        after = dict(before)
        for path in pending:
            if path in working:
                after[path] = working[path]
            else:
                after.pop(path, None)
        if after == before:
            return Reply(1, NO_CHANGE)
        self.commits.append(Commit(_sha(len(self.commits)), self._message_of(rest), before, after))
        self.staged = set()
        return Reply(0, f"[main {self.head[:7]}] {self.commits[-1].subject()}\n")

    def _revert(self, rest: list[str]) -> Reply:
        target = self._find(rest[-1])
        if target is None:
            return Reply(128, "", f"fatal: bad revision '{rest[-1]}'")
        changed = target.paths()
        for path in changed:
            self._restore(path, target.before.get(path))
        self.staged |= changed
        return Reply()

    def _restore(self, path: str, data: bytes | None) -> None:
        key = posixpath.join(self.root, path)
        if data is None:
            self.fake.remove(Path(key))
        else:
            self.fake.put(Path(key), data)

    def _find(self, ref: str) -> Commit | None:
        if ref in ("HEAD", ""):
            return self.commits[-1]
        return next((c for c in self.commits if c.sha == ref or c.sha.startswith(ref)), None)

    def _symbolic_ref(self, rest: list[str]) -> Reply:
        return (
            Reply(0, self.branch + "\n")
            if self.branch
            else Reply(1, "", "fatal: ref HEAD is not a symbolic ref")
        )

    def _checkout(self, rest: list[str]) -> Reply:
        old = self.branch or self.head[:7]
        if "--detach" in rest:
            self.branch = None
            self._moved(old, self.head[:7])
        elif "-b" in rest:
            self.branch = rest[rest.index("-b") + 1]
            self._moved(old, self.branch)
        else:
            self.branch = rest[-1]
            self._moved(old, self.branch)
        return Reply()

    def _moved(self, old: str, new: str) -> None:
        self.moves.append(f"HEAD@{{{len(self.moves)}}} checkout: moving from {old} to {new}")

    def _git_dir(self) -> str:
        return posixpath.join(self.root, ".git")

    def _reset_hard(self, back: int) -> None:
        """Drop the last ``back`` commits and put their files back."""
        for _ in range(back):
            dropped = self.commits.pop()
            for path in dropped.paths():
                self._restore(path, dropped.before.get(path))

    def _rev_parse(self, rest: list[str]) -> Reply | None:
        if "--absolute-git-dir" in rest:
            return Reply(0, self._git_dir() + "\n")
        if rest[-1:] != ["HEAD"]:
            return None
        short = next((a for a in rest if a.startswith("--short")), None)
        width = int(short.split("=")[1]) if short and "=" in short else (7 if short else 40)
        return Reply(0, self.head[:width] + "\n")

    def _log(self, rest: list[str]) -> Reply:
        if "-g" in rest:
            return Reply(0, (self.moves[-1] if self.moves else "") + "\n")
        fmt = next((a.split("=", 1)[1] for a in rest if a.startswith("--format=")), "%s")
        count = next((int(a[1:]) for a in rest if a[1:].isdigit() and a[0] == "-"), None)
        named = [c for c in map(self._find, rest) if c is not None and rest[-1:] != ["HEAD"]]
        commits = named[:1] if named else list(reversed(self.commits))
        lines = [self._render(fmt, c) for c in commits[:count]]
        return Reply(0, "".join(lines))

    @staticmethod
    def _render(fmt: str, commit: Commit) -> str:
        shown = {"%B": commit.message.rstrip(), "%H": commit.sha}.get(fmt, commit.subject())
        return shown + "\n"

    def _show(self, rest: list[str]) -> Reply:
        if ":" in rest[-1]:
            return self._file_at(*rest[-1].split(":", 1))
        commit = self._find(rest[-1]) or self.commits[-1]
        return Reply(0, "".join(p + "\n" for p in sorted(commit.paths())))

    def _rev_list(self, rest: list[str]) -> Reply | None:
        span = rest[-1]
        if "--count" not in rest or ".." not in span:
            return None
        older, _, _ = span.partition("..")
        known = [c.sha for c in self.commits]
        start = known.index(self._find(older).sha) if self._find(older) else 0
        return Reply(0, f"{len(known) - start - 1}\n")

    def _file_at(self, ref: str, path: str) -> Reply:
        commit = self._find(ref)
        data = commit.after.get(path) if commit else None
        if data is None:
            return Reply(128, "", f"fatal: path '{path}' does not exist in '{ref}'")
        return Reply(0, data.decode())

    def _check_ignore(self, rest: list[str]) -> Reply:
        path = rest[-1]
        return Reply(0 if self._ignored(path) else 1)


def tree_reply(tree: FakeTree, args: list[str]) -> Any:
    """Adapter used by the fake: a ``Done`` for a modelled command, else ``None``."""
    from .fake_system import Done

    reply = tree.answer(args)
    return None if reply is None else Done(reply.code, reply.out, reply.err)
