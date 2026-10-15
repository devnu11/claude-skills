"""s23 Parts 2 and 3: turns per step, long-running roles, isolation, and leaner role files."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import pytest
from agile_team import dispatch, guard, insights, roles, system
from agile_team import state as state_mod
from agile_team.dashboard import snapshot
from agile_team.dispatch import Launch, Plan
from agile_team.guard import ToolCall
from agile_team.insights import long_running_roles, spend_by_role
from agile_team.ledger import Entry, Ledger, Tokens, Totals
from agile_team.po_tools import PoTurn, po_plan

from .pipeline_helpers import Script, add_story, build, drive

DASHBOARD = resources.files("agile_team.dashboard")
FIXTURE = Path(snapshot.__file__).parent / "fixtures" / "snapshot.json"


def entry(role: str, turns: int, tokens: Tokens | None = None, story: str | None = None) -> Entry:
    return Entry(role, "m", 0.1, story=story, tokens=tokens or Tokens(input=10), turns=turns)


# ----- T3, T4: Tokens.prompt and Totals ---------------------------------------------


def test_prompt_is_input_plus_cache_read_plus_cache_creation() -> None:
    assert Tokens(input=1, output=50, cache_read=20, cache_creation=300).prompt() == 321


def test_totals_count_unmeasured_entries_as_steps_only() -> None:
    t = Totals()
    t.add(entry("a", 10, Tokens(input=100)))
    t.add(entry("a", 0, Tokens(input=9999)))
    t.add(entry("a", 30, Tokens(input=300)))
    assert (t.steps, t.measured, t.turns, t.measured_prompt) == (3, 2, 40, 400)
    assert t.turns_per_step() == 20.0
    assert t.context_per_turn() == 10


def test_latest_turns_is_the_last_measured_entry() -> None:
    t = Totals()
    t.add(entry("a", 12))
    t.add(entry("a", 0))
    assert t.latest_turns == 12
    t.add(entry("a", 7))
    assert t.latest_turns == 7


def test_empty_totals_have_zero_averages() -> None:
    t = Totals()
    t.add(entry("a", 0))
    assert (t.turns_per_step(), t.context_per_turn(), t.latest_turns) == (0.0, 0, 0)
    assert Totals().turns_per_step() == 0.0


def test_context_per_turn_rounds() -> None:
    t = Totals()
    t.add(entry("a", 3, Tokens(input=10)))
    assert t.context_per_turn() == 3


def test_old_ledger_lines_load_as_unmeasured(scratch: Path) -> None:
    path = scratch / "ledger.jsonl"
    system.write_text(path, json.dumps({"role": "a", "model": "m", "cost_usd": 1.0}) + "\n")
    (loaded,) = Ledger(path).entries()
    assert loaded.turns == 0
    t = Totals()
    t.add(loaded)
    assert (t.steps, t.measured) == (1, 0)


# ----- T5: spend_by_role ------------------------------------------------------------


def test_spend_by_role_reports_measured_turns_and_context(scratch: Path) -> None:
    led = Ledger(scratch / "ledger.jsonl")
    led.record(entry("tester", 10, Tokens(input=1000)))
    led.record(entry("tester", 0))
    led.record(entry("tester", 20, Tokens(input=2000)))
    view = spend_by_role(led)["tester"]
    assert view["steps"] == 3
    assert view["turns_per_step"] == 15.0
    assert view["latest_turns"] == 20
    assert view["context_per_turn"] == 100


def test_spend_by_role_without_turns(scratch: Path) -> None:
    led = Ledger(scratch / "ledger.jsonl")
    led.record(entry("tester", 0))
    view = spend_by_role(led)["tester"]
    assert (view["turns_per_step"], view["latest_turns"], view["context_per_turn"]) == (0.0, 0, 0)


# ----- T6: long_running_roles -------------------------------------------------------


def long_ledger(scratch: Path, rows: list[tuple[str, int]]) -> Ledger:
    led = Ledger(scratch / "ledger.jsonl")
    for role, turns in rows:
        led.record(entry(role, turns, Tokens(input=turns * 100)))
    return led


def test_constants() -> None:
    assert (insights.LONG_TURNS, insights.RECENT, insights.LONG_OF_RECENT) == (30, 3, 2)


def test_two_of_the_last_three_long_lists_the_role(scratch: Path) -> None:
    led = long_ledger(scratch, [("t", 5), ("t", 31), ("t", 40), ("t", 10)])
    # last three: 31, 40, 10 -> two long
    (item,) = long_running_roles(led)
    assert item["role"] == "t" and item["recent_turns"] == [31, 40, 10]
    assert item["context_per_turn"] == 100


def test_exactly_thirty_is_not_long(scratch: Path) -> None:
    led = long_ledger(scratch, [("t", 30), ("t", 30), ("t", 30)])
    assert long_running_roles(led) == []


def test_one_of_three_is_not_listed(scratch: Path) -> None:
    led = long_ledger(scratch, [("t", 99), ("t", 5), ("t", 5)])
    assert long_running_roles(led) == []


def test_only_the_recent_window_counts(scratch: Path) -> None:
    led = long_ledger(scratch, [("t", 99), ("t", 99), ("t", 5), ("t", 5), ("t", 5)])
    assert long_running_roles(led) == []


def test_unmeasured_entries_are_ignored(scratch: Path) -> None:
    led = long_ledger(scratch, [("t", 40), ("t", 0), ("t", 41), ("t", 0)])
    (item,) = long_running_roles(led)
    assert item["recent_turns"] == [40, 41]


def test_roles_are_sorted_by_name(scratch: Path) -> None:
    rows = [("zed", 40), ("alpha", 50), ("zed", 40), ("alpha", 50)]
    assert [i["role"] for i in long_running_roles(long_ledger(scratch, rows))] == ["alpha", "zed"]


def test_no_ledger_no_long_roles(scratch: Path) -> None:
    assert long_running_roles(Ledger(scratch / "none.jsonl")) == []


def test_manager_context_has_long_running_roles(make_runtime) -> None:
    rt = make_runtime()
    for turns in (45, 50):
        rt.ledger.record(entry("developer", turns))
    text = rt._manager_context()
    context = json.loads(text.split("\n", 1)[1])
    assert list(context).index("long_running_roles") == list(context).index("spend_by_role") + 1
    assert context["long_running_roles"][0]["role"] == "developer"
    assert context["spend_by_role"]["developer"]["latest_turns"] == 50


# ----- T2: step-end carries turns ---------------------------------------------------


def test_step_end_events_carry_turns(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design"])
    add_story(rt)
    drive(rt)
    ends = [e for e in rt.events.events() if e.kind == "step-end"]
    assert ends and all(e.data["turns"] == 1 for e in ends)
    assert {e.turns for e in rt.ledger.entries()} == {1}


# ----- L1: isolation ----------------------------------------------------------------


def test_isolation_env_constant() -> None:
    assert dispatch.ISOLATION_ENV == {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}


def role_plan(rt) -> Plan:
    role = rt.resolve("architect")
    return rt.finish(Plan(role, rt.scope_for(role), prompt="x"))


def test_role_steps_use_strict_mcp_and_hide_claudeai_connectors(make_runtime) -> None:
    rt = make_runtime()
    plan = role_plan(rt)
    plan.launch.env = {**plan.launch.env, "KEEP": "1"}
    options = dispatch.build_options(plan)
    assert options.strict_mcp_config is True
    assert options.env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert options.env["KEEP"] == "1"


def test_isolation_env_wins_over_launch_env(make_runtime) -> None:
    rt = make_runtime()
    plan = role_plan(rt)
    plan.launch.env = {"ENABLE_CLAUDEAI_MCP_SERVERS": "true"}
    assert dispatch.build_options(plan).env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"


def test_po_plan_is_isolated_and_keeps_the_team_server(make_runtime) -> None:
    rt = make_runtime()
    options = po_plan(rt, PoTurn("x", None)).options
    assert options.strict_mcp_config is True
    assert options.env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert "team" in options.mcp_servers


def test_launch_mcp_servers_still_load() -> None:
    role = resolved("customer-proxy")
    plan = Plan(role, guard.Scope(role.name, Path("."), [], []), prompt="x")
    plan.launch = Launch(mcp_servers={"sandbox": object()})
    assert list(dispatch.build_options(plan).mcp_servers) == ["sandbox"]


def resolved(name: str):
    return roles.RoleBook.for_repo(Path("."), {}).resolve(name)


# ----- state ------------------------------------------------------------------------


def test_new_state_fields_default_and_legacy_files_load(scratch: Path) -> None:
    assert state_mod.RunState().po_renew_due == []
    assert state_mod.RunState().po_renew_path == "compact"
    legacy = state_mod.RunState().to_json()
    data = json.loads(legacy)
    del data["po_renew_due"], data["po_renew_path"]
    back = state_mod.RunState.from_json(json.dumps(data))
    assert (back.po_renew_due, back.po_renew_path) == ([], "compact")


def test_new_state_fields_round_trip(scratch: Path) -> None:
    st = state_mod.RunState(po_renew_due=["s1 done"], po_renew_path="handoff")
    state_mod.save(scratch, st)
    back = state_mod.load(scratch)
    assert (back.po_renew_due, back.po_renew_path) == (["s1 done"], "handoff")


def test_po_session_event_kind() -> None:
    from agile_team.events import EventKind

    assert EventKind.PO_SESSION == "po-session"


# ----- roles (L2-L6) ----------------------------------------------------------------


def test_po_may_write_its_handoff(make_runtime) -> None:
    rt = make_runtime()
    role = rt.resolve("product-owner")
    assert role.write == [".team/po/**"]
    scope = rt.scope_for(role)
    root = rt.config.repo
    ok = guard.check_tool_use(
        scope, ToolCall("Write", {"file_path": str(root / ".team/po/handoff.md")})
    )
    assert ok is None
    assert guard.check_tool_use(scope, ToolCall("Write", {"file_path": str(root / "src/app.py")}))


def prompt_of(name: str) -> str:
    book = roles.RoleBook.for_repo(Path("."), {})
    return book.system_prompt(book.resolve(name), "")


@pytest.mark.parametrize(
    "name",
    ["architect", "unit-tester", "developer", "code-reviewer", "quality-czar", "manager"],
)
def test_every_role_gets_the_read_little_rules(name: str) -> None:
    """The shared section (roles/_shared.md) reaches every role via system_prompt (L2)."""
    prompt = prompt_of(name)
    assert "## Read little" in prompt  # shared section, not the role's own body
    assert "Never `cat` or `sed` source files through Bash" in prompt
    assert "pytest -q -x --no-header" in prompt


def test_unit_tester_works_lean() -> None:
    prompt = prompt_of("unit-tester")
    assert "## Work lean" in prompt
    assert prompt.index("## Work lean") < prompt.index("## Forbidden")
    assert "Write each test file in one Write" in prompt


def test_architect_keeps_designs_focused() -> None:
    assert "Keep each design file focused" in prompt_of("architect")


def test_manager_raises_long_running_roles() -> None:
    prompt = prompt_of("manager")
    assert "long_running_roles" in prompt and "Long-running roles" in prompt
    assert "latest_turns" in prompt and "context_per_turn" in prompt


def test_po_prompt_explains_renewal_and_handoff_scope() -> None:
    prompt = prompt_of("product-owner")
    assert ".team/po/handoff.md" in prompt
    assert (
        "Editing anything but your handoff file (`.team/po/handoff.md`); "
        "story files are the runner's."
    ) in prompt


# ----- dashboard (T9-T11) -----------------------------------------------------------


@pytest.fixture
def page() -> str:
    return system.read_text(DASHBOARD / "index.html")


@pytest.mark.parametrize("needle", ["Turns/step", "Last turns", "Context/turn"])
def test_tokens_tables_have_the_turn_columns(page: str, needle: str) -> None:
    assert needle in page


def test_turn_columns_sit_between_tokens_and_cost(page: str) -> None:
    head = page[page.index("Turns/step") - 400 : page.index("Context/turn") + 200]
    assert head.index("Turns/step") < head.index("Last turns") < head.index("Context/turn")
    assert head.index("Context/turn") < head.index(">Cost<")


def test_totals_sum_turns_and_keep_the_latest(page: str) -> None:
    body = page[page.index("function totalsBy") : page.index("function renderTokens")]
    for name in ("turns", "measured", "measured_prompt", "latest"):
        assert name in body


def test_unmeasured_groups_show_a_dash(page: str) -> None:
    assert "—" in page[page.index("Turns/step") - 800 : page.index("Context/turn") + 800]


def test_step_end_meta_shows_turns(page: str) -> None:
    body = page[page.index("function stepEndMeta") : page.index("const TIMELINE")]
    assert "turns" in body and body.index("d.turns") < body.index("d.tokens")


def test_timeline_has_the_po_session_entry(page: str) -> None:
    assert '"po-session"' in page
    entry_ = page[page.index('"po-session"') : page.index('"po-session"') + 400]
    for part in ("session ", "reasons", "pre_tokens", "before compaction"):
        assert part in entry_


def test_fixture_step_ends_have_turns_and_a_po_session_event() -> None:
    data = json.loads(system.read_text(FIXTURE))
    ends = [e for e in data["events"] if e["kind"] == "step-end"]
    assert ends and all(isinstance(e["data"].get("turns"), int) for e in ends)
    (session,) = [e for e in data["events"] if e["kind"] == "po-session"]
    assert session["data"]["path"] == "compact" and session["data"]["pre_tokens"]
