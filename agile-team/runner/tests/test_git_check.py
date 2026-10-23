"""s65: which git segments a role's Bash may run, and where (rules G1-G8)."""

from pathlib import Path

import pytest
from agile_team import git_check, guard, system
from agile_team.git_check import Link, Site, Where
from agile_team.guard import Scope

WORKSPACE_PARTS = ".team/run/presentation/s1/workspace"


@pytest.fixture
def ws(repo: Path) -> Path:
    path = repo / WORKSPACE_PARTS
    system.make_dirs(path)
    return path


def confined(repo: Path, ws: Path, role: str = "integration-tester") -> Scope:
    return Scope(role, repo, ["**"], git_workspace=system.resolve(ws))


def unconfined(repo: Path) -> Scope:
    return Scope("developer", repo, ["src/**"])


def denial(scope: Scope, command: str) -> str | None:
    return guard.check_bash(scope, command)


# ----- G3 / AC10: prefixes are seen through, every role ------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m x",
        "X=1 git commit -m x",
        "env git commit -m x",
        "command git commit -m x",
        "env -i A=1 git commit -m x",
        "timeout 5 git commit -m x",
        "/usr/bin/git commit -m x",
        "nohup git commit -m x",
        "env -S 'git commit -m x'",
        "true && X=1 env command git commit",
    ],
)
def test_prefixed_git_commit_is_denied_like_git_commit(repo: Path, command: str) -> None:
    reason = denial(unconfined(repo), command)
    assert reason and "`git commit` changes the repo, and the runner commits for you" in reason


def test_write_denied_text_names_its_rule() -> None:
    assert git_check.GIT_WRITE_DENIED.startswith("refused by rule `git-write`: ")
    assert "`git {first}` changes the repo, and the runner commits for you" in (
        git_check.GIT_WRITE_DENIED
    )


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "X=1 git log",
        "env git diff",
        "git cherry-pick -n abc",
        "git cherry-pick --no-commit a",
        "git -C x status",
        "git --git-dir x/.git --work-tree x log",
        "git -C x cherry-pick -n abc",
        "git cat-file -p HEAD",
        "git merge-base HEAD main",
        "git ls-tree HEAD",
        "git rev-list HEAD",
        "git name-rev HEAD",
        "git worktree list --porcelain",
    ],
)
def test_unconfined_read_only_git_is_allowed(repo: Path, command: str) -> None:
    assert denial(unconfined(repo), command) is None


@pytest.mark.parametrize(
    "command",
    [
        "git cherry-pick abc",
        "git",
        "git -C x commit -m y",
        "git -c core.fsmonitor=evil status",
        "git --config-env=core.pager=X log",
        "git --exec-path=/x status",
        "git worktree add list",
        "git -C list worktree add x",
    ],
)
def test_unconfined_other_git_is_denied(repo: Path, command: str) -> None:
    assert denial(unconfined(repo), command)


@pytest.mark.parametrize(
    ("command", "rule"),
    [
        ("git -C /other/repo log", "git-outside-workspace"),
        ("git --git-dir=/other/.git log", "git-outside-workspace"),
        ("git --git-dir /other/.git log", "git-outside-workspace"),
        ("git --work-tree=/other status", "git-outside-workspace"),
        ("git -C ../sibling status", "git-outside-workspace"),
        ("git -C src/../../up status", "git-outside-workspace"),
        ("env -C /other git status", "git-outside-workspace"),
        ("git log --output=/tmp/x", "git-write"),
        ("git diff --output /tmp/x", "git-write"),
        ("git diff --ext-diff", "git-write"),
        ("GIT_EXTERNAL_DIFF=evil git diff", "git-env"),
        ("git -C ~ status", "git-outside-workspace"),
        ("git -C ~/src log", "git-outside-workspace"),
        ('git -C "$HOME" status', "git-outside-workspace"),
        ("git -C $PWD status", "git-outside-workspace"),
        ("git --git-dir=$GIT_X log", "git-outside-workspace"),
        ("git --work-tree='$X' status", "git-outside-workspace"),
    ],
)
def test_unconfined_git_aimed_outside_the_repo_or_writing_is_denied(
    repo: Path, command: str, rule: str
) -> None:
    reason = denial(unconfined(repo), command)
    assert reason and f"`{rule}`" in reason


@pytest.mark.parametrize(
    "command",
    [
        "git -C src status",
        'git -C "src" status',
        "git -C {repo}/src log",
        "git --git-dir={repo}/.git log",
        "git diff",
    ],
)
def test_unconfined_git_inside_the_repo_is_allowed(repo: Path, command: str) -> None:
    assert denial(unconfined(repo), command.format(repo=system.resolve(repo))) is None


def test_unconfined_non_git_is_untouched(repo: Path) -> None:
    assert denial(unconfined(repo), "env FOO=1 ls") is None
    assert denial(unconfined(repo), "echo git commit") is None


