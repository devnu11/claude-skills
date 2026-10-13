"""Which git segments a role's Bash may run, and where (s65).

A pure checker the guard feeds Bash links. It sees through ``X=1``, ``env``,
``command`` and friends (G3), works out the directory each git segment runs in
(G5) and looks the place up in ``GIT_RULES`` (G6). I/O only through
``paths.resolve_in``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from . import system
from .paths import resolve_in
from .refusal import Refusal, Rule
from .suite_check import ASSIGNMENT

SAFE_GIT = frozenset(
    {"status", "diff", "log", "show", "blame", "grep", "ls-files", "rev-parse", "describe"}
)
NO_COMMIT_FLAGS = frozenset({"-n", "--no-commit"})
CEILING_ENV = "GIT_CEILING_DIRECTORIES"
KEEP_CWD_ENV = "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR"
GIT_ENV_LOCKED = (
    CEILING_ENV,
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    KEEP_CWD_ENV,
)
CD_WORDS = frozenset({"cd", "pushd"})
AND = "&&"
UNSAFE_DIR_CHARS = ("$", "`", "~")
OUTSIDE_FLAGS = frozenset({"--global", "--system"})
SCP_LIKE = re.compile(r"^[^/:]+:")
PLACE_OPTIONS = frozenset({"-C"})
PATH_OPTIONS = frozenset({"--git-dir", "--work-tree"})
CONFIG_OPTIONS = frozenset({"-c"})
GIT_VALUE_OPTIONS = (
    PLACE_OPTIONS
    | PATH_OPTIONS
    | CONFIG_OPTIONS
    | frozenset({"--namespace", "--config-env", "--super-prefix", "--exec-path"})
)

GIT_WRITE_DENIED = Refusal(
    Rule.GIT_WRITE,
    "`git {first}` changes the repo, and the runner commits for you",
    "read-only git: `git status`, `git diff`, `git log`, `git show` and the other "
    "read-only subcommands",
).text()
GIT_OUTSIDE = Refusal(
    Rule.GIT_OUTSIDE,
    "{role} may not run `git {sub}` on {target}: in this step git works only "
    "inside {workspace}, and the team repo {repo} is the runner's",
    "`cd {workspace} && git …` or `git -C {workspace}/<dir> …`",
).text()
GIT_DIR_UNKNOWN = Refusal(
    Rule.GIT_UNKNOWN_DIR,
    "{role} may not run `git {sub}` where an earlier `cd` may not have run",
    "chain the `cd` with `&&`, or give git an absolute `-C` inside {workspace}",
).text()
GIT_ENV_DENIED = Refusal(
    Rule.GIT_ENV,
    "{role} may not set {name}: the runner sets git's environment for this step",
    "the same git command without setting {name}",
).text()


@dataclass(frozen=True)
class Wrapper:
    """A command that runs another: its value-taking options and leading operands (G3)."""

    values: frozenset[str] = frozenset()
    operands: int = 0


TIMEOUT = Wrapper(frozenset({"-s", "--signal", "-k", "--kill-after"}), 1)
WRAPPERS: dict[str, Wrapper] = {
    "env": Wrapper(frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"})),
    "command": Wrapper(),
    "builtin": Wrapper(),
    "nohup": Wrapper(),
    "exec": Wrapper(frozenset({"-a"})),
    "nice": Wrapper(frozenset({"-n", "--adjustment"})),
    "time": Wrapper(frozenset({"-f", "--format", "-o", "--output"})),
    "timeout": TIMEOUT,
    "gtimeout": TIMEOUT,
}
CHDIR_OPTIONS = frozenset({"-C", "--chdir"})
SPLIT_OPTIONS = frozenset({"-S", "--split-string"})


class Args(StrEnum):
    """Which words after a subcommand are paths (G5)."""

    ALL = "all"
    FIRST = "first"


PATH_ARGS: dict[str, Args] = {
    "init": Args.ALL,
    "clone": Args.ALL,
    "remote": Args.ALL,
    "config": Args.ALL,
    "submodule": Args.ALL,
    "worktree": Args.ALL,
    "push": Args.FIRST,
    "fetch": Args.FIRST,
    "pull": Args.FIRST,
}


class Where(StrEnum):
    """Where one git segment works (G5, G6)."""

    UNCONFINED = "unconfined"
    STEP_DIR = "step-dir"
    WORKSPACE = "workspace"
    ELSEWHERE = "elsewhere"
    UNKNOWN = "unknown"


class Allows(StrEnum):
    """Which subcommands a row lets through (G6)."""

    READ_ONLY = "read-only"
    ANY = "any"
    NONE = "none"


@dataclass(frozen=True)
class GitRule:
    """One row of GIT_RULES: what it allows and the reason when it does not."""

    allows: Allows
    reason: str


@dataclass(frozen=True)
class Link:
    """One Bash segment's words and the separator after it ("" at the end) (G5)."""

    words: tuple[str, ...]
    after: str


