"""s114: the Scribe and the briefs are retired; the architect writes the ADRs."""

import json
import re
from pathlib import Path

import pytest
from agile_team import cli, dispatch, gates, roles, router, state, system
from agile_team import config as cfg
from agile_team.roles import RoleBook, RoleError

WHY = (
    "the Scribe was retired in s114: the architect writes ADRs in .team/adr/ "
    "and roles get no briefs"
)
PAGE = Path(__file__).parent.parent / "agile_team/dashboard/index.html"
FIXTURE = Path(__file__).parent.parent / "agile_team/dashboard/fixtures/snapshot.json"
SCRIBE_WORD = re.compile(r"\bscribe\b", re.IGNORECASE)
ROLE_SECTIONS = ("events", "ledger", "steps")


def builtin_names() -> list[str]:
    return sorted(
        n for n in roles.load_dir(roles.BUILTIN_DIR) if not n.startswith(roles.BASE_PREFIX)
    )


def stub_text() -> str:
    return roles.STUB.format(name="scribe", layer="repo", description="x")


def fixture_role_names(snapshot: dict) -> set[str | None]:
    """Every role name the dashboard fixture mentions: roles, events, ledger, steps."""
    named = {r["name"] for r in snapshot["roles"]}
    return named | {e.get("role") for key in ROLE_SECTIONS for e in snapshot[key]}


# ----- SC1: no briefs in prompts -------------------------------------------------------


@pytest.mark.parametrize("name", builtin_names())
def test_no_prompt_includes_a_scribe_brief(repo: Path, name: str) -> None:
    system.make_dirs(repo / ".team/briefs")
    system.write_text(repo / ".team/briefs" / f"{name}.md", f"BRIEF-MARKER-{name}")
    book = RoleBook.for_repo(repo, {})
    prompt = book.system_prompt(book.resolve(name), "scope")
    assert f"BRIEF-MARKER-{name}" not in prompt
    assert "Brief from the Scribe" not in prompt


def test_briefs_constant_is_gone() -> None:
    assert not hasattr(roles, "BRIEFS")


# ----- SC2 / SC5: no scribe role -------------------------------------------------------


def test_builtin_scribe_is_gone(repo: Path) -> None:
    assert "scribe" not in roles.load_dir(roles.BUILTIN_DIR)
    with pytest.raises(RoleError, match="unknown role 'scribe'"):
        RoleBook.for_repo(repo, {}).resolve("scribe")


def test_retired_roles_table() -> None:
    assert roles.RETIRED_ROLES == {"scribe": WHY}


# ----- SC3: nothing routes to a scribe -------------------------------------------------


def test_routing_constants_have_no_scribe() -> None:
    assert set(gates.UNGATED_ROLES) == {"manager"}
    assert set(gates.STORYLESS_ROLES) == {"architect", "devops", "unit-tester", "manager"}
    assert set(dispatch.BOUNDARY_UNGATED) == {dispatch.MANAGER}
    assert not hasattr(dispatch, "SCRIBE")


def test_router_has_no_scribe_picker() -> None:
    names = [p.__name__ for p in router.Router.PICKERS]
    assert names == ["_boundary_work", "_manager_work", "_repeat_work", "_land_work", "_story_work"]
    assert not hasattr(router, "BRIEF_HEADINGS")
    assert not hasattr(router.Router, "_scribe_work")


# ----- SC4: old state loads ------------------------------------------------------------


def old_state_text() -> str:
    override = {"model": "haiku", "effort": "low", "reason": "r"}
    data = {
        "sprint": 1,
        "scribe_due": ["s1"],
        "overrides": {"scribe": override, "developer": override},
    }
    return json.dumps(data)


def test_old_state_with_scribe_due_loads_and_drops_it() -> None:
    loaded = state.RunState.from_json(old_state_text())
    assert not hasattr(loaded, "scribe_due")
    assert "scribe_due" not in json.loads(loaded.to_json())


def test_old_state_drops_scribe_override_and_keeps_others() -> None:
    loaded = state.RunState.from_json(old_state_text())
    assert set(loaded.overrides) == {"developer"}
    assert set(json.loads(loaded.to_json())["overrides"]) == {"developer"}


def test_run_dropped_names_scribe_due() -> None:
    assert set(state.RUN_DROPPED) == {"scribe_due", "offered", "land_queue"}


# ----- SC6: [roles.scribe] refused -----------------------------------------------------


@pytest.mark.parametrize("section", [{"model": "haiku"}, {"extends": "developer"}, {}])
def test_roles_scribe_section_is_refused(repo: Path, section: dict) -> None:
    with pytest.raises(cfg.ConfigError) as err:
        cfg.from_raw(repo, {"roles": {"scribe": section}})
    assert str(err.value) == f"{WHY}; remove [roles.scribe] from .agile-team.toml"


def test_other_role_sections_still_load(repo: Path) -> None:
    config = cfg.from_raw(repo, {"roles": {"developer": {"model": "haiku"}}})
    assert config.roles == {"developer": {"model": "haiku"}}


def test_no_roles_section_loads(repo: Path) -> None:
    assert cfg.from_raw(repo, {}).roles == {}


def test_retired_sections_pure() -> None:
    assert roles.retired_sections({}) == []
    assert roles.retired_sections({"developer": {}}) == []
    assert roles.retired_sections({"scribe": {}, "developer": {}}) == [
        f"{WHY}; remove [roles.scribe] from .agile-team.toml"
    ]


# ----- SC7: scribe.md refused unless a stub --------------------------------------------


def write_repo_scribe(repo: Path, text: str) -> Path:
    system.make_dirs(repo / ".team/roles")
    path = repo / ".team/roles/scribe.md"
    system.write_text(path, text)
    return path