def test_strip_prefixes_keeps_env_chdir() -> None:
    stripped = git_check.strip_prefixes(["X=1", "env", "-C", "/r", "git", "status"])
    assert (stripped.words, stripped.chdir) == (("git", "status"), "/r")
    split = git_check.strip_prefixes(["env", "--split-string=git log"])
    assert split.words == ("git", "log")


def test_parse_git_reads_places_paths_and_configs() -> None:
    stripped = git_check.strip_prefixes(
        ["git", "-C", "a", "--git-dir", "g", "-c", "core.worktree=/w", "-C", "b", "log"]
    )
    call = git_check.parse_git(stripped)
    assert call is not None
    assert (call.first, call.sub, call.places) == ("-C", "log", ("a", "b"))
    assert (call.paths, call.configs, call.explicit) == (("g",), ("/w",), True)


def test_parse_git_none_for_other_commands_and_bare_git() -> None:
    assert git_check.parse_git(git_check.strip_prefixes(["ls"])) is None
    call = git_check.parse_git(git_check.strip_prefixes(["git"]))
    assert call is not None and (call.first, call.sub) == ("", "")


# ----- G5: bases ---------------------------------------------------------------------


def links(command: str) -> list[Link]:
    return guard._links(command)


def test_links_pair_segments_with_separators() -> None:
    got = links("cd x && git a; git b | c")
    assert [(link.words, link.after) for link in got] == [
        (("cd", "x"), "&&"),
        (("git", "a"), ";"),
        (("git", "b"), "|"),
        (("c",), ""),
    ]


def test_bases_follow_cd_chained_with_and(repo: Path, ws: Path) -> None:
    start = system.resolve(repo)
    got = git_check.bases(links(f"cd {ws} && git x"), start)
    assert got == [start, system.resolve(ws)]


@pytest.mark.parametrize(
    "command",
    [
        "cd ws; git x",
        "cd ws && ls; git x",
        "cd $HOME && git x",
        "cd ~/x && git x",
        "cd -P ws && git x",
        "cd `pwd` && git x",
    ],
)
def test_bases_unknown_after_uncertain_cd(repo: Path, command: str) -> None:
    start = system.resolve(repo)
    assert git_check.bases(links(command), start)[-1] is None


def test_bases_unmoved_carry_through_any_separator(repo: Path) -> None:
    start = system.resolve(repo)
    assert git_check.bases(links("git x; git y"), start) == [start, start]


def test_subshell_cd_does_not_move_the_base(repo: Path) -> None:
    start = system.resolve(repo)
    assert git_check.bases(links("(cd ws) && git x"), start)[-1] == start


# ----- G5 / G6: where and the rule table ---------------------------------------------


def test_rule_table_has_a_row_per_place() -> None:
    assert set(git_check.GIT_RULES) == set(Where)
    assert git_check.GIT_RULES[Where.WORKSPACE].allows is git_check.Allows.ANY
    assert git_check.GIT_RULES[Where.UNKNOWN].allows is git_check.Allows.NONE
    assert git_check.GIT_RULES[Where.ELSEWHERE].allows is git_check.Allows.NONE
    assert git_check.GIT_RULES[Where.STEP_DIR].allows is git_check.Allows.READ_ONLY
    assert set(git_check.ALLOWS) == set(git_check.Allows)


def site_of(repo: Path, ws: Path) -> Site:
    root = system.resolve(repo)
    return Site("integration-tester", root, root, system.resolve(ws))


def where_of(repo: Path, ws: Path, command: str, base: Path | None = None) -> Where:
    stripped = git_check.strip_prefixes(command.split())
    call = git_check.parse_git(stripped)
    assert call is not None
    start = system.resolve(ws) if base is None else base
    return git_check.where(site_of(repo, ws), call, start)[0]


@pytest.mark.parametrize(
    "command",
    [
        "git init demo",
        "git commit -m x",
        "git -C demo status",
        "git --git-dir demo/.git log",
        "git --work-tree demo status",
        "git clone demo copy",
        "git push origin HEAD:topic",
        "git remote add o demo",
    ],
)
def test_inside_the_workspace_is_workspace(repo: Path, ws: Path, command: str) -> None:
    assert where_of(repo, ws, command) is Where.WORKSPACE


@pytest.mark.parametrize(
    "command",
    [
        "git -c core.worktree=/elsewhere status",
        "git clone https://h/r",
        "git clone git@host:r.git",
        "git remote add o /elsewhere",
        "git config --global user.name x",
        "git config --system user.name x",
        "git -c alias.x=!rm status",
        "git init ../../..",
    ],
)
def test_reaching_out_is_elsewhere(repo: Path, ws: Path, command: str) -> None:
    assert where_of(repo, ws, command) is Where.ELSEWHERE


def test_step_dir_is_the_cwd_without_explicit_places(repo: Path, ws: Path) -> None:
    base = system.resolve(repo)
    assert where_of(repo, ws, "git status", base) is Where.STEP_DIR
    assert where_of(repo, ws, "git -C . status", base) is Where.ELSEWHERE


