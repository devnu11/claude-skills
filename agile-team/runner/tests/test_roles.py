"""Role parsing, extends chains, overrides, prompt assembly and handoffs."""

from pathlib import Path

import pytest
from agile_team import roles, system
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


def test_every_builtin_role_resolves(repo: Path) -> None:
    real = RoleBook.for_repo(repo, {})
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


def test_load_dir_missing(repo: Path) -> None:
    assert roles.load_dir(repo / "none") == {}


def test_expand_globs() -> None:
    values = {"tests": ["tests/**", "!tests/e2e/**"], "source": ["src/**"]}
    out = roles.expand_globs(["{source}", "!{tests}", "lit/**"], values)
    assert out == ["src/**", "!tests/**", "lit/**"]
    with pytest.raises(RoleError, match="placeholder"):
        roles.expand_globs(["{nope}"], values)


def test_system_prompt_order(repo: Path) -> None:
    system.make_dirs(repo / ".team")
    system.write_text(repo / ".team/CLAUDE.md", "CHARTER")
    b = book({"child": "ADDENDUM"}, repo)
    prompt = b.system_prompt(b.resolve("child"), "SCOPE")
    order = [prompt.index(s) for s in ("SHARED", "BASE", "CHILD", "ADDENDUM", "CHARTER", "SCOPE")]
    assert order == sorted(order)


def test_system_prompt_skips_missing(repo: Path) -> None:
    b = book(repo=repo)
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


def test_enabled_names(repo: Path) -> None:
    real = RoleBook.for_repo(repo, {"integration-tester": {"enabled": False}})
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


def test_user_roles_dir(repo: Path) -> None:
    assert roles.user_roles_dir(repo, {}) == repo / ".config/agile-team/roles"
    assert roles.user_roles_dir(repo, {"AGILE_TEAM_HOME": "/x"}) == Path("/x/roles")


def test_scaffold_writes_missing_stubs_only(repo: Path) -> None:
    real = RoleBook.for_repo(repo, {})
    target = repo / "roles"
    system.make_dirs(target)
    system.write_text(target / "architect.md", "mine")
    created = real.scaffold(target, roles.Layer.GLOBAL)
    names = {p.stem for p in created}
    assert "_shared" in names and "developer" in names and "architect" not in names
    stub = system.read_text(target / "developer.md")
    assert "global layer" in stub and "Write plain Markdown" in stub
    assert system.read_text(target / "architect.md") == "mine"
    assert real.scaffold(target, roles.Layer.GLOBAL) == []
    reloaded = RoleBook.for_repo(repo, {}, target)
    assert reloaded.resolve("developer").body == real.resolve("developer").body
    assert reloaded.addendum("architect") == "mine"


# ----- s13: the role rules state the handover (AC1, AC2, AC4, AC5) ----------


def test_integration_tester_builds_the_presentation(repo: Path) -> None:
    tester = RoleBook.for_repo(repo, {}).resolve("integration-tester")
    assert ".team/run/presentation/**" in tester.write and "{e2e}" in tester.write
    assert "PRESENTATION.md" in tester.body and "live-status.json" in tester.body


def test_customer_proxy_never_builds_its_own_environment(repo: Path) -> None:
    proxy = RoleBook.for_repo(repo, {}).resolve("customer-proxy")
    assert "changes_requested" in proxy.body and "integration-tester" in proxy.body
    assert "never build" in proxy.body
    assert "Read it, then rewrite it" in proxy.body


def test_product_owner_knows_the_returned_status(repo: Path) -> None:
    po = RoleBook.for_repo(repo, {}).resolve("product-owner")
    assert "returned" in po.body


# ----- s19: the handoff's developer field and the built-in PO/architect ----------


def test_handoff_developer_defaults_to_none() -> None:
    assert roles.parse_handoff('```handoff\n{"status": "done"}\n```').developer is None


