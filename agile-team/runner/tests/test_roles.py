"""Role parsing, extends chains, overrides, prompt assembly and handoffs."""

from pathlib import Path

import pytest
from agile_team import roles
from agile_team.roles import RoleBook, RoleError

BUILTIN = {
    "_shared": "---\nname: _shared\n---\nSHARED",
    "base": "---\nmodel: sonnet\neffort: low\ntools: [Read]\nwrite: ['{source}']\n---\nBASE",
    "child": "---\nextends: base\neffort: high\n---\nCHILD",
    "loop-a": "---\nextends: loop-b\n---\nA",
    "loop-b": "---\nextends: loop-a\n---\nB",
    "bare": "---\nextends: _shared\n---\nno model",
}


def book(repo_files=None, repo: Path = Path()) -> RoleBook:
    return RoleBook(dict(BUILTIN), repo_files or {}, {}, repo)


def test_every_builtin_role_resolves(tmp_path: Path) -> None:
    real = RoleBook.for_repo(tmp_path, {})
    assert "product-owner" in real.names() and "_shared" not in real.names()
    for name in real.names():
        role = real.resolve(name)
        assert role.model in {"opus", "sonnet", "haiku"}
        assert role.effort in {"low", "medium", "high"}
    assert "handoff" in real.shared_body()


def test_extends_chain_inherits_and_concatenates() -> None:
    r = book().resolve("child")
    assert (r.model, r.effort, r.tools, r.write) == ("sonnet", "high", ["Read"], ["{source}"])
    assert r.body == "BASE\n\nCHILD"
    assert r.read == ["**"] and r.enabled


def test_cycle_detected() -> None:
    with pytest.raises(RoleError, match="cycle"):
        book().resolve("loop-a")


def test_missing_model() -> None:
    with pytest.raises(RoleError, match="model and effort"):
        book().resolve("bare")


def test_unknown_role() -> None:
    with pytest.raises(RoleError, match="unknown role"):
        book().spec("nope")


def test_repo_addendum_appended() -> None:
    r = book(repo_files={"child": "Prefer hexagonal."}).resolve("child")
    assert r.body.endswith("Prefer hexagonal.")


def test_repo_complete_file_replaces_builtin() -> None:
    b = book(repo_files={"base": "---\nmodel: opus\neffort: max\n---\nREPO"})
    assert b.resolve("base").body == "REPO"
    assert b.resolve("child").model == "opus"


def test_repo_new_role_listed() -> None:
    b = book(repo_files={"embedded": "---\nextends: base\n---\nEMB", "base": "addendum"})
    assert "embedded" in b.names()


def test_config_override_and_config_only_role() -> None:
    b = RoleBook(
        dict(BUILTIN),
        {},
        {
            "child": {"model": "haiku", "enabled": False, "bogus": 1},
            "child-x": {"extends": "child"},
        },
    )
    assert b.resolve("child").model == "haiku"
    assert not b.resolve("child").enabled
    assert b.resolve("child-x").body == "BASE\n\nCHILD"
    assert b.resolve("child", {"model": "opus"}).model == "opus"


def test_parse_role_errors() -> None:
    with pytest.raises(RoleError, match="mapping"):
        roles.parse_role("x", "---\n- a\n---\nbody")
    with pytest.raises(RoleError, match="unknown frontmatter"):
        roles.parse_role("x", "---\ncolour: red\n---\nbody")
    assert roles.parse_role("x", "just text").body == "just text"


def test_load_dir_missing(tmp_path: Path) -> None:
    assert roles.load_dir(tmp_path / "none") == {}


def test_expand_globs() -> None:
    values = {"tests": ["tests/**", "!tests/e2e/**"], "source": ["src/**"]}
    out = roles.expand_globs(["{source}", "!{tests}", "lit/**"], values)
    assert out == ["src/**", "!tests/**", "lit/**"]
    with pytest.raises(RoleError, match="placeholder"):
        roles.expand_globs(["{nope}"], values)


def test_system_prompt_order(tmp_path: Path) -> None:
    (tmp_path / ".team/briefs").mkdir(parents=True)
    (tmp_path / ".team/CLAUDE.md").write_text("CHARTER")
    (tmp_path / ".team/briefs/child.md").write_text("BRIEF")
    b = book({"child": "ADDENDUM"}, tmp_path)
    prompt = b.system_prompt(b.resolve("child"), "SCOPE")
    order = [
        prompt.index(s)
        for s in ("SHARED", "BASE", "CHILD", "ADDENDUM", "CHARTER", "BRIEF", "SCOPE")
    ]
    assert order == sorted(order)


def test_system_prompt_skips_missing(tmp_path: Path) -> None:
    b = book(repo=tmp_path)
    prompt = b.system_prompt(b.resolve("base"), "")
    assert "charter" not in prompt and "Scribe" not in prompt