@dataclass(frozen=True)
class Stripped:
    """A segment's command words after G3, with env's ``-C`` directory if any."""

    words: tuple[str, ...]
    chdir: str | None = None


@dataclass(frozen=True)
class GitCall:
    """A parsed git segment (G5)."""

    words: tuple[str, ...]
    first: str
    sub: str
    places: tuple[str, ...]
    paths: tuple[str, ...]
    configs: tuple[str, ...]
    args: tuple[str, ...]
    outside: tuple[str, ...]

    @property
    def explicit(self) -> bool:
        """Whether the segment names a place, a git dir, a work tree or a config."""
        return bool(self.places or self.paths or self.configs)


@dataclass(frozen=True)
class Site:
    """A confined step's git context; all paths resolved (G1)."""

    role: str
    repo: Path
    step_dir: Path
    workspace: Path


NO_SITE = Site("", Path(), Path(), Path())


# ----- G3: prefixes ---------------------------------------------------------------


def strip_prefixes(words: Sequence[str]) -> Stripped:
    """The command words after assignments and WRAPPERS (G3)."""
    rest, chdir = tuple(words), None
    while rest:
        if ASSIGNMENT.match(rest[0]):
            rest = rest[1:]
        elif rest[0] in WRAPPERS:
            inner = _skip_wrapper(WRAPPERS[rest[0]], rest[1:])
            rest, chdir = inner.words, chdir or inner.chdir
        else:
            break
    return Stripped(rest, chdir)


def _skip_wrapper(wrapper: Wrapper, rest: tuple[str, ...]) -> Stripped:
    words, chdir = list(rest), None
    while words and (words[0].startswith("-") or ASSIGNMENT.match(words[0])):
        word = words.pop(0)
        if ASSIGNMENT.match(word):
            continue
        name, has_value, value = word.partition("=")
        if not has_value and name in wrapper.values and words:
            value = words.pop(0)
        chdir = value if name in CHDIR_OPTIONS else chdir
        if name in SPLIT_OPTIONS:
            words[:0] = value.split()
    del words[: _operands(wrapper, words)]
    return Stripped(tuple(words), chdir)


def _operands(wrapper: Wrapper, words: list[str]) -> int:
    return min(wrapper.operands, len(words))


def parse_git(stripped: Stripped) -> GitCall | None:
    """The git call in a stripped segment, or None when its command is not git (G3, G5)."""
    words = stripped.words
    if not words or PurePosixPath(words[0]).name != "git":
        return None
    options, sub, rest = _global_options(words[1:])
    args = _path_args(sub, rest)
    places = (*([stripped.chdir] if stripped.chdir else []), *options["-C"])
    configs = tuple(c.partition("=")[2] for c in options["-c"])
    paths = (*options["--git-dir"], *options["--work-tree"])
    outside = _outside(words, (*configs, *args))
    return GitCall(
        words, words[1] if len(words) > 1 else "", sub, places, paths, configs, args, outside
    )


def _global_options(words: Sequence[str]) -> tuple[dict[str, list[str]], str, list[str]]:
    """Git's global options by name, the subcommand, and the words after it."""
    found: dict[str, list[str]] = {name: [] for name in GIT_VALUE_OPTIONS}
    rest, i = list(words), 0
    while i < len(rest) and rest[i].startswith("-"):
        name, has_value, value = rest[i].partition("=")
        if not has_value and name in GIT_VALUE_OPTIONS:
            i, value = i + 1, rest[i + 1] if i + 1 < len(rest) else ""
        if name in GIT_VALUE_OPTIONS:
            found[name].append(value)
        i += 1
    return found, rest[i] if i < len(rest) else "", rest[i + 1 :]


def _path_args(sub: str, rest: list[str]) -> tuple[str, ...]:
    mode = PATH_ARGS.get(sub)
    plain = [w for w in rest if not w.startswith("-")]
    valued = [w.partition("=")[2] for w in rest if w.startswith("--") and "=" in w]
    if mode is Args.FIRST:
        return tuple(plain[:1])
    return (*plain, *valued) if mode is Args.ALL else ()


def _is_outside_word(word: str) -> bool:
    return "://" in word or word.startswith("!") or bool(SCP_LIKE.match(word))


def _outside(words: Sequence[str], candidates: Sequence[str]) -> tuple[str, ...]:
    flags = [w for w in words if w in OUTSIDE_FLAGS]
    return (*flags, *(c for c in candidates if _is_outside_word(c)))


# ----- G5: bases and places -------------------------------------------------------