@pytest.mark.parametrize("text", ["Keep ADRs short.", "---\nextends: developer\n---\nbody"])
def test_repo_scribe_file_is_refused(repo: Path, text: str) -> None:
    path = write_repo_scribe(repo, text)
    with pytest.raises(RoleError) as err:
        RoleBook.for_repo(repo, {})
    assert str(err.value) == f"{WHY}; delete {path}"


def test_repo_scribe_stub_is_ignored(repo: Path) -> None:
    write_repo_scribe(repo, stub_text())
    assert "scribe" not in RoleBook.for_repo(repo, {}).names()


def test_global_scribe_file_is_refused(repo: Path, isolated_global_roles: Path) -> None:
    system.make_dirs(isolated_global_roles)
    system.write_text(isolated_global_roles / "scribe.md", "Keep ADRs short.")
    with pytest.raises(RoleError) as err:
        RoleBook.for_repo(repo, {}, isolated_global_roles)
    assert str(err.value) == f"{WHY}; delete {isolated_global_roles / 'scribe.md'}"


def test_global_scribe_stub_is_ignored(repo: Path, isolated_global_roles: Path) -> None:
    system.make_dirs(isolated_global_roles)
    system.write_text(isolated_global_roles / "scribe.md", stub_text())
    book = RoleBook.for_repo(repo, {}, isolated_global_roles)
    assert "scribe" not in book.names()


def test_both_layers_refused_repo_first(repo: Path, isolated_global_roles: Path) -> None:
    path = write_repo_scribe(repo, "Keep ADRs short.")
    system.make_dirs(isolated_global_roles)
    system.write_text(isolated_global_roles / "scribe.md", "More.")
    with pytest.raises(RoleError) as err:
        RoleBook.for_repo(repo, {}, isolated_global_roles)
    assert str(err.value) == (
        f"{WHY}; delete {path}; {WHY}; delete {isolated_global_roles / 'scribe.md'}"
    )


def test_retired_files_pure() -> None:
    a, b = Path("/a"), Path("/b")
    layers = {a: {"scribe": "text", "x": "y"}, b: {"scribe": stub_text()}, Path("/c"): {}}
    assert roles.retired_files(layers) == [f"{WHY}; delete /a/scribe.md"]
    assert roles.retired_files({}) == []


# ----- SC8: the CLI prints a RoleError -------------------------------------------------


def test_cli_refuses_scribe_file_without_traceback(configured: Path, capsys) -> None:
    write_repo_scribe(configured, "Keep ADRs short.")
    code = cli.main(["--repo", str(configured), "config", "check"])
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("agile-team config: ") or err.startswith("agile-team config check: ")
    assert "the Scribe was retired in s114" in err
    assert "Traceback" not in err


# ----- SC9 / SC10: the architect owns ADRs ---------------------------------------------


def test_architect_writes_adrs(repo: Path) -> None:
    architect = RoleBook.for_repo(repo, {}).resolve("architect")
    assert architect.write == ["{docs}", ".team/adr/**"]
    assert ".team/adr/NNNN-<slug>.md" in architect.body
    assert "amend" in architect.body
    for word in ("Context", "Decision", "Consequences"):
        assert word in architect.body


@pytest.mark.parametrize("name", sorted(roles.load_dir(roles.BUILTIN_DIR)))
def test_no_builtin_role_mentions_the_scribe_or_briefs_dir(name: str) -> None:
    text = roles.load_dir(roles.BUILTIN_DIR)[name]
    assert not SCRIBE_WORD.search(text)
    assert ".team/briefs" not in text


@pytest.mark.parametrize("text", ["scribe", "the Scribe", "the Scribe's ADRs", "SCRIBE"])
def test_scribe_word_matches_the_word(text: str) -> None:
    assert SCRIBE_WORD.search(text)


@pytest.mark.parametrize("text", ["describe", "prescribe", "Describes the step", "scribes"])
def test_scribe_word_skips_other_words(text: str) -> None:
    assert SCRIBE_WORD.search(text) is None


def test_shared_no_longer_says_your_brief_below() -> None:
    assert "your brief below" not in roles.load_dir(roles.BUILTIN_DIR)["_shared"]


def test_product_owner_does_not_run_a_scribe() -> None:
    assert not SCRIBE_WORD.search(po_body())


# ----- SC11: dashboard -----------------------------------------------------------------


def test_dashboard_ring_has_no_scribe() -> None:
    assert "scribe" not in system.read_text(PAGE).lower()


def test_fixture_has_no_scribe_role() -> None:
    names = fixture_role_names(json.loads(system.read_text(FIXTURE)))
    assert "architect" in names
    assert "scribe" not in names


def test_fixture_role_names_reads_every_section() -> None:
    snapshot = {
        "roles": [{"name": "a"}],
        "events": [{"role": "b"}, {"kind": "x"}],
        "ledger": [{"role": "c"}],
        "steps": [{"role": "scribe"}],
    }
    assert fixture_role_names(snapshot) == {"a", "b", None, "c", "scribe"}


# ----- s117: product-owner.md wording --------------------------------------------------


def po_body() -> str:
    return RoleBook.for_repo(Path("/none"), {}).resolve("product-owner").body


def test_po_mission_has_the_missing_and() -> None:
    assert "sends a story back with\nthe gate's reason, and runs the manager" in po_body()


def test_po_item_5_is_a_capitalised_wrapped_sentence() -> None:
    body = po_body()
    assert "\n   `continue_story` it or `run_role` a step on it yourself. Calling\n" in body
    assert "   `continue_story` also clears" in body
    item = body.split("\n5. A story in your prompt is held.")[1].split("\n6. ")[0]
    assert all(len(line) <= 78 for line in item.splitlines())
