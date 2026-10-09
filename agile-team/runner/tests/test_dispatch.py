"""run_role end to end against a real repo with a fake query()."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from agile_team import dispatch, gates, guard, sandbox
from agile_team.config import Delivery
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryStatus, Verdict
from agile_team.ledger import Tokens
from agile_team.providers import Provider, Providers
from agile_team.state import STOP_FILE, ModelOverride, RunState, RunStatus
from claude_agent_sdk import AssistantMessage, TextBlock

from .conftest import GUIDE_TEXT, FakeQuery, FakeRunner, git, handoff, present


def run(rt, role, brief="go", story=None):
    return asyncio.run(rt.run_role(StepRequest(role, brief, story)))


def open_story(rt, step="design", **kw):
    kw.setdefault("sprint", 1)
    rt.state.stories["s1"] = gates.StoryState("s1", "Add todo", step, **kw)
    return rt.state.stories["s1"]


def write(repo: Path, rel: str, text: str = "x"):
    def action() -> None:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)

    return action


def test_collect_without_result_message() -> None:
    async def fake(**_kw):
        yield AssistantMessage(content=[TextBlock(text="only text")], model="m")
        yield AssistantMessage(content=[], model="m")

    result = asyncio.run(dispatch.collect(fake, SimpleNamespace(prompt="p", options=None)))
    assert (result.text, result.cost) == ("only text", 0.0)


def test_options_carry_role_settings(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    run(rt, "architect")
    opts = q.calls[0]["options"]
    assert (opts.model, opts.effort, opts.permission_mode) == ("opus", "high", "dontAsk")
    assert "Bash" not in opts.tools
    assert opts.env == {"ANTHROPIC_API_KEY": "k"}
    assert opts.setting_sources == []
    assert "You may write: docs/**" in opts.system_prompt
    assert opts.hooks["PreToolUse"][0].hooks


def test_refusals(make_runtime, configured: Path) -> None:
    rt = make_runtime()
    assert "unknown role" in run(rt, "wizard")["reason"]
    assert "unknown story" in run(rt, "architect", story="nope")["reason"]
    assert "only runs on a story" in run(rt, "developer")["reason"]
    rt.state.manager_due.append("sprint start")
    assert "manager review due" in run(rt, "architect")["reason"]
    rt.state.manager_due.clear()
    rt.state.status, rt.state.cadence = RunStatus.SPRINT_END, "sprint"
    assert "the run is sprint-end" in run(rt, "architect")["reason"]
    rt.state.status = RunStatus.RUNNING
    rt.config.run_dir.mkdir(parents=True, exist_ok=True)
    (rt.config.run_dir / STOP_FILE).touch()
    assert "stop was requested" in run(rt, "architect")["reason"]


def test_storyless_step_commits_chore(make_runtime, configured: Path) -> None:
    rt = make_runtime(FakeQuery(action=write(configured, "docs/architecture.md")))
    report = run(rt, "architect")
    assert report["status"] == "done" and report["commit"]
    assert git(configured, "log", "-1", "--format=%s").strip() == "chore(team): architect step"
    assert rt.ledger.total() == pytest.approx(0.1)
    assert rt.ledger.entries()[0].tokens == Tokens(100, 20, 300, 40)


def test_story_commits_feat_then_fixup(make_runtime, configured: Path) -> None:
    runner = FakeRunner({"pytest": (1, "")})
    q = FakeQuery(action=write(configured, "docs/design.md"))
    rt = make_runtime(q, runner)
    open_story(rt)
    first = run(rt, "architect", story="s1")
    assert first["gate"]["now_at"] == "tests"
    q.action = write(configured, "tests/test_todo.py")
    second = run(rt, "unit-tester", story="s1")
    assert second["gate"]["verdict"] is Verdict.PASS and second["gate"]["now_at"] == "implement"
    log = git(configured, "log", "--format=%s", "-2").splitlines()
    assert log == ["fixup! feat(s1): Add todo", "feat(s1): Add todo"]
    assert rt.state.stories["s1"].commit == first["commit"]


def test_developer_bash_write_to_tests_is_quarantined(make_runtime, configured: Path) -> None:
    def action() -> None:
        write(configured, "src/todo.py")()
        write(configured, "tests/x", "sneaky")()

    rt = make_runtime(FakeQuery(action=action), FakeRunner({"pytest --cov": (0, "TOTAL 99%")}))
    open_story(rt, "implement")
    report = run(rt, "developer-cli", story="s1")
    assert report["quarantine"] and report["commit"]
    log = git(configured, "log", "--format=%s", "-3").splitlines()
    assert log[0] == "feat(s1): Add todo"
    assert log[1].startswith(
        'Revert "chore(team): quarantine out-of-scope changes by developer-cli'
    )
    assert log[2] == "chore(team): quarantine out-of-scope changes by developer-cli"
    assert rt.git.is_clean() and not (configured / "tests/x").exists()
    assert report["gate"]["verdict"] is Verdict.PASS
    events = rt.events.events()
    assert [e.kind for e in events] == ["step-start", "quarantine", "step-end", "gate"]
    assert {e.role for e in events[:3]} == {"developer-cli"} and events[0].story == "s1"
    assert events[1].data["paths"] == ["tests/x"]
    end = events[2].data
    assert end["status"] == "done" and end["commit"] == report["commit"]
    assert end["tokens"]["input"] == 100 and end["cost_usd"] == 0.1
    assert events[3].data["now_at"] == "quality"


def test_failed_gate_bounces_and_caps(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("changes_requested", next_role="developer")))
    open_story(rt, "review")
    for _ in range(3):
        rt.state.stories["s1"].step = "review"
        report = run(rt, "code-reviewer", story="s1")
    assert report["gate"]["story_status"] is StoryStatus.NEEDS_MANAGER
    rt.state.stories["s1"].step = "review"
    assert "round cap" in run(rt, "code-reviewer", story="s1")["reason"]


def test_manager_rules_on_capped_story(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", ruling="revise_design")))
    open_story(rt, "implement", rounds=3, status=StoryStatus.NEEDS_MANAGER)
    rt.state.manager_due.append("round cap")
    rt.state.overrides["developer"] = ModelOverride("opus", "high", "stuck")
    rt.state.unreviewed.append("developer")
    report = run(rt, "manager", story="s1")
    assert report["status"] == "done"
    s = rt.state.stories["s1"]
    assert (s.step, s.status, s.rounds) == ("design", StoryStatus.ACTIVE, 0)
    assert rt.state.manager_due == [] and rt.state.unreviewed == []
    ruling = rt.events.events()[-1]
    assert ruling.kind == "ruling" and ruling.data == {
        "ruling": "revise_design",
        "now_at": "design",
    }
    prompt = rt.query_fn.calls[0]["prompt"]
    assert "unreviewed_overrides" in prompt and "stuck" in prompt


def test_bad_handoff_bounces(make_runtime) -> None:
    rt = make_runtime(FakeQuery("no handoff here"))
    open_story(rt, "review")
    report = run(rt, "code-reviewer", story="s1")
    assert report["status"] == "bad_handoff"
    assert rt.state.stories["s1"].rounds == 1
    end = next(e for e in rt.events.events() if e.kind == "step-end")
    assert end.data["status"] == "bad_handoff" and "handoff" in end.data["summary"]
    assert run(rt, "architect")["status"] == "bad_handoff"


def test_budget_checkpoint_queues_manager(make_runtime) -> None:
    rt = make_runtime(FakeQuery(cost=6.0))
    run(rt, "architect")
    assert rt.state.manager_due and "budget checkpoint" in rt.state.manager_due[0]


def test_model_override_applies(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    rt.state.overrides["architect"] = ModelOverride("haiku", "low", "cheap")
    run(rt, "architect")
    assert q.calls[0]["options"].model == "haiku"


def test_customer_proxy_runs_in_sandbox(make_runtime, configured: Path) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    open_story(rt, "acceptance")
    present(rt.config)
    report = run(rt, "customer-proxy", story="s1")
    opts = q.calls[0]["options"]
    assert opts.cwd.endswith(".team/run/customer/cli")
    assert '"denyRead"' in opts.settings
    assert "How the customer reaches the product" in q.calls[0]["prompt"]
    assert report["gate"]["story_status"] is StoryStatus.DONE


LOCAL = Providers({"local": Provider("local", "http://localhost:11434")})


def local_runtime(make_runtime, q, role):
    rt = make_runtime(q, providers=LOCAL)
    rt.book.config_roles[role] = {"provider": "local", "model": "qwen3-coder"}
    return rt


def test_local_provider_role_uses_endpoint_and_costs_nothing(make_runtime) -> None:
    q = FakeQuery(cost=0.7)
    report = run(local_runtime(make_runtime, q, "scribe"), "scribe")
    env = q.calls[0]["options"].env
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert q.calls[0]["options"].model == "qwen3-coder"
    assert report["cost_usd"] == 0


def test_local_provider_reaches_the_customer_sandbox(make_runtime) -> None:
    q = FakeQuery()
    rt = local_runtime(make_runtime, q, "customer-proxy")
    open_story(rt, "acceptance")
    present(rt.config)
    run(rt, "customer-proxy", story="s1")
    env = q.calls[0]["options"].env
    assert (env["ANTHROPIC_BASE_URL"], env["ANTHROPIC_API_KEY"]) == ("http://localhost:11434", "")
    assert "PATH" in env


def test_customer_proxy_without_delivery(make_runtime) -> None:
    rt = make_runtime()
    rt.config.deliveries = []
    open_story(rt, "acceptance")
    present(rt.config, workspace=False)
    assert "no [[delivery]]" in run(rt, "customer-proxy", story="s1")["reason"]


def test_manual_acceptance_script_reaches_outbox(make_runtime) -> None:
    script = "1. Plug in the device.\n" + handoff("done")
    rt = make_runtime(FakeQuery(script))
    rt.config.deliveries = [Delivery("hw", "manual")]
    open_story(rt, "acceptance")
    present(rt.config, workspace=False)
    report = run(rt, "customer-proxy", story="s1")
    [question] = rt.relay.open_questions()
    assert question.id == report["question_id"]
    assert "Plug in the device" in question.text and question.stories == ["s1"]
    assert rt.query_fn.calls[0]["options"].tools == ["Write"]


def test_web_proxy_gets_browser(make_runtime) -> None:
    q = FakeQuery()
    stopped = []

    def fake_prepare(config, order):
        p = sandbox.Prepared(
            order.delivery,
            sandbox.DELIVERY_KINDS["web"],
            config.repo,
            config.run_dir,
            config.run_dir,
        )
        p.stop = lambda: stopped.append(True)  # type: ignore[method-assign]
        return p

    rt = make_runtime(q, prepare_fn=fake_prepare)
    rt.config.deliveries = [Delivery("ui", "web", url="http://localhost:3000")]
    open_story(rt, "acceptance")
    present(rt.config)
    run(rt, "customer-proxy", story="s1")
    opts = q.calls[0]["options"]
    assert "playwright" in opts.mcp_servers and "mcp__playwright" in opts.allowed_tools
    assert stopped == [True]


def test_shell_runner(tmp_path: Path) -> None:
    code, out = dispatch.shell_runner(tmp_path)("echo hi; exit 4")
    assert (code, out.strip()) == (4, "hi")


@pytest.mark.parametrize(
    ("status", "cadence", "halted"),
    [
        ("sprint-end", "sprint", True),
        ("sprint-end", "until-blocker", False),
        ("done", "until-blocker", True),
        ("blocked", "sprint", True),
        ("running", "sprint", False),
    ],
)
def test_run_halted(status, cadence, halted) -> None:
    assert RunState(cadence=cadence, status=RunStatus(status)).halted() is halted


def test_po_story_edits_committed_before_next_role(make_runtime, configured: Path) -> None:
    rt = make_runtime(FakeQuery(action=write(configured, "docs/a.md")))
    write(configured, ".team/stories/s1.md", "As a user…")()
    run(rt, "architect")
    log = git(configured, "log", "--format=%s", "-2").splitlines()
    assert log == ["chore(team): architect step", "chore(team): product-owner step"]
    assert "s1.md" in git(configured, "show", "--name-only", "--format=", "HEAD~1")
    assert rt.git.is_clean()


def edit_config(repo: Path, old: str, new: str):
    def action() -> None:
        path = repo / ".agile-team.toml"
        path.write_text(path.read_text().replace(old, new))

    return action


def test_devops_may_edit_toolchain(make_runtime, configured: Path) -> None:
    rt = make_runtime(FakeQuery(action=edit_config(configured, '"pytest"', '"make test"')))
    report = run(rt, "devops")
    assert report["commit"] and not report["quarantine"]


def test_devops_may_not_widen_roles(make_runtime, configured: Path) -> None:
    widen = edit_config(configured, "[team]", '[roles.devops]\nwrite = ["**"]\n\n[team]')
    rt = make_runtime(FakeQuery(action=widen))
    report = run(rt, "devops")
    assert report["quarantine"] and not report["commit"]
    assert "roles.devops" not in (configured / ".agile-team.toml").read_text()


def test_config_edit_unreadable_is_refused(configured: Path) -> None:
    from agile_team.git_ops import Git

    (configured / ".agile-team.toml").write_text("not = [toml")
    assert not dispatch.config_edit_allowed(Git(configured))


def test_secret_denials_merge(tmp_path: Path) -> None:
    assert dispatch.with_secret_denials(None, []) is None
    merged = dispatch.with_secret_denials({"permissions": {"deny": ["X"]}}, [tmp_path / "k"])
    assert merged["permissions"]["deny"][0] == "X"
    assert f"Read(/{tmp_path.resolve()}/k)" in merged["permissions"]["deny"]


def test_roles_get_secret_denials(make_runtime, tmp_path: Path) -> None:
    q = FakeQuery()
    rt = make_runtime(q, secrets=[tmp_path / "secrets"])
    run(rt, "architect")
    assert "secrets" in q.calls[0]["options"].settings
    assert rt.scope_for(rt.book.resolve("developer")).secrets == [tmp_path / "secrets"]


def test_story_blocked_on_open_question(make_runtime) -> None:
    from agile_team.relay import Note

    rt = make_runtime()
    open_story(rt)
    rt.relay.post(Note("question", "DB?", ["s1"]))
    assert "waiting on an answer" in run(rt, "architect", story="s1")["reason"]


def test_backlog_story_is_refused_for_story_bound_roles(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, sprint=None)
    out = run(rt, "architect", story="s1")
    assert out["status"] == "refused"
    assert out["reason"] == "story s1 is in the backlog; add it to a sprint"


def test_backlog_story_still_allows_manager_and_scribe(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, sprint=None)
    for role in ("manager", "scribe"):
        out = run(rt, role, story="s1")
        assert "backlog" not in out.get("reason", "")


def test_manager_followups_reach_the_role_and_friction_is_logged(make_runtime) -> None:
    q = FakeQuery(handoff("done", followups={"architect": "Why so many greps?"}))
    rt = make_runtime(q)
    rt.state.manager_due.append("checkpoint")
    run(rt, "manager")
    assert rt.state.followups == {"architect": ["Why so many greps?"]}
    q.text = handoff("done", friction="No index of the docs; I grep each time.")
    run(rt, "architect")
    assert "## Questions from the Manager" in q.calls[1]["prompt"]
    assert "Why so many greps?" in q.calls[1]["prompt"]
    assert rt.state.followups == {}
    end = [e for e in rt.events.events() if e.kind == "step-end"][-1]
    assert end.data["friction"] == "No index of the docs; I grep each time."
    rt.state.manager_due.append("checkpoint")
    q.text = handoff("done")
    run(rt, "manager")
    context = q.calls[2]["prompt"]
    assert "spend_by_role" in context and "No index of the docs" in context
    assert rt.ledger.entries()[0].turns == 1


# ----- s13: presentation (E2, E4, E6, E7, E8, E9) ----------------------------


def gate_events(rt):
    return [e for e in rt.events.events() if e.kind == "gate"]


def test_unpresented_story_returns_to_e2e_without_a_round(make_runtime) -> None:
    q, prepared = FakeQuery(), []
    rt = make_runtime(q, prepare_fn=lambda *a: prepared.append(a))
    s = open_story(rt, "acceptance", rounds=1)
    report = run(rt, "customer-proxy", story="s1")
    assert (report["status"], report["role"]) == ("returned", "customer-proxy")
    assert "no presentation" in report["reason"]
    assert report["gate"]["verdict"] == "return" and report["gate"]["now_at"] == "e2e"
    assert (s.step, s.rounds, s.status) == ("e2e", 1, StoryStatus.ACTIVE)
    assert q.calls == [] and prepared == [] and rt.ledger.total() == 0


def test_return_is_logged_and_saved(make_runtime, configured: Path) -> None:
    rt = make_runtime()
    open_story(rt, "acceptance")
    run(rt, "customer-proxy", story="s1")
    [event] = gate_events(rt)
    assert (event.role, event.story) == ("customer-proxy", "s1")
    assert event.data["verdict"] == "return" and event.data["now_at"] == "e2e"
    from agile_team import state as state_mod

    assert state_mod.load(rt.config.run_dir).stories["s1"].step == "e2e"


def test_unpresented_return_comes_after_the_refusals(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "acceptance", sprint=None)
    assert run(rt, "customer-proxy", story="s1")["status"] == "refused"
    open_story(rt, "acceptance", status=StoryStatus.DONE)
    assert run(rt, "customer-proxy", story="s1")["status"] == "refused"
    open_story(rt, "e2e")
    assert run(rt, "customer-proxy", story="s1")["status"] == "refused"


def test_returned_story_is_presented_then_reaches_acceptance(make_runtime) -> None:
    def tester_builds() -> None:
        present(rt.config)

    rt = make_runtime(FakeQuery(action=tester_builds))
    s = open_story(rt, "acceptance")
    assert run(rt, "customer-proxy", story="s1")["status"] == "returned"
    report = run(rt, "integration-tester", story="s1")
    assert report["gate"]["verdict"] == "pass" and s.step == "acceptance" and s.rounds == 0


def test_no_e2e_step_runs_the_proxy_as_today(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    rt.pipeline.steps = [x for x in rt.pipeline.steps if x != "e2e"]
    open_story(rt, "acceptance")
    report = run(rt, "customer-proxy", story="s1")
    assert report["status"] == "done" and len(q.calls) == 1
    assert "What the team presents" not in q.calls[0]["prompt"]


def test_proxy_gets_the_copy_and_the_guide_in_its_prompt(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    open_story(rt, "acceptance")
    present(rt.config)
    run(rt, "customer-proxy", story="s1")
    box = rt.config.run_dir / "customer/cli"
    assert (box / "presentation/workspace/todo.txt").read_text() == "milk\n"
    prompt = q.calls[0]["prompt"]
    assert "## What the team presents" in prompt and str(box / "presentation") in prompt
    assert GUIDE_TEXT.strip() in prompt
    assert prompt.index("How the customer reaches") < prompt.index("What the team presents")


def test_prepare_receives_the_order_with_the_presentation_source(make_runtime) -> None:
    orders = []

    def fake_prepare(config, order):
        orders.append(order)
        return sandbox.Preparer().prepare(config, order)

    rt = make_runtime(FakeQuery(), prepare_fn=fake_prepare)
    open_story(rt, "acceptance")
    source = present(rt.config)
    run(rt, "customer-proxy", story="s1")
    assert orders[0].presentation == source and orders[0].delivery.name == "cli"


def test_without_a_presentation_dir_the_order_carries_none(make_runtime) -> None:
    orders = []

    def fake_prepare(config, order):
        orders.append(order)
        return sandbox.Preparer().prepare(config, order)

    rt = make_runtime(FakeQuery(), prepare_fn=fake_prepare)
    rt.pipeline.steps = [x for x in rt.pipeline.steps if x != "e2e"]
    open_story(rt, "acceptance")
    run(rt, "customer-proxy", story="s1")
    assert orders[0].presentation is None
    assert not (rt.config.run_dir / "customer/cli/presentation").exists()


def test_integration_tester_gets_a_fresh_presentation_to_fill(make_runtime) -> None:
    seen = {}
    rt = make_runtime()
    source = present(rt.config)
    (source / "stale.txt").write_text("old")

    def build() -> None:
        seen["stale"] = (source / "stale.txt").exists()
        seen["git"] = (source / "workspace/.git").exists()
        seen["old"] = (source / "PRESENTATION.md").exists()
        present(rt.config)

    rt.query_fn = FakeQuery(action=build)
    s = open_story(rt, "e2e")
    report = run(rt, "integration-tester", story="s1")
    assert seen == {"stale": False, "git": True, "old": False}
    assert report["gate"]["verdict"] == "pass" and s.step == "acceptance"


def test_e2e_done_without_presentation_bounces_to_e2e(make_runtime) -> None:
    rt = make_runtime(FakeQuery(action=lambda: None))
    s = open_story(rt, "e2e")
    report = run(rt, "integration-tester", story="s1")
    assert report["gate"]["verdict"] == "bounce" and "no presentation" in report["gate"]["reason"]
    assert (s.step, s.rounds) == ("e2e", 1)


def test_e2e_with_only_the_empty_workspace_bounces(make_runtime) -> None:
    def guide_only() -> None:
        (rt.config.run_dir / "presentation/s1/PRESENTATION.md").write_text(GUIDE_TEXT)

    rt = make_runtime(FakeQuery(action=guide_only))
    s = open_story(rt, "e2e")
    report = run(rt, "integration-tester", story="s1")
    assert "workspace is missing or empty" in report["gate"]["reason"] and s.rounds == 1


def test_e2e_for_an_unsafe_story_id_is_refused_before_wiping(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    (rt.config.run_dir / "x").mkdir(parents=True)
    (rt.config.run_dir / "x/keep.txt").write_text("keep")
    rt.state.stories["../x"] = gates.StoryState("../x", "Bad", "e2e", sprint=1)
    report = run(rt, "integration-tester", story="../x")
    assert report["status"] == "refused" and "must match" in report["reason"]
    assert (rt.config.run_dir / "x/keep.txt").exists() and q.calls == []


def test_integration_tester_may_write_the_presentation(make_runtime) -> None:
    rt = make_runtime()
    scope = rt.scope_for(rt.resolve("integration-tester"))
    ok = [
        ".team/run/presentation/s4/PRESENTATION.md",
        ".team/run/presentation/s4/workspace/.team/run/state.json",
        "tests/e2e/test_x.py",
    ]
    for path in ok:
        assert guard.check_tool_use(scope, guard.ToolCall("Write", {"file_path": path})) is None
    assert guard.check_tool_use(scope, guard.ToolCall("Write", {"file_path": "src/app.py"}))


def test_other_roles_may_not_write_the_presentation(make_runtime) -> None:
    rt = make_runtime()
    scope = rt.scope_for(rt.resolve("developer-cli"))
    path = ".team/run/presentation/s4/PRESENTATION.md"
    assert guard.check_tool_use(scope, guard.ToolCall("Write", {"file_path": path}))


def test_web_proxy_keeps_read_to_rewrite_its_report(make_runtime) -> None:
    q = FakeQuery()

    def fake_prepare(config, order):
        kind = sandbox.DELIVERY_KINDS["web"]
        return sandbox.Prepared(order.delivery, kind, config.repo, config.run_dir, config.run_dir)

    rt = make_runtime(q, prepare_fn=fake_prepare)
    rt.config.deliveries = [Delivery("ui", "web", url="http://x")]
    open_story(rt, "acceptance")
    present(rt.config)
    run(rt, "customer-proxy", story="s1")
    assert "Read" in q.calls[0]["options"].tools


# ----- s19: holds, previous step, scribe queue, developer pick -------------------


class Raising:
    """A fake query that raises ``exc`` when its stream starts."""

    def __init__(self, exc: BaseException):
        self.exc = exc

    def __call__(self, *, prompt: str, options):
        async def gen():
            raise self.exc
            yield  # pragma: no cover

        return gen()


def blocked(**extra):
    return handoff("blocked", summary="need a db", **extra)


def test_a_stopped_report_holds_the_story(make_runtime) -> None:
    rt = make_runtime(FakeQuery(blocked()))
    s = open_story(rt)
    report = run(rt, "architect", story="s1")
    assert report["status"] == "blocked" and s.hold == "stopped"
    assert dispatch.state_mod.load(rt.config.run_dir).stories["s1"].hold == "stopped"


def test_several_triggers_join_into_the_hold(make_runtime) -> None:
    rt = make_runtime(FakeQuery(blocked(open_questions=["why?"])))
    s = open_story(rt)
    run(rt, "architect", story="s1")
    assert s.hold == "stopped, questions"


def test_a_clean_po_step_clears_the_hold(make_runtime) -> None:
    rt = make_runtime(FakeQuery())
    s = open_story(rt, hold="stopped", note="keep")
    run(rt, "architect", story="s1")
    assert s.hold is None


def test_a_story_less_step_has_no_hold_to_set(make_runtime) -> None:
    rt = make_runtime(FakeQuery(blocked()))
    report = run(rt, "architect")
    assert report["status"] == "blocked"


def test_a_refused_po_step_leaves_state_events_and_hold_alone(make_runtime) -> None:
    rt = make_runtime()
    s = open_story(rt, hold="stopped")
    rt.save()
    (rt.config.run_dir / STOP_FILE).write_text("")
    before = (rt.state.to_json(), len(rt.events.events()))
    assert run(rt, "architect", story="s1")["status"] == "refused"
    assert (rt.state.to_json(), len(rt.events.events())) == before and s.hold == "stopped"


def test_a_halted_step_does_not_touch_the_hold(make_runtime) -> None:
    limit = RuntimeError("You've hit your session limit · resets 2pm (UTC)")
    rt = make_runtime(Raising(limit))
    s = open_story(rt, hold="stopped")
    assert run(rt, "architect", story="s1")["status"] == "halted"
    assert s.hold == "stopped" and s.previous is None


def test_a_gated_step_records_the_previous_step(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", summary="designed")))
    s = open_story(rt)
    run(rt, "architect", story="s1")
    assert s.previous == gates.PreviousStep("architect", "done", "designed", "pass", "", None)


def test_a_bounce_is_recorded_with_its_reason_and_next_role(make_runtime) -> None:
    text = handoff("changes_requested", summary="too long", next_role="developer-gui")
    rt = make_runtime(FakeQuery(text))
    s = open_story(rt, "review")
    run(rt, "code-reviewer", story="s1")
    prev = s.previous
    assert (prev.role, prev.status, prev.summary) == (
        "code-reviewer",
        "changes_requested",
        "too long",
    )
    assert (prev.verdict, prev.reason, prev.next_role) == ("bounce", "too long", "developer-gui")


def test_a_bad_handoff_is_recorded_as_a_bounce(make_runtime) -> None:
    rt = make_runtime(FakeQuery("no block"))
    s = open_story(rt, "tests")
    run(rt, "unit-tester", story="s1")
    assert (s.previous.status, s.previous.verdict) == ("bad_handoff", "bounce")
    assert s.previous.reason


def test_a_return_is_recorded_as_the_previous_step(make_runtime) -> None:
    rt = make_runtime()
    s = open_story(rt, "acceptance")
    run(rt, "customer-proxy", story="s1")
    assert (s.previous.role, s.previous.status, s.previous.verdict) == (
        "customer-proxy",
        "returned",
        "return",
    )


def test_ungated_roles_leave_previous_alone(make_runtime) -> None:
    rt = make_runtime(FakeQuery("no block"))
    keep = gates.PreviousStep("architect", "done")
    s = open_story(rt, "review", status=StoryStatus.DONE, previous=keep)
    run(rt, "scribe", story="s1")
    assert s.previous is keep


def test_note_step_ignores_reports_with_no_gate(make_runtime) -> None:
    rt = make_runtime()
    keep = gates.PreviousStep("architect", "done")
    s = open_story(rt, previous=keep)
    rt.note_step(s, {"role": "architect", "status": "done"})
    assert s.previous is keep and s.hold is None


def test_note_step_sets_and_clears_the_hold(make_runtime) -> None:
    rt = make_runtime()
    s = open_story(rt)
    rt.note_step(s, {"role": "architect", "status": "refused", "reason": "r"})
    assert s.hold == "refused"
    rt.note_step(s, {"role": "architect", "status": "done"})
    assert s.hold is None


def test_note_step_removes_the_story_from_the_scribe_queue(make_runtime) -> None:
    rt = make_runtime()
    s = open_story(rt, "review", status=StoryStatus.DONE)
    rt.state.scribe_due = ["s1", "s2"]
    rt.note_step(s, {"role": "architect", "status": "done"})
    assert rt.state.scribe_due == ["s1", "s2"]
    rt.note_step(s, {"role": "scribe", "status": "bad_handoff", "reason": "r"})
    assert rt.state.scribe_due == ["s2"]
    rt.note_step(s, {"role": "scribe", "status": "done"})
    assert rt.state.scribe_due == ["s2"]


def test_a_story_reaching_done_queues_the_scribe(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "review")
    rt.pipeline.steps = ["review"]
    run(rt, "code-reviewer", story="s1")
    assert rt.state.stories["s1"].status is StoryStatus.DONE
    assert rt.state.scribe_due == ["s1"]


def test_a_story_that_is_not_done_is_not_queued(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "design")
    run(rt, "architect", story="s1")
    assert rt.state.scribe_due == []


def test_running_the_scribe_dequeues_it(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "review", status=StoryStatus.DONE)
    rt.state.scribe_due = ["s1"]
    run(rt, "scribe", story="s1")
    assert rt.state.scribe_due == []


def test_the_architect_names_the_developer(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", developer="developer-cli")))
    s = open_story(rt)
    run(rt, "architect", story="s1")
    assert s.developer == "developer-cli"


@pytest.mark.parametrize("developer", [None, ""])
def test_an_empty_developer_changes_nothing(make_runtime, developer) -> None:
    rt = make_runtime(FakeQuery(handoff("done", developer=developer)))
    s = open_story(rt, developer="developer-api")
    run(rt, "architect", story="s1")
    assert s.developer == "developer-api"


def test_another_roles_developer_field_is_ignored(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", developer="developer-gui")))
    s = open_story(rt, "review")
    run(rt, "code-reviewer", story="s1")
    assert s.developer is None


def test_an_architect_without_a_story_has_nowhere_to_put_it(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", developer="developer-cli")))
    assert run(rt, "architect")["status"] == "done"


def test_a_non_string_developer_is_a_bad_handoff(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", developer=3)))
    s = open_story(rt)
    report = run(rt, "architect", story="s1")
    assert report["status"] == "bad_handoff" and "developer must be a role name" in report["reason"]
    assert s.developer is None


def test_the_step_end_event_shape_does_not_gain_a_developer(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", developer="developer-cli")))
    open_story(rt)
    run(rt, "architect", story="s1")
    [end] = [e for e in rt.events.events() if e.kind == "step-end"]
    assert "developer" not in end.data
