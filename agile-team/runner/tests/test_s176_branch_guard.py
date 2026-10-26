"""s176: a story rebase step's git may move only its own rebase branch (the guard side)."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import git_check, guard, system
from agile_team.git_check import Allows, Site
from agile_team.guard import Scope

from .fake_system import Done, FakeSystem

BRANCH = "team/story-s1-r1"
OTHER = "team/story-s2"
DETACHED = git_check.DETACHED
UNKNOWN = git_check.HEAD_UNKNOWN


def parsed(command: str) -> git_check.GitCall:
    call = git_check.parse_git(git_check.strip_prefixes(command.split()))
    assert call is not None
    return call


def site_at(repo: Path, head: str, branch: str = BRANCH) -> Site:
    ws = repo / "ws"
    system.make_dirs(ws)
    root, work = system.resolve(repo), system.resolve(ws)
    return Site("developer-cli", root, work, work, Allows.LOCAL, branch=branch, head=head)


def denial(repo: Path, command: str, head: str = BRANCH, branch: str = BRANCH) -> str | None:
    return git_check.git_denial(site_at(repo, head, branch), guard._links(command))


# ----- find_moved_branch (B3) -----------------------------------------------------

HEAD = "cur"


@pytest.mark.parametrize(
    ("command", "moved"),
    [
        ("git checkout -B other", "other"),
        ("git checkout -Bother", "other"),
        ("git checkout -fB other", "other"),
        ("git checkout -b new", "new"),
        ("git checkout --orphan o", "o"),
        ("git checkout other", DETACHED),
        ("git checkout -- f", DETACHED),
        ("git checkout HEAD -- f", DETACHED),
        ("git switch -C other", "other"),
        ("git switch -c n", "n"),
        ("git switch --force-c other", "other"),
        ("git switch --create=other", "other"),
        ("git switch --orphan o", "o"),
        ("git switch other", DETACHED),
        ("git reset --hard X", HEAD),
        ("git reset -- f", HEAD),
        ("git commit -m x", HEAD),
        ("git cherry-pick X", HEAD),
        ("git rebase --continue", DETACHED),
        ("git rebase --abort", DETACHED),
        ("git rebase --skip", DETACHED),
        ("git rebase --quit", DETACHED),
        ("git rebase --edit-todo", DETACHED),
        ("git rebase --show-current-patch", DETACHED),
        ("git rebase main", HEAD),
        ("git rebase main other", git_check.REBASE_UNCLEAR),
        ("git rebase --onto main base other", git_check.REBASE_UNCLEAR),
        ("git rebase --root other", git_check.REBASE_UNCLEAR),
        ("git rebase --root", HEAD),
        ("git rebase -s ours main other", git_check.REBASE_UNCLEAR),
        ("git stash branch other", "other"),
        ("git stash", DETACHED),
        ("git stash push -m x", DETACHED),
        ("git stash list", DETACHED),
        ("git status", DETACHED),
        ("git add f", DETACHED),
        ("git log", DETACHED),
    ],
)
def test_find_moved_branch_names_the_branch_a_call_moves(command: str, moved: str) -> None:
    assert git_check.find_moved_branch(parsed(command), HEAD) == moved


@pytest.mark.parametrize(
    "command",
    [
        "git rebase main other",
        "git rebase --onto main base other",
        "git rebase --root other",
        "git rebase -s ours main other",
    ],
)
def test_find_moved_branch_names_the_rebase_branch_when_head_is_detached(command: str) -> None:
    assert git_check.find_moved_branch(parsed(command), DETACHED) == "other"


def test_branch_moves_is_a_table_keyed_by_subcommand() -> None:
    subs = {"checkout", "switch", "reset", "commit", "cherry-pick", "rebase", "stash"}
    assert subs <= set(git_check.BRANCH_MOVES)


# ----- get_next_head (B4) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "after"),
    [
        ("git checkout -B n", "n"),
        ("git switch -c n", "n"),
        ("git checkout --detach", DETACHED),
        ("git switch -d", DETACHED),
        ("git switch --detach other", DETACHED),
        ("git checkout -- f", HEAD),
        ("git checkout HEAD -- f", HEAD),
        ("git checkout", HEAD),
        ("git checkout other", UNKNOWN),
        ("git switch other", UNKNOWN),
        ("git checkout -", UNKNOWN),
        ("git switch -", UNKNOWN),
        ("git checkout other --", UNKNOWN),
        ("git checkout -f other", UNKNOWN),
        ("git reset --hard X", HEAD),
        ("git rebase main", HEAD),
        ("git status", HEAD),
    ],
)
def test_get_next_head_follows_checkout_and_switch_only(command: str, after: str) -> None:
    assert git_check.get_next_head(parsed(command), HEAD) == after


# ----- AC1: refused ---------------------------------------------------------------

REFUSED = [
    "git checkout -B other",
    "git checkout -Bother",
    "git checkout -fB other",
    "git checkout -b new",
    "git switch -C other",
    "git switch --force-c other",
    "git switch --create=other",
    "git rebase main other",
    "git rebase --onto main base other",
    "git rebase --root other",
    "git stash branch other",
]


@pytest.mark.parametrize("command", REFUSED)
def test_a_call_moving_another_branch_is_refused_naming_the_own_branch(
    repo: Path, command: str
) -> None:
    reason = denial(repo, command)
    assert reason and BRANCH in reason


@pytest.mark.parametrize(
    "command", ["git reset --hard X", "git rebase main", "git commit -m x", "git cherry-pick X"]
)
@pytest.mark.parametrize("head", [OTHER, UNKNOWN])
def test_a_head_move_while_on_another_branch_is_refused(
    repo: Path, command: str, head: str
) -> None:
    reason = denial(repo, command, head=head)
    assert reason and BRANCH in reason


def test_a_checkout_in_the_same_command_makes_a_later_reset_refused(repo: Path) -> None:
    assert denial(repo, "git checkout other && git reset --hard X")


def test_a_detach_in_the_same_command_makes_a_later_reset_allowed(repo: Path) -> None:
    assert denial(repo, "git checkout --detach && git reset --hard X") is None


def test_the_refusal_for_an_unknown_head_says_where_it_came_from(repo: Path) -> None:
    reason = denial(repo, "git checkout other && git reset --hard X")
    assert reason and "git checkout" in reason and "git switch" in reason


# ----- AC2: still allowed ---------------------------------------------------------

ALLOWED = [
    "git rebase --continue",
    "git rebase --abort",
    "git rebase --skip",
    "git add f",
    "git checkout -- f",
    "git checkout HEAD -- f",
    "git reset --hard X",
    "git reset -- f",
    f"git checkout -B {BRANCH} X",
    f"git checkout -B {BRANCH}",
    "git checkout other",
    "git status",
    "git log",
    "git diff",
]


@pytest.mark.parametrize("command", ALLOWED)
@pytest.mark.parametrize("head", [BRANCH, DETACHED])
def test_the_commands_the_rebase_needs_still_run(repo: Path, command: str, head: str) -> None:
    assert denial(repo, command, head=head) is None


def test_rebase_continue_runs_even_with_head_on_another_branch(repo: Path) -> None:
    assert denial(repo, "git rebase --continue", head=OTHER) is None


def test_a_site_with_no_branch_gets_no_branch_check(repo: Path) -> None:
    assert denial(repo, "git checkout -B other", head=OTHER, branch="") is None


# ----- through the guard: rule names and the HEAD read (B2) ----------------------


def scope_of(repo: Path, **kw: object) -> Scope:
    ws = repo / "ws"
    system.make_dirs(ws)
    return Scope(
        "developer-cli",
        repo,
        ["**"],
        cwd=ws,
        git_workspace=system.resolve(ws),
        git_allows=Allows.LOCAL,
        **kw,  # type: ignore[arg-type]
    )


def test_the_guard_refuses_another_branch_under_the_own_branch_rule(
    repo: Path, fake: FakeSystem
) -> None:
    fake.reply(("symbolic-ref",), Done(0, BRANCH + "\n"))
    reason = guard.check_bash(scope_of(repo, git_branch=BRANCH), "git checkout -B other")
    assert reason and "git-own-branch" in reason and BRANCH in reason


@pytest.mark.parametrize(
    "command",
    [
        "git branch -f other X",
        "git update-ref refs/heads/other X",
        "git symbolic-ref HEAD refs/heads/other",
    ],
)
def test_branch_update_ref_and_symbolic_ref_stay_refused_as_local_only(
    repo: Path, fake: FakeSystem, command: str
) -> None:
    fake.reply(("symbolic-ref",), Done(0, BRANCH + "\n"))
    reason = guard.check_bash(scope_of(repo, git_branch=BRANCH), command)
    assert reason and "git-local-only" in reason


def test_the_site_reads_head_only_when_the_scope_has_a_branch(repo: Path, fake: FakeSystem) -> None:
    site = guard._site(scope_of(repo))
    assert site is not None and site.branch == "" and site.head == DETACHED
    assert not [c for c in fake.commands if "symbolic-ref" in c.argv]


def test_the_site_carries_the_branch_and_head_of_a_branch_scope(
    repo: Path, fake: FakeSystem
) -> None:
    fake.reply(("symbolic-ref",), Done(0, OTHER + "\n"))
    site = guard._site(scope_of(repo, git_branch=BRANCH))
    assert site is not None and site.branch == BRANCH and site.head == OTHER


@pytest.mark.parametrize(
    ("done", "head"),
    [(Done(0, OTHER + "\n"), OTHER), (Done(1, ""), DETACHED), (Done(128, "", "fatal"), UNKNOWN)],
    ids=["branch", "detached", "unknown"],
)
def test_read_head_branch_maps_the_exit_code(repo: Path, fake: FakeSystem, done, head) -> None:
    fake.reply(("symbolic-ref",), done)
    assert guard._read_head_branch(repo) == head
    asked = [c.argv for c in fake.commands if "symbolic-ref" in c.argv]
    assert asked and "-q" in asked[0] and "--short" in asked[0] and "HEAD" in asked[0]
