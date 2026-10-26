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
from typing import NamedTuple

from . import system
from .paths import resolve_in
from .refusal import Refusal, Rule
from .suite_check import ASSIGNMENT

SAFE_GIT = frozenset(
    {
        "status", "diff", "log", "show", "blame", "grep", "ls-files", "rev-parse", "describe",
        "cat-file", "merge-base", "ls-tree", "rev-list", "name-rev",
    }
)  # fmt: skip
# Read-only only with this action right after the subcommand.
SAFE_GIT_ACTIONS = {"worktree": "list"}
# Global options that can make even a read-only subcommand run a program.
RUNS_PROGRAMS = frozenset({"--config-env", "--exec-path"})
LOCAL_GIT = SAFE_GIT | frozenset(
    {
        "add", "rm", "mv", "restore", "checkout", "switch", "rebase", "commit", "stash",
        "reset", "cherry-pick", "apply", "merge-file", "mergetool", "rerere", "merge-base",
        "rev-list", "cat-file", "ls-tree", "show-ref", "diff-files", "diff-index", "var",
    }
)  # fmt: skip
NO_COMMIT_FLAGS = frozenset({"-n", "--no-commit"})
LONG_PREFIX_MIN = 4
# A head that is on no branch, or that cannot be told: not valid ref names (``~``).
DETACHED = "~detached"
HEAD_UNKNOWN = "~unknown"
REBASE_OPERATIONS = frozenset(
    {"--continue", "--abort", "--skip", "--quit", "--edit-todo", "--show-current-patch"}
)  # fmt: skip
# Options git always gives a separate value (``-S``/``--gpg-sign`` take theirs attached only).
REBASE_VALUED_SHORT = frozenset({"-s", "-X", "-C", "-x"})
REBASE_VALUED_LONG = (
    "--onto",
    "--strategy",
    "--strategy-option",
    "--whitespace",
    "--empty",
    "--exec",
)
REBASE_UNCLEAR = "~unclear"
OTHER_REFS = "~other-refs"
UPDATE_REFS = ("--update-refs",)
ROOT_FLAGS = ("--root",)
BRANCH_ENV_LOCKED = ("GIT_CONFIG",)
DETACH_FLAGS = ("--detach",)


@dataclass(frozen=True)
class Flags:
    """Options a LOCAL step may not give a subcommand: long names (or their abbreviations,
    which git accepts) and short letters, alone or in a cluster such as ``-rx``."""

    long: tuple[str, ...]
    short: str = ""
    valued: str = ""


