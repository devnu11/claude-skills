"""s1: the traced design gate, the trace state, the check command, the briefs, the role files."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import cli, gates, revert_log, reverts, system
from agile_team import config as config_mod
from agile_team import requirements as rq
from agile_team.roles import Handoff
from agile_team.state import RunState

from .conftest import FakeQuery, write_story
from .test_dispatch import open_story, run

HEAD = "s1's ACs must be traced to active requirements in docs/requirements/ before design passes:"


def req_text(id: str = "REQ-001", covers: str = '["s1/AC1"]', status: str = "active") -> str:
    return f"---\nid: {id}\ntitle: Title {id}\nstatus: {status}\ncovers: {covers}\n---\n\nWords.\n"


def write_req(repo: Path, n: int, **kw: Any) -> None:
    folder = repo / "docs" / "requirements"
    system.make_dirs(folder)
    kw.setdefault("id", f"REQ-{n:03d}")
    system.write_text(folder / f"REQ-{n:03d}.md", req_text(**kw))


def cli_run(repo: Path, capsys) -> tuple[int, dict[str, Any]]:
    code = cli.main(["--repo", str(repo), "requirements", "check"])
    return code, json.loads(capsys.readouterr().out)


# ---- the gate (T9-T11)


def gate_story(make_runtime, reasons, **kw):
    rt = make_runtime()
    story = open_story(rt, "design", **kw)
    calls: list[str] = []

    def traced(sid: str) -> list[str]:
        calls.append(sid)
        return list(reasons)

    rt.pipeline.checks.traced = traced
    return rt, story, calls


def revert_setup(rt, story, design_text: str) -> None:
    """Mark the story reverted once, with a design file holding ``design_text``."""
    story.reverted = [revert_log.RevertEntry("2026-01-01", 1, "r", ["a" * 40], "b" * 40)]
    rt.pipeline.checks.design_file = lambda sid: f"docs/design/{sid}.md"
    rt.pipeline.checks.read = lambda path: design_text


def test_checked_story_with_untraced_ac_bounces_to_design(make_runtime) -> None:
    reasons = [HEAD, "- s1/AC2 is covered by no active requirement; add it"]
    rt, story, calls = gate_story(make_runtime, reasons)
    out = rt.pipeline.evaluate(story, Handoff("done"))
    assert out.verdict is gates.Verdict.BOUNCE and out.bounce_to == "design"
    assert out.author is gates.Author.ROLE
    assert out.reason == "\n".join(reasons)
    assert calls == ["s1"]


def test_a_bounce_counts_a_round(make_runtime) -> None:
    rt, story, _ = gate_story(make_runtime, [HEAD, "- x"])
    report = run(rt, "architect", story="s1")
    assert report["gate"]["verdict"] == "bounce"
    assert story.rounds == 1 and story.step == "design"


def test_traced_story_passes(make_runtime) -> None:
    rt, story, _ = gate_story(make_runtime, [])
    assert rt.pipeline.evaluate(story, Handoff("done")).verdict is gates.Verdict.PASS


def test_exempt_story_passes_without_asking_for_the_trace(make_runtime) -> None:
    rt, story, calls = gate_story(make_runtime, [HEAD, "- x"], trace=gates.Trace.EXEMPT)
    assert rt.pipeline.evaluate(story, Handoff("done")).verdict is gates.Verdict.PASS
    assert calls == []


def test_the_gate_runs_only_at_the_design_step(make_runtime) -> None:
    rt, story, calls = gate_story(make_runtime, ["- x"])
    story.step = "tests"
    rt.pipeline.evaluate(story, Handoff("done"))
    assert calls == []


def test_a_reverted_story_lists_the_revert_reason_then_the_trace(make_runtime) -> None:
    rt, story, _ = gate_story(make_runtime, [HEAD, "- s1/AC1 untraced"])
    revert_setup(rt, story, "# s1\n\nnothing\n")
    out = rt.pipeline.evaluate(story, Handoff("done"))
    missing = gates.REDESIGN_MISSING.format(id="s1", count=1, file="docs/design/s1.md")
    assert out.verdict is gates.Verdict.BOUNCE
    assert out.reason == "\n".join([missing, HEAD, "- s1/AC1 untraced"])


def test_a_reverted_exempt_story_still_needs_its_redesign_section(make_runtime) -> None:
    rt, story, calls = gate_story(make_runtime, ["- x"], trace=gates.Trace.EXEMPT)
    revert_setup(rt, story, "# s1\n\nnothing\n")
    out = rt.pipeline.evaluate(story, Handoff("done"))
    assert out.reason == gates.REDESIGN_MISSING.format(id="s1", count=1, file="docs/design/s1.md")
    assert calls == []


def test_a_reverted_story_with_section_and_trace_passes(make_runtime) -> None:
    rt, story, _ = gate_story(make_runtime, [])
    revert_setup(rt, story, "# s1\n\n## After revert 1\n\nchanges\n")
    assert rt.pipeline.evaluate(story, Handoff("done")).verdict is gates.Verdict.PASS


def test_default_checks_find_no_reasons() -> None:
    assert gates.Checks.traced is not None
    assert gates.Trace.CHECKED == "checked" and gates.Trace.EXEMPT == "exempt"


# ---- the trace state (T9)


def loaded(**story: Any) -> gates.StoryState:
    data = {"id": "s1", "title": "t", "step": "design", **story}
    return RunState.from_json(json.dumps({"stories": {"s1": data}})).stories["s1"]


def test_new_story_is_checked() -> None:
    assert gates.StoryState("s1", "t", "design").trace is gates.Trace.CHECKED


def test_saved_without_trace_at_design_never_designed_is_checked() -> None:
    assert loaded().trace is gates.Trace.CHECKED


def test_saved_without_trace_at_design_after_a_step_is_exempt() -> None:
    previous = {"role": "developer", "status": "done"}
    assert loaded(previous=previous).trace is gates.Trace.EXEMPT


@pytest.mark.parametrize("step", ["implement", "tests", "review", "done"])
def test_saved_without_trace_past_design_is_exempt(step: str) -> None:
    assert loaded(step=step).trace is gates.Trace.EXEMPT


def test_a_saved_trace_wins_over_the_legacy_rule() -> None:
    assert loaded(step="implement", trace="checked").trace is gates.Trace.CHECKED
    assert loaded(trace="exempt").trace is gates.Trace.EXEMPT


def test_trace_round_trips_through_json() -> None:
    story = gates.StoryState("s1", "t", "implement", trace=gates.Trace.EXEMPT)
    state = RunState(stories={"s1": story})
    assert RunState.from_json(state.to_json()).stories["s1"].trace is gates.Trace.EXEMPT


def test_reverted_story_keeps_its_trace() -> None:
    story = gates.StoryState("s1", "t", "implement", trace=gates.Trace.EXEMPT)
    entry = revert_log.RevertEntry("2026-01-01", 1, "why", [], "abc")
    back = reverts.Back("implement", entry, [])
    assert reverts.reverted_story(story, back).trace is gates.Trace.EXEMPT


# ---- make_pipeline reads the repo's files (T10, T12)


def test_pipeline_traced_reads_the_repo(configured: Path) -> None:
    config = config_mod.load(configured)
    write_story(config, "s1", "cli", "cli")
    write_req(configured, 1, covers='["s1/AC1"]')
    reasons = cli.make_pipeline(config).checks.traced("s1")
    assert reasons == [
        HEAD,
        "- s1/AC2 is covered by no active requirement; "
        "add it to an active REQ's covers or write a new REQ-NNN.md",
    ]


def test_pipeline_traced_is_empty_when_everything_is_covered(configured: Path) -> None:
    config = config_mod.load(configured)
    write_story(config, "s1", "cli")
    write_req(configured, 1)
    assert cli.make_pipeline(config).checks.traced("s1") == []


# ---- the command (T6-T8)


def test_check_on_a_clean_repo(configured: Path, capsys) -> None:
    config = config_mod.load(configured)
    write_story(config, "s1", "cli", "cli")
    write_story(config, "s2", "cli")
    write_req(configured, 1, covers='["s1/AC1"]')
    system.write_text(config.stories_dir / "s100.md", "---\nid: s100\ntitle: old\n---\nbody\n")
    code, out = cli_run(configured, capsys)
    assert code == 0
    assert list(out) == ["problems", "coverage", "unreadable"]
    assert out["problems"] == []
    assert out["coverage"] == {"s1": {"AC1": ["REQ-001"], "AC2": []}, "s2": {"AC1": []}}
    assert list(out["unreadable"]) == ["s100"]
    assert out["unreadable"]["s100"][0].startswith(".team/stories/s100.md")


def test_check_prints_indented_json(configured: Path, capsys) -> None:
    cli.main(["--repo", str(configured), "requirements", "check"])
    assert capsys.readouterr().out.startswith("{\n  ")


def test_check_with_a_bad_file_exits_1_and_still_reports(configured: Path, capsys) -> None:
    config = config_mod.load(configured)
    write_story(config, "s1", "cli")
    write_req(configured, 1)
    write_req(configured, 7, status="draft")
    code, out = cli_run(configured, capsys)
    assert code == 1
    assert out["problems"] == [
        "docs/requirements/REQ-007.md: status is 'draft'; use active or retired"
    ]
    assert out["coverage"] == {"s1": {"AC1": ["REQ-001"]}}


def test_check_reports_a_ref_to_an_unknown_story(configured: Path, capsys) -> None:
    write_req(configured, 1, covers='["s9/AC1"]')
    code, out = cli_run(configured, capsys)
    assert code == 1
    assert "no story file for s9" in out["problems"][0]


def test_check_without_a_requirements_folder(configured: Path, capsys) -> None:
    config = config_mod.load(configured)
    write_story(config, "s1", "cli", "cli")
    code, out = cli_run(configured, capsys)
    assert code == 0
    assert out == {"problems": [], "coverage": {"s1": {"AC1": [], "AC2": []}}, "unreadable": {}}


def test_an_unreadable_requirement_file_is_reported_not_raised(
    configured: Path, monkeypatch
) -> None:
    config = config_mod.load(configured)
    write_req(configured, 1)

    def broken(path):
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")

    monkeypatch.setattr(rq.system, "read_text", broken)
    [source] = rq.sources(config)
    assert source == rq.Source("docs/requirements/REQ-001.md", None)


def test_requirements_command_is_registered_after_config() -> None:
    names = [c.name for c in cli.COMMANDS]
    assert names.index("requirements") == names.index("config") + 1


# ---- the briefs (T13)


def seed_requirements(rt) -> None:
    write_req(rt.config.repo, 1, covers='["s1/AC1"]')


def architect_prompt(make_runtime, trace=gates.Trace.CHECKED) -> str:
    q = FakeQuery()
    rt = make_runtime(q)
    open_story(rt, "design", trace=trace)
    seed_requirements(rt)
    run(rt, "architect", story="s1")
    return q.calls[0]["prompt"]


def test_architect_brief_has_coverage_index_and_next_id(make_runtime) -> None:
    prompt = architect_prompt(make_runtime)
    assert "## Requirements" in prompt
    assert "- AC1: REQ-001 (Title REQ-001)" in prompt
    assert "- REQ-001 Title REQ-001: s1/AC1" in prompt
    assert "write REQ-002.md, the next free id" in prompt


def test_exempt_story_brief_has_no_section(make_runtime) -> None:
    assert "## Requirements" not in architect_prompt(make_runtime, gates.Trace.EXEMPT)


def attach(rt, role: str, trace=gates.Trace.CHECKED) -> SimpleNamespace:
    story = open_story(rt, "design", trace=trace)
    seed_requirements(rt)
    plan = SimpleNamespace(role=SimpleNamespace(name=role), story=story, prompt="brief")
    rt._attach_requirements(plan)
    return plan


@pytest.mark.parametrize("role", ["code-reviewer", "customer-proxy"])
def test_reviewer_and_proxy_get_coverage_only(make_runtime, role: str) -> None:
    plan = attach(make_runtime(), role)
    assert plan.prompt.startswith("brief\n\n## Requirements")
    assert "- AC1: REQ-001 (Title REQ-001)" in plan.prompt
    assert "next free id" not in plan.prompt


@pytest.mark.parametrize("role", ["code-reviewer", "customer-proxy", "architect"])
def test_exempt_story_gets_no_section_for_any_role(make_runtime, role: str) -> None:
    assert attach(make_runtime(), role, gates.Trace.EXEMPT).prompt == "brief"


@pytest.mark.parametrize("role", ["developer-cli", "devops", "tester", "integration-tester"])
def test_other_roles_get_no_section(make_runtime, role: str) -> None:
    assert attach(make_runtime(), role).prompt == "brief"


# ---- the role files (T14)

ROLES = Path(cli.__file__).parent / "roles"
ARCHITECT = (ROLES / "architect.md").read_text()
REVIEWER = (ROLES / "code-reviewer.md").read_text()
PROXY = (ROLES / "customer-proxy.md").read_text()


def test_architect_file_describes_the_requirement_files() -> None:
    assert "requirements/REQ-NNN.md" in ARCHITECT
    assert "`requirements.md`" not in ARCHITECT
    assert "covers" in ARCHITECT and "## Requirements" in ARCHITECT
    assert "status: retired" in ARCHITECT


def test_reviewer_file_asks_for_ac_and_requirement_ids() -> None:
    assert "requirement" in REVIEWER and "## Requirements" in REVIEWER
    assert "s7/AC2" in REVIEWER and "REQ-004" in REVIEWER


def test_proxy_file_asks_for_ac_and_requirement_ids() -> None:
    assert "## Requirements" in PROXY and "AC id" in PROXY and "requirement ids" in PROXY
