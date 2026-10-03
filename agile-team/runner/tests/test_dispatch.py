"""run_role end to end against a real repo with a fake query()."""

import asyncio
from pathlib import Path

import pytest
from agile_team import dispatch, gates, sandbox
from agile_team.config import Delivery
from agile_team.state import STOP_FILE, ModelOverride
from claude_agent_sdk import AssistantMessage, TextBlock

from .conftest import FakeQuery, FakeRunner, git, handoff


def run(rt, role, brief="go", story=None):
    return asyncio.run(rt.run_role(role, brief, story))


def open_story(rt, step="design", **kw):
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

    result = asyncio.run(dispatch.collect(fake, "p", None))
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
    rt.state.status, rt.state.cadence = "sprint-end", "sprint"
    assert "the run is sprint-end" in run(rt, "architect")["reason"]
    rt.state.status = "running"
    rt.config.run_dir.mkdir(parents=True, exist_ok=True)
    (rt.config.run_dir / STOP_FILE).touch()
    assert "stop was requested" in run(rt, "architect")["reason"]


def test_storyless_step_commits_chore(make_runtime, configured: Path) -> None:
    rt = make_runtime(FakeQuery(action=write(configured, "docs/architecture.md")))
    report = run(rt, "architect")
    assert report["status"] == "done" and report["commit"]
    assert git(configured, "log", "-1", "--format=%s").strip() == "chore(team): architect step"
    assert rt.ledger.total() == pytest.approx(0.1)


def test_story_commits_feat_then_fixup(make_runtime, configured: Path) -> None:
    runner = FakeRunner({"pytest": (1, "")})
    q = FakeQuery(action=write(configured, "docs/design.md"))
    rt = make_runtime(q, runner)
    open_story(rt)
    first = run(rt, "architect", story="s1")
    assert first["gate"]["now_at"] == "tests"
    q.action = write(configured, "tests/test_todo.py")
    second = run(rt, "unit-tester", story="s1")
    assert second["gate"]["passed"] and second["gate"]["now_at"] == "implement"
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
    assert report["gate"]["passed"]


def test_failed_gate_bounces_and_caps(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("changes_requested", next_role="developer")))
    open_story(rt, "review")
    for _ in range(3):
        rt.state.stories["s1"].step = "review"
        report = run(rt, "code-reviewer", story="s1")
    assert report["gate"]["needs_manager"]
    rt.state.stories["s1"].step = "review"
    assert "round cap" in run(rt, "code-reviewer", story="s1")["reason"]


def test_manager_rules_on_capped_story(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff("done", ruling="revise_design")))
    open_story(rt, "implement", rounds=3, needs_manager=True)
    rt.state.manager_due.append("round cap")
    rt.state.overrides["developer"] = ModelOverride("opus", "high", "stuck")
    report = run(rt, "manager", story="s1")
    assert report["status"] == "done"
    s = rt.state.stories["s1"]
    assert (s.step, s.needs_manager, s.rounds) == ("design", False, 0)
    assert rt.state.manager_due == [] and rt.state.overrides["developer"].reviewed
    prompt = rt.query_fn.calls[0]["prompt"]
    assert "unreviewed_overrides" in prompt and "stuck" in prompt


def test_bad_handoff_bounces(make_runtime) -> None:
    rt = make_runtime(FakeQuery("no handoff here"))
    open_story(rt, "review")
    report = run(rt, "code-reviewer", story="s1")
    assert report["status"] == "bad_handoff"
    assert rt.state.stories["s1"].rounds == 1
    assert run(rt, "architect")["status"] == "bad_handoff"


def test_budget_checkpoint_queues_manager(make_runtime) -> None:
    rt = make_runtime(FakeQuery(cost=6.0))
    run(rt, "architect")
    assert rt.state.manager_due and "budget checkpoint" in rt.state.manager_due[0]


def test_model_override_applies(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    rt.state.overrides["architect"] = ModelOverride("haiku", "low", "cheap", reviewed=True)
    run(rt, "architect")
    assert q.calls[0]["options"].model == "haiku"


def test_customer_proxy_runs_in_sandbox(make_runtime, configured: Path) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    open_story(rt, "acceptance")
    report = run(rt, "customer-proxy", story="s1")
    opts = q.calls[0]["options"]
    assert opts.cwd.endswith(".team/run/customer/cli")
    assert '"denyRead"' in opts.settings
    assert "How the customer reaches the product" in q.calls[0]["prompt"]
    assert report["gate"]["now_at"] == "done"


def test_customer_proxy_without_delivery(make_runtime) -> None:
    rt = make_runtime()
    rt.config.deliveries = []
    open_story(rt, "acceptance")
    assert "no [[delivery]]" in run(rt, "customer-proxy", story="s1")["reason"]


def test_manual_acceptance_script_reaches_outbox(make_runtime) -> None:
    script = "1. Plug in the device.\n" + handoff("done")
    rt = make_runtime(FakeQuery(script))
    rt.config.deliveries = [Delivery("hw", "manual")]
    open_story(rt, "acceptance")
    report = run(rt, "customer-proxy", story="s1")
    [question] = rt.relay.open_questions()
    assert question.id == report["question_id"]
    assert "Plug in the device" in question.text and question.stories == ["s1"]
    assert rt.query_fn.calls[0]["options"].tools == ["Write"]


def test_web_proxy_gets_browser(make_runtime) -> None:
    q = FakeQuery()
    stopped = []

    def fake_prepare(config, delivery):
        p = sandbox.Prepared(
            delivery, sandbox.DELIVERY_KINDS["web"], config.run_dir, config.run_dir, {}
        )
        p.stop = lambda: stopped.append(True)  # type: ignore[method-assign]
        return p

    rt = make_runtime(q, prepare_fn=fake_prepare)
    rt.config.deliveries = [Delivery("ui", "web", url="http://localhost:3000")]
    open_story(rt, "acceptance")
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
def test_run_halted(make_runtime, status, cadence, halted) -> None:
    rt = make_runtime()
    rt.state.status, rt.state.cadence = status, cadence
    assert rt.run_halted() is halted


def test_po_story_edits_committed_before_next_role(make_runtime, configured: Path) -> None:
    rt = make_runtime(FakeQuery(action=write(configured, "docs/a.md")))
    write(configured, ".team/stories/s1.md", "As a user…")()
    run(rt, "architect")
    log = git(configured, "log", "--format=%s", "-2").splitlines()
    assert log == ["chore(team): architect step", "chore(team): product-owner step"]
    assert "s1.md" in git(configured, "show", "--name-only", "--format=", "HEAD~1")
    assert rt.git.is_clean()