def test_unknown_base_is_unknown_unless_an_absolute_place_resets(repo: Path, ws: Path) -> None:
    site = site_of(repo, ws)
    plain = git_check.parse_git(git_check.strip_prefixes(["git", "commit"]))
    placed = git_check.parse_git(git_check.strip_prefixes(["git", "-C", f"{ws}/demo", "commit"]))
    assert plain and placed
    assert git_check.where(site, plain, None)[0] is Where.UNKNOWN
    assert git_check.where(site, placed, None)[0] is Where.WORKSPACE


def test_env_chdir_is_the_first_place(repo: Path, ws: Path) -> None:
    stripped = git_check.strip_prefixes(["env", "-C", str(repo), "git", "commit"])
    call = git_check.parse_git(stripped)
    assert call is not None
    assert git_check.where(site_of(repo, ws), call, system.resolve(ws))[0] is Where.ELSEWHERE


def test_a_symlink_out_of_the_workspace_is_outside(
    repo: Path, ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = system.resolve
    link = system.resolve(ws) / "link"

    def resolve(path: Path) -> Path:
        return system.resolve(repo) if path == link else real(path)

    monkeypatch.setattr(system, "resolve", resolve)
    assert where_of(repo, ws, "git -C link status") is Where.ELSEWHERE


# ----- AC7 / AC2 / AC3 through the guard ---------------------------------------------


def test_workspace_git_is_allowed(repo: Path, ws: Path) -> None:
    scope = confined(repo, ws)
    for command in [
        f"cd {ws} && git init demo",
        f"git -C {ws}/demo commit -m x",
        f"cd {ws} && git clone demo copy",
        f"cd {ws} && git -C demo rebase main",
        f"cd {ws}/demo && git checkout -b topic",
    ]:
        assert denial(scope, command) is None, command


def test_the_same_commands_with_paths_outside_are_denied(repo: Path, ws: Path) -> None:
    scope = confined(repo, ws)
    for command in [
        f"git -C {repo} commit -m x",
        f"cd {ws} && git clone demo /tmp/x",
        f"git init {repo}/x",
    ]:
        assert denial(scope, command), command


def test_team_repo_is_denied_with_git_reason_naming_it(repo: Path, ws: Path) -> None:
    scope = confined(repo, ws)
    for command in [f"git -C {repo} status", f"git --git-dir {repo}/.git log"]:
        reason = denial(scope, command)
        assert reason and str(system.resolve(repo)) in reason
        assert "may not reference" not in reason
        assert "may not run `git" in reason


def test_proxy_git_reason_is_the_git_one(repo: Path, ws: Path) -> None:
    scope = confined(repo, ws, "customer-proxy")
    reason = denial(scope, f"git -C {repo} status")
    assert reason and "customer-proxy may not run `git" in reason


def test_step_cwd_reads_allowed_writes_denied(repo: Path, ws: Path) -> None:
    scope = confined(repo, ws)
    for command in ["git status", "git diff", "git log"]:
        assert denial(scope, command) is None
    reason = denial(scope, "git commit -m x")
    assert reason and str(system.resolve(repo)) in reason


def test_unknown_place_is_denied_with_its_own_reason(repo: Path, ws: Path) -> None:
    scope = confined(repo, ws)
    reason = denial(scope, f"cd {ws}; git commit -m x")
    assert reason and "an earlier `cd` may not have run" in reason
    assert denial(scope, f"cd x; git -C {ws}/demo commit -m x") is None


def test_env_chdir_to_the_team_repo_is_denied(repo: Path, ws: Path) -> None:
    scope = confined(repo, ws)
    assert denial(scope, f"cd {ws} && env -C {repo} git commit -m x")


# ----- G7: git's environment is locked -----------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "GIT_DIR=/x git status",
        "export GIT_CEILING_DIRECTORIES=",
        "unset CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR",
        "GIT_WORK_TREE=/x ls",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM=1 ls",
    ],
)
def test_confined_step_may_not_touch_gits_environment(repo: Path, ws: Path, command: str) -> None:
    reason = denial(confined(repo, ws), command)
    assert reason and "the runner sets git's environment for this step" in reason


def test_unconfined_step_is_not_denied_by_the_env_lock(repo: Path) -> None:
    assert denial(unconfined(repo), "GIT_DIR=/x ls") is None
    assert denial(unconfined(repo), "export GIT_CEILING_DIRECTORIES=") is None


def test_env_lock_names() -> None:
    assert set(git_check.GIT_ENV_LOCKED) == {
        "GIT_CEILING_DIRECTORIES",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_SEQUENCE_EDITOR",
        "GIT_EDITOR",
        "GIT_EXTERNAL_DIFF",
        "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR",
    }


# ----- G2: the environment ----------------------------------------------------------


def test_git_env_is_ceiling_and_kept_cwd(repo: Path) -> None:
    run_dir = repo / ".team" / "run"
    assert git_check.git_env(run_dir) == {
        git_check.CEILING_ENV: str(system.resolve(run_dir)),
        git_check.KEEP_CWD_ENV: "1",
    }


def test_git_denial_without_git_is_none() -> None:
    assert git_check.git_denial(None, [Link(("ls",), "")]) is None
    assert git_check.git_denial(None, []) is None