LOCAL_DENIED_FLAGS: dict[str, Flags] = {
    "rebase": Flags(("--exec", "--interactive"), "ix", "sSX"),
    "checkout": Flags(("--ignore-other-worktrees",)),
    "switch": Flags(("--ignore-other-worktrees",)),
}
CEILING_ENV = "GIT_CEILING_DIRECTORIES"
KEEP_CWD_ENV = "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR"
GIT_ENV_LOCKED = (
    CEILING_ENV,
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_SEQUENCE_EDITOR",
    "GIT_EDITOR",
    "GIT_EXTERNAL_DIFF",
    KEEP_CWD_ENV,
)
# A place the shell rewrites (home, a variable, a quoted word) cannot be checked.
SHELL_EXPANDED = ("~", "$", '"', "'")
# Options that make a read-only subcommand write a file or run a program.
WRITING_OPTIONS = frozenset({"--output", "--ext-diff"})
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
GIT_LOCAL_DENIED = Refusal(
    Rule.GIT_LOCAL,
    "{role} may not run `git {sub}` in {workspace}: this worktree shares the team repo's "
    "remotes, refs and config, so its git stays local, and only the runner pushes or fetches",
    "local git in {workspace}: `git add`, `git rebase --continue`, `git status`, `git diff`, "
    "`git log`, `git checkout -- <file>`",
).text()
GIT_OWN_BRANCH_DENIED = Refusal(
    Rule.GIT_OWN_BRANCH,
    "{role} may not run `git {sub}` in {workspace}: it would move {moved}, and this step may "
    "move only its own branch {branch}",
    "`git checkout -B {branch}`, `git reset` and `git rebase` while HEAD is on {branch}, "
    "`git rebase --continue`, `git add`, `git checkout -- <file>`",
).text()
GIT_HEAD_UNKNOWN_DENIED = Refusal(
    Rule.GIT_OWN_BRANCH,
    "{role} may not run `git {sub}` in {workspace}: an earlier `git checkout` or `git switch` "
    "in this command may have left HEAD on a branch other than {branch}, the only one this "
    "step may move",
    "the `git {sub}` in its own command, once HEAD is on {branch}",
).text()
GIT_REBASE_UNCLEAR_DENIED = Refusal(
    Rule.GIT_OWN_BRANCH,
    "{role} may not run `git rebase` in {workspace}: it could move more than one branch "
    "(HEAD's and the one it names), and this step may move only {branch}",
    "`git rebase <onto>` while HEAD is on {branch}, or `git rebase <onto> {branch}` with "
    "HEAD on {branch} or detached",
).text()
GIT_OTHER_REFS_DENIED = Refusal(
    Rule.GIT_OWN_BRANCH,
    "{role} may not run `git {sub}` in {workspace}: `--update-refs` or a `-c` setting can "
    "move branches other than {branch}, the only one this step may move",
    "the same git command without `--update-refs` or `-c`",
).text()
GIT_ELSEWHERE = Refusal(
    Rule.GIT_OUTSIDE,
    "`git {sub}` may not name {place}: outside a confined step git works only in {repo}",
    "`git -C <dir inside the repo> …`, or plain `git …` from the repo",
).text()
GIT_EXTERNAL_DIFF_DENIED = Refusal(
    Rule.GIT_ENV,
    "Bash may not set GIT_EXTERNAL_DIFF: it makes read-only git run a program",
    "the same git command without GIT_EXTERNAL_DIFF",
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
    LOCAL = "local"
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
    workspace_allows: Allows = Allows.ANY
    branch: str = ""  # the one branch the step may move; "" = no branch check (s176)
    head: str = DETACHED  # the branch HEAD is on when the command starts


class Position(NamedTuple):
    """Where a link starts: its directory and the branch HEAD is on (s176)."""

    base: Path | None
    head: str


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


# ----- s176: which branch a call moves ---------------------------------------------


@dataclass(frozen=True)
class Create:
    """The options that make checkout or switch create (or reset) a branch."""

    short: str
    long: tuple[str, ...]


CREATES = {
    "checkout": Create("Bb", ("--orphan",)),
    "switch": Create("Cc", ("--create", "--force-create", "--orphan")),
}


def _list_args_after_sub(call: GitCall) -> list[str]:
    return list(call.words[call.words.index(call.sub) + 1 :])


def _is_long(word: str, names: Sequence[str]) -> bool:
    name = word.partition("=")[0]
    return len(name) >= LONG_PREFIX_MIN and any(n.startswith(name) for n in names)


def _read_value_at(rest: list[str], i: int) -> str:
    """The value of the option at ``rest[i]``: after ``=`` or the next word."""
    word = rest[i]
    if word.startswith("--") and "=" in word:
        return word.partition("=")[2]
    return rest[i + 1] if i + 1 < len(rest) else ""


def _find_short_create(word: str, letters: str) -> str | None:
    """The branch a short cluster such as ``-fB``, ``-Bname`` creates, ``""`` if unnamed."""
    cut = next((i for i, c in enumerate(word[1:]) if c in letters), None)
    return None if cut is None else word[cut + 2 :]


def _find_created(call: GitCall) -> str | None:
    """The branch ``checkout``/``switch`` creates or resets, or None."""
    spec, rest = CREATES[call.sub], _list_args_after_sub(call)
    for i, word in enumerate(rest):
        if word == "--":
            return None
        if word.startswith("--"):
            found = _read_value_at(rest, i) if _is_long(word, spec.long) else None
        elif word.startswith("-"):
            attached = _find_short_create(word, spec.short)
            found = None if attached is None else attached or _read_value_at(rest, i)
        else:
            continue
        if found is not None:
            return found
    return None


def _moves_by_checkout(call: GitCall, head: str) -> str:
    return _find_created(call) or DETACHED


def _moves_head(call: GitCall, head: str) -> str:
    return head


def _moves_by_rebase(call: GitCall, head: str) -> str:
    """The branch ``git rebase`` moves: HEAD's and any operand after the upstream (R1)."""
    rest = _list_args_after_sub(call)
    if REBASE_OPERATIONS & set(rest):
        return DETACHED
    operands = _split_rebase_operands(rest)
    start = 0 if any(_is_long(w, ROOT_FLAGS) for w in rest) else 1
    return _find_rebase_branch([*operands[start:], head])


def _find_rebase_branch(candidates: list[str]) -> str:
    """The one branch among ``candidates``, DETACHED for none, REBASE_UNCLEAR for several."""
    named = {c for c in candidates if c != DETACHED}
    if len(named) > 1:
        return REBASE_UNCLEAR
    return next(iter(named), DETACHED)


def _is_rebase_valued(word: str) -> bool:
    """Whether git always reads the word after ``word`` as its value."""
    return word in REBASE_VALUED_SHORT or ("=" not in word and _is_long(word, REBASE_VALUED_LONG))


def _split_rebase_operands(rest: list[str]) -> list[str]:
    out, skip = [], False
    for word in rest:
        if skip or not word.startswith("-"):
            out += [] if skip else [word]
        skip = not skip and _is_rebase_valued(word)
    return out


def _moves_by_stash(call: GitCall, head: str) -> str:
    rest = _list_args_after_sub(call)
    return rest[1] if rest[:1] == ["branch"] and len(rest) > 1 else DETACHED


def _moves_none(call: GitCall, head: str) -> str:
    return DETACHED


BRANCH_MOVES: dict[str, Callable[[GitCall, str], str]] = {
    "checkout": _moves_by_checkout,
    "switch": _moves_by_checkout,
    "reset": _moves_head,
    "commit": _moves_head,
    "cherry-pick": _moves_head,
    "rebase": _moves_by_rebase,
    "stash": _moves_by_stash,
}


def find_moved_branch(call: GitCall, head: str) -> str:
    """The local branch ``call`` moves: ``head`` if it moves the current one, else DETACHED."""
    if call.configs or _updates_refs(call):
        return OTHER_REFS
    return BRANCH_MOVES.get(call.sub, _moves_none)(call, head)


def _updates_refs(call: GitCall) -> bool:
    """Whether a ``rebase`` asks to move the other branches that point into it (R2)."""
    return call.sub == "rebase" and any(_is_long(w, UPDATE_REFS) for w in call.words)


def get_next_head(call: GitCall, head: str) -> str:
    """The branch HEAD is on after ``call``; HEAD_UNKNOWN when a checkout leaves it unclear."""
    if call.sub not in CREATES:
        return head
    rest = _list_args_after_sub(call)
    if created := _find_created(call):
        return created
    if "-d" in rest or any(_is_long(w, DETACH_FLAGS) for w in rest):
        return DETACHED
    return _find_plain_next_head(rest, head)


def _find_plain_next_head(rest: list[str], head: str) -> str:
    """HEAD after a checkout/switch that creates nothing: ``-`` or a bare ``<b> --`` is unclear."""
    before, after = _split_dashes(rest)
    named = [w for w in before if w == "-" or not w.startswith("-")]
    if after or not named:
        return head
    return HEAD_UNKNOWN


def _split_dashes(rest: list[str]) -> tuple[list[str], list[str]]:
    """``rest`` split at the first ``--`` into the words before and after it."""
    if "--" not in rest:
        return rest, []
    i = rest.index("--")
    return rest[:i], rest[i + 1 :]


def _is_own_or_detached(site: Site, branch: str) -> bool:
    return branch in (DETACHED, site.branch)


def find_branch_denial(site: Site, call: GitCall, head: str) -> str | None:
    """The refusal when ``call`` would move a branch other than the site's own (s176)."""
    moved = find_moved_branch(call, head)
    if _is_own_or_detached(site, moved):
        return None
    template = BRANCH_DENIALS.get(moved, GIT_OWN_BRANCH_DENIED)
    fields = _fields(site, call, "") | {"moved": f"branch {moved}", "branch": site.branch}
    return template.format(**fields)


BRANCH_DENIALS = {
    HEAD_UNKNOWN: GIT_HEAD_UNKNOWN_DENIED,
    REBASE_UNCLEAR: GIT_REBASE_UNCLEAR_DENIED,
    OTHER_REFS: GIT_OTHER_REFS_DENIED,
}


# ----- G6: the rule table ---------------------------------------------------------


def _read_only(call: GitCall) -> bool:
    """Read-only by the subcommand, past global options such as ``-C`` (#61)."""
    unsafe = RUNS_PROGRAMS | WRITING_OPTIONS
    if call.configs or any(w.partition("=")[0] in unsafe for w in call.words):
        return False
    if call.sub in SAFE_GIT or _is_safe_action(call):
        return True
    return call.sub == "cherry-pick" and bool(NO_COMMIT_FLAGS & set(call.words))


def _is_safe_action(call: GitCall) -> bool:
    action = SAFE_GIT_ACTIONS.get(call.sub)
    after = call.words[call.words.index(call.sub) + 1 :] if action else ()
    return after[:1] == (action,)


def _is_local(call: GitCall) -> bool:
    flags = LOCAL_DENIED_FLAGS.get(call.sub)
    denied = flags is not None and any(_is_denied_flag(w, flags) for w in call.words)
    return call.sub in LOCAL_GIT and not denied


def _is_denied_flag(word: str, flags: Flags) -> bool:
    if word.startswith("--"):
        name = word.partition("=")[0]
        return len(name) >= LONG_PREFIX_MIN and any(f.startswith(name) for f in flags.long)
    return word.startswith("-") and bool(set(_read_cluster(word, flags)) & set(flags.short))


def _read_cluster(word: str, flags: Flags) -> str:
    """A short-option cluster's letters, up to the first one that takes a value."""
    letters = word[1:]
    cut = next((i for i, c in enumerate(letters) if c in flags.valued), len(letters))
    return letters[:cut]


def _any(call: GitCall) -> bool:
    return True


def _none(call: GitCall) -> bool:
    return False


GIT_RULES: dict[Where, GitRule] = {
    Where.UNCONFINED: GitRule(Allows.READ_ONLY, GIT_WRITE_DENIED),
    Where.STEP_DIR: GitRule(Allows.READ_ONLY, GIT_OUTSIDE),
    Where.WORKSPACE: GitRule(Allows.ANY, GIT_LOCAL_DENIED),
    Where.ELSEWHERE: GitRule(Allows.NONE, GIT_OUTSIDE),
    Where.UNKNOWN: GitRule(Allows.NONE, GIT_DIR_UNKNOWN),
}
ALLOWS: dict[Allows, Callable[[GitCall], bool]] = {
    Allows.READ_ONLY: _read_only,
    Allows.LOCAL: _is_local,
    Allows.ANY: _any,
    Allows.NONE: _none,
}


def git_denial(site: Site | None, links: Sequence[Link]) -> str | None:
    """The first reason to deny a git segment in ``links`` (G4-G7); ``site`` None = unconfined."""
    locked = _locked_mention(site, links)
    if locked:
        return locked
    spots = _list_positions(site, links)
    reasons = (_link_denial(site, link, spot) for link, spot in zip(links, spots, strict=True))
    return next((r for r in reasons if r), None)


def _list_positions(site: Site | None, links: Sequence[Link]) -> list[Position]:
    """Each link's start directory and the branch HEAD is on there (G5, s176)."""
    starts = bases(links, site.step_dir) if site else [None] * len(links)
    heads, head = [], site.head if site else DETACHED
    for link in links:
        heads.append(head)
        call = parse_git(strip_prefixes(link.words))
        if call and (site is None or _is_own_or_detached(site, head)):
            head = get_next_head(call, head)
    return [Position(b, h) for b, h in zip(starts, heads, strict=True)]


def find_unconfined_place_denial(repo: Path, links: Sequence[Link]) -> str | None:
    """Deny an unconfined step's git aimed outside ``repo`` by -C, --git-dir or --work-tree."""
    if any("GIT_EXTERNAL_DIFF" in w for link in links for w in link.words):
        return GIT_EXTERNAL_DIFF_DENIED
    calls = [c for c in (parse_git(strip_prefixes(link.words)) for link in links) if c]
    found = ((c, p) for c in calls for p in (*c.places, *c.paths) if _leaves(repo, p))
    hit = next(found, None)
    return GIT_ELSEWHERE.format(sub=hit[0].sub, place=hit[1], repo=repo) if hit else None


def _leaves(repo: Path, raw: str) -> bool:
    """``raw`` climbs, is expanded by the shell, or names an absolute place outside ``repo``."""
    if raw.startswith(SHELL_EXPANDED) or ".." in PurePosixPath(raw).parts:
        return True
    return Path(raw).is_absolute() and not _inside(repo, resolve_in(repo, raw))


def _locked_mention(site: Site | None, links: Sequence[Link]) -> str | None:
    if site is None:
        return None
    words = [w for link in links for w in link.words]
    locked = GIT_ENV_LOCKED + (BRANCH_ENV_LOCKED if site.branch else ())
    name = next((n for n in locked if any(n in w for w in words)), None)
    return GIT_ENV_DENIED.format(role=site.role, name=name) if name else None


def _link_denial(site: Site | None, link: Link, spot: Position) -> str | None:
    call = parse_git(strip_prefixes(link.words))
    if call is None:
        return None
    place, target = where(site, call, spot.base) if site else (Where.UNCONFINED, "")
    rule = _find_rule(site, place)
    if ALLOWS[rule.allows](call):
        return find_branch_denial(site, call, spot.head) if _guards_branch(site, rule) else None
    return rule.reason.format(**_fields(site or NO_SITE, call, target))


def _guards_branch(site: Site | None, rule: GitRule) -> bool:
    return site is not None and bool(site.branch) and rule.allows is Allows.LOCAL


def _find_rule(site: Site | None, place: Where) -> GitRule:
    """The ``GIT_RULES`` row; in the workspace, what the site lets through there."""
    rule = GIT_RULES[place]
    if site is None or place is not Where.WORKSPACE:
        return rule
    return GitRule(site.workspace_allows, rule.reason)


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