def bases(links: Sequence[Link], start: Path) -> list[Path | None]:
    """The directory each link starts in; None once a moved cwd is uncertain (G5)."""
    out: list[Path | None] = []
    base: Path | None = start
    for link in links:
        out.append(base)
        base = _next_base(link, base, start)
    return out


def _next_base(link: Link, base: Path | None, start: Path) -> Path | None:
    moved = _after_cd(link.words, base)
    return moved if link.after == AND or moved == start else None


def _after_cd(words: tuple[str, ...], base: Path | None) -> Path | None:
    if not words or words[0] not in CD_WORDS:
        return base
    return _move(base, words[1]) if len(words) == 2 else None


def _move(base: Path | None, raw: str) -> Path | None:
    if raw.startswith("-") or any(c in raw for c in UNSAFE_DIR_CHARS):
        return None
    if base is None and not Path(raw).is_absolute():
        return None
    return resolve_in(base or Path("/"), raw)


def _inside(workspace: Path, path: Path) -> bool:
    return path == workspace or workspace in path.parents


def _directory(call: GitCall, base: Path | None) -> Path | None:
    for place in call.places:
        base = _move(base, place)
    return base


def _targets(call: GitCall, here: Path) -> list[Path]:
    named = (*call.paths, *call.configs, *call.args)
    return [here, *(resolve_in(here, w) for w in named if not _is_outside_word(w))]


def where(site: Site, call: GitCall, base: Path | None) -> tuple[Where, str]:
    """The call's Where and the target its denial names (G5)."""
    here = _directory(call, base)
    if here is None:
        return Where.UNKNOWN, ""
    if call.outside:
        return Where.ELSEWHERE, call.outside[0]
    outside = next((t for t in _targets(call, here) if not _inside(site.workspace, t)), None)
    if outside is None:
        return Where.WORKSPACE, ""
    kind = Where.STEP_DIR if here == site.step_dir and not call.explicit else Where.ELSEWHERE
    return kind, str(outside)


# ----- G6: the rule table ---------------------------------------------------------


def _read_only(call: GitCall) -> bool:
    if call.first in SAFE_GIT:
        return True
    return call.first == "cherry-pick" and bool(NO_COMMIT_FLAGS & set(call.words))


def _any(call: GitCall) -> bool:
    return True


def _none(call: GitCall) -> bool:
    return False


GIT_RULES: dict[Where, GitRule] = {
    Where.UNCONFINED: GitRule(Allows.READ_ONLY, GIT_WRITE_DENIED),
    Where.STEP_DIR: GitRule(Allows.READ_ONLY, GIT_OUTSIDE),
    Where.WORKSPACE: GitRule(Allows.ANY, ""),
    Where.ELSEWHERE: GitRule(Allows.NONE, GIT_OUTSIDE),
    Where.UNKNOWN: GitRule(Allows.NONE, GIT_DIR_UNKNOWN),
}
ALLOWS: dict[Allows, Callable[[GitCall], bool]] = {
    Allows.READ_ONLY: _read_only,
    Allows.ANY: _any,
    Allows.NONE: _none,
}


def git_denial(site: Site | None, links: Sequence[Link]) -> str | None:
    """The first reason to deny a git segment in ``links`` (G4-G7); ``site`` None = unconfined."""
    locked = _locked_mention(site, links)
    if locked:
        return locked
    starts = bases(links, site.step_dir) if site else [None] * len(links)
    reasons = (_link_denial(site, link, start) for link, start in zip(links, starts, strict=True))
    return next((r for r in reasons if r), None)


def _locked_mention(site: Site | None, links: Sequence[Link]) -> str | None:
    if site is None:
        return None
    words = [w for link in links for w in link.words]
    name = next((n for n in GIT_ENV_LOCKED if any(n in w for w in words)), None)
    return GIT_ENV_DENIED.format(role=site.role, name=name) if name else None


def _link_denial(site: Site | None, link: Link, start: Path | None) -> str | None:
    call = parse_git(strip_prefixes(link.words))
    if call is None:
        return None
    place, target = where(site, call, start) if site else (Where.UNCONFINED, "")
    rule = GIT_RULES[place]
    if ALLOWS[rule.allows](call):
        return None
    return rule.reason.format(**_fields(site or NO_SITE, call, target))


def _fields(site: Site, call: GitCall, target: str) -> dict[str, str]:
    return {
        "first": call.first,
        "sub": call.sub or call.first,
        "target": target,
        "role": site.role,
        "repo": str(site.repo),
        "workspace": str(site.workspace),
    }


def git_env(run_dir: Path) -> dict[str, str]:
    """The confined step's git environment (G2): ceiling at the resolved run dir, cwd kept."""
    return {CEILING_ENV: str(system.resolve(run_dir)), KEEP_CWD_ENV: "1"}