def test_handoff_developer_is_read() -> None:
    text = '```handoff\n{"status": "done", "developer": "developer-cli"}\n```'
    assert roles.parse_handoff(text).developer == "developer-cli"


@pytest.mark.parametrize("value", ["null", '""'])
def test_handoff_empty_developer_is_none(value: str) -> None:
    text = f'```handoff\n{{"status": "done", "developer": {value}}}\n```'
    assert roles.parse_handoff(text).developer is None


@pytest.mark.parametrize("value", ["3", "[]", "true"])
def test_handoff_developer_must_be_a_string(value: str) -> None:
    text = f'```handoff\n{{"status": "done", "developer": {value}}}\n```'
    with pytest.raises(roles.HandoffError, match="developer must be a role name"):
        roles.parse_handoff(text)


def test_product_owner_defaults_to_sonnet(repo: Path) -> None:
    po = RoleBook.for_repo(repo, {}).resolve("product-owner")
    assert po.model == "sonnet"
    assert po.description == (
        "Schedules the stories the liaison writes, starts sprints and makes the team's "
        "judgement calls; the only role that talks to the human."
    )


def test_product_owner_body_describes_the_split(repo: Path) -> None:
    body = RoleBook.for_repo(repo, {}).resolve("product-owner").body
    for text in ("continue_story", "set_developer", "standard brief", "judgement"):
        assert text in body
    assert "Run the `scribe` after each story" not in body
    assert "Keep briefs short" not in body
    assert "point at artifacts rather than restating them" in body
    assert "the runner sends it back to e2e" in body


def test_architect_names_the_developer_in_the_handoff(repo: Path) -> None:
    body = RoleBook.for_repo(repo, {}).resolve("architect").body
    assert '"developer": "developer-cli"' in body
    assert "in your summary" not in body
    assert "story index" in body


def test_devops_scopes_its_test_runs(repo: Path) -> None:
    body = RoleBook.for_repo(repo, {}).resolve("devops").body
    text = " ".join(body.split())
    for phrase in (
        "Run only what proves your change, normally one named test",
        "Never run the full suite or a coverage run; the runner's gate does those",
        "only so the onboarding sprint can record its baseline",
        "This is the one step where you run the full suite and the coverage command.",
        "run the failing tests the brief names",
    ):
        assert phrase in text


def test_integration_tester_prompt_explains_the_seeded_config(repo: Path) -> None:
    body = RoleBook.for_repo(repo, {}).resolve("integration-tester").body
    assert "the runner seeds the config" in body
    assert 'token = "presentation"' in body


LEADERSHIP = {
    "_shared": "---\nname: _shared\n---\nSHARED",
    "_lead": "---\nextends: _shared\n---\nLEAD",
    "boss": "---\nextends: _lead\nmodel: sonnet\neffort: low\n---\nBOSS",
}


def test_underscore_files_are_bases_not_roles() -> None:
    lead = RoleBook(dict(LEADERSHIP), {}, {}, Path())
    assert lead.names() == {"boss"}
    assert lead.resolve("boss").body == "LEAD\n\nBOSS"


def test_addenda_follow_the_extends_chain() -> None:
    repo = {"_lead": "Decided once.", "boss": "Boss note."}
    body = RoleBook(dict(LEADERSHIP), repo, {}, Path()).resolve("boss").body
    assert body == "LEAD\n\nDecided once.\n\nBOSS\n\nBoss note."


def test_leadership_reaches_po_and_manager_only(repo: Path) -> None:
    system.make_dirs(repo / ".team" / "roles")
    system.write_text(repo / ".team" / "roles" / "_leadership.md", "Raise budgets slowly.")
    real = RoleBook.for_repo(repo, {})
    assert "_leadership" not in real.names()
    for name in ("product-owner", "manager"):
        assert "Raise budgets slowly." in real.resolve(name).body
        assert "leadership team" in real.resolve(name).body
    assert "Raise budgets slowly." not in real.resolve("architect").body