def test_scope_note() -> None:
    assert "nothing" in roles.scope_note([], ["**"])
    assert "src/**" in roles.scope_note(["src/**"], ["**"])


def test_parse_handoff_takes_last_block() -> None:
    text = (
        '```handoff\n{"status": "failed"}\n```\nlater\n```handoff\n'
        '{"status": "done", "summary": "ok", "changed_files": ["a"], "next_role": "x",'
        ' "ruling": "rescope"}\n```'
    )
    h = roles.parse_handoff(text)
    assert (h.status, h.summary, h.changed_files, h.next_role, h.ruling) == (
        "done",
        "ok",
        ["a"],
        "x",
        "rescope",
    )


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("no block", "no ```handoff"),
        ("```handoff\nnot json\n```", "valid JSON"),
        ("```handoff\n[1]\n```", "JSON object"),
        ('```handoff\n{"status": "meh"}\n```', "status"),
        ('```handoff\n{"status": "done", "changed_files": "a"}\n```', "changed_files"),
        ('```handoff\n{"status": "done", "ruling": "fire"}\n```', "ruling"),
        ('```handoff\n{"status": "done", "friction": 3}\n```', "friction"),
        ('```handoff\n{"status": "done", "followups": {"dev": 1}}\n```', "followups"),
    ],
)
def test_malformed_handoff_rejected(text: str, match: str) -> None:
    with pytest.raises(roles.HandoffError, match=match):
        roles.parse_handoff(text)


def test_parse_handoff_none() -> None:
    with pytest.raises(roles.HandoffError):
        roles.parse_handoff(None)  # type: ignore[arg-type]


def test_enabled_names(tmp_path: Path) -> None:
    real = RoleBook.for_repo(tmp_path, {"integration-tester": {"enabled": False}})
    names = real.enabled_names()
    assert "integration-tester" not in names and "developer" in names


def test_provider_defaults_and_overrides() -> None:
    b = RoleBook(dict(BUILTIN), {}, {"child": {"provider": "local", "model": "qwen3-coder"}})
    assert b.resolve("base").provider == "anthropic"
    assert b.resolve("child").provider == "local"
    assert b.resolve("child", {"provider": "anthropic", "model": "sonnet"}).provider == "anthropic"
    assert roles.parse_role("x", "---\nprovider: local\n---\n").provider == "local"


def layered(user=None, repo_files=None) -> RoleBook:
    return RoleBook(dict(BUILTIN), repo_files or {}, {}, Path(), user or {})


def test_global_then_repo_addenda_without_comments() -> None:
    b = layered({"base": "<!-- stub -->\nG"}, {"base": "R\n<!-- note -->"})
    assert b.resolve("base").body == "BASE\n\nG\n\nR"
    assert b.layers("base") == {"builtin": "base", "global": "addendum", "repo": "addendum"}


def test_complete_files_repo_beats_global_beats_builtin() -> None:
    glob = "---\nmodel: haiku\neffort: low\n---\nGLOBAL"
    assert layered({"base": glob}).resolve("base").body == "GLOBAL"
    repo = "---\nmodel: opus\neffort: max\n---\nREPO"
    both = layered({"base": glob}, {"base": repo})
    assert both.resolve("base").model == "opus" and both.layers("base")["global"] == "replace"
    assert "extra" in layered({"extra": glob}).names()


def test_stub_adds_nothing_and_shared_addendum_applies() -> None:
    b = layered({"_shared": "Always be terse."}, {"base": "<!-- only a comment -->"})
    assert b.resolve("base").body == "BASE" and b.layers("base")["repo"] == "stub"
    assert b.shared_body() == "SHARED\n\nAlways be terse."
    assert b.layers("nothing") == {"builtin": None, "global": None, "repo": None}


def test_user_roles_dir(tmp_path: Path) -> None:
    assert roles.user_roles_dir(tmp_path, {}) == tmp_path / ".config/agile-team/roles"
    assert roles.user_roles_dir(tmp_path, {"AGILE_TEAM_HOME": "/x"}) == Path("/x/roles")


def test_scaffold_writes_missing_stubs_only(tmp_path: Path) -> None:
    real = RoleBook.for_repo(tmp_path, {})
    target = tmp_path / "roles"
    target.mkdir()
    (target / "architect.md").write_text("mine")
    created = real.scaffold(target, roles.Layer.GLOBAL)
    names = {p.stem for p in created}
    assert "_shared" in names and "developer" in names and "architect" not in names
    stub = (target / "developer.md").read_text()
    assert "global layer" in stub and "Write plain Markdown" in stub
    assert (target / "architect.md").read_text() == "mine"
    assert real.scaffold(target, roles.Layer.GLOBAL) == []
    reloaded = RoleBook.for_repo(tmp_path, {}, target)
    assert reloaded.resolve("developer").body == real.resolve("developer").body
    assert reloaded.addendum("architect") == "mine"
