"""s120: shared files in the gates, briefs, Proxy scope and router (S9-S12; AC2, AC3)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from agile_team import gates, sandbox, shares, system
from agile_team.config import PIPELINE_STEPS, Environment
from agile_team.gates import Verdict
from agile_team.roles import Handoff
from agile_team.router import Router
from agile_team.sharing import Sharer, Shares

from .conftest import FakeRunner
from .test_dispatch import open_story
from .test_s120_shares import BYTES, DESIGN, SHA, STORY, entry

OTHER = "f" * 64
FILES = "\n## Files\n\n- src/a.py\n"
PATH = f"{DESIGN}s1-mock.html"


def listed(*names: str) -> shares.Listed:
    return shares.Listed(tuple(entry(n) for n in names))


def pipe(check: shares.Check, design_text: str = "", names=("cli",)) -> gates.Pipeline:
    checks = gates.Checks({"test": "T", "coverage": "C"}, 95.0, FakeRunner(None), None)
    checks.environments = lambda _story: list(names)
    checks.shares = lambda _story: check
    checks.design_file = lambda story: f"docs/design/{story}.md"
    sections = "".join(f"## Environment: {n}\n" for n in names)
    checks.read = lambda path: design_text if path.startswith("docs/design/") else sections
    return gates.Pipeline(list(PIPELINE_STEPS), 3, checks)


def at(step: str, **kw) -> gates.StoryState:
    return gates.StoryState("s1", "T", step, sprint=1, **kw)


# ----- the default Checks (nothing shared) ------------------------------------------


def test_checks_share_nothing_by_default() -> None:
    checks = gates.Checks({"test": "T", "coverage": "C"}, 95.0, FakeRunner(None), None)
    assert checks.shares("s1") == shares.Check(shares.Listed())


# ----- S12: the acceptance hash check -----------------------------------------------


def test_acceptance_passes_with_intact_files_and_goes_on_as_before() -> None:
    p = pipe(shares.Check(listed("mock.html")))
    out = p.evaluate(at("acceptance"), Handoff("done"))
    assert out.verdict is Verdict.PASS


def test_acceptance_without_shared_files_is_as_before() -> None:
    assert (
        pipe(shares.Check(shares.Listed())).evaluate(at("acceptance"), Handoff("done")).verdict
        is Verdict.PASS
    )


def test_a_changed_file_bounces_to_design_with_the_changed_text() -> None:
    line = shares.CHANGED_LINE.format(path=PATH, found=OTHER[:12], recorded=SHA[:12])
    p = pipe(shares.Check(listed("mock.html"), (line,)))
    out = p.evaluate(at("acceptance"), Handoff("done"))
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "design"
    assert out.author is gates.Author.ROLE
    assert out.reason == shares.CHANGED.format(story="s1", lines=line)
    assert out.reason.startswith("shared files changed since the liaison shared them:\n- ")
    assert "Restore each to its shared version (the `chore(s1): share …` commit)" in out.reason


def test_a_missing_file_bounces_too() -> None:
    line = shares.MISSING_LINE.format(path=PATH, recorded=SHA[:12])
    out = pipe(shares.Check(listed("mock.html"), (line,))).evaluate(
        at("acceptance"), Handoff("done")
    )
    assert out.verdict is Verdict.BOUNCE and line in out.reason


def test_every_changed_file_is_listed_in_one_bounce() -> None:
    lines = (
        shares.CHANGED_LINE.format(path="a", found="1" * 12, recorded="2" * 12),
        shares.MISSING_LINE.format(path="b", recorded="3" * 12),
    )
    out = pipe(shares.Check(listed("a", "b"), lines)).evaluate(at("acceptance"), Handoff("done"))
    assert "\n".join(lines) in out.reason


def test_the_hash_check_wins_over_a_handoff_that_says_changes_requested() -> None:
    line = shares.MISSING_LINE.format(path=PATH, recorded=SHA[:12])
    handoff = Handoff("changes_requested", "broken", next_role="developer", failed_acs=["AC1"])
    out = pipe(shares.Check(listed("mock.html"), (line,))).evaluate(at("acceptance"), handoff)
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "design" and line in out.reason


def test_a_changed_file_bounces_even_with_no_environments() -> None:
    line = shares.MISSING_LINE.format(path=PATH, recorded=SHA[:12])
    out = pipe(shares.Check(listed("mock.html"), (line,)), names=()).evaluate(
        at("acceptance"), Handoff("done")
    )
    assert out.verdict is Verdict.BOUNCE


def test_a_malformed_shared_list_holds_with_the_story_file_text() -> None:
    problem = ".team/stories/s1.md: shared: not a list"
    out = pipe(shares.Check(shares.Listed(problems=(problem,)))).evaluate(
        at("acceptance"), Handoff("done")
    )
    assert out.verdict is Verdict.HOLD
    from agile_team import story_spec

    assert out.reason == story_spec.STORY_FILE_HOLD.format(refusal=problem)


def test_the_check_is_for_the_acceptance_step_only() -> None:
    line = shares.MISSING_LINE.format(path=PATH, recorded=SHA[:12])
    p = pipe(shares.Check(listed("mock.html"), (line,)))
    assert shares.CHANGED.split("\n")[0] not in p.evaluate(at("tests"), Handoff("done")).reason


# ----- S10: the design gate ---------------------------------------------------------


def test_a_design_that_names_every_shared_path_passes() -> None:
    text = f"## Shared files\n\n- {PATH}\n" + FILES
    out = pipe(shares.Check(listed("mock.html")), text).evaluate(at("design"), Handoff("done"))
    assert out.verdict is Verdict.PASS


def test_a_design_that_does_not_name_a_shared_path_bounces_to_design() -> None:
    out = pipe(shares.Check(listed("mock.html")), "no list\n" + FILES).evaluate(
        at("design"), Handoff("done")
    )
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "design"
    assert out.reason == shares.UNNAMED.format(file="docs/design/s1.md", path=PATH)
    assert out.reason.endswith("list it under ## Shared files")


def test_a_missing_design_file_names_nothing() -> None:
    out = pipe(shares.Check(listed("mock.html")), "").evaluate(at("design"), Handoff("done"))
    assert out.verdict is Verdict.BOUNCE and PATH in out.reason


def test_each_unnamed_path_adds_a_reason() -> None:
    out = pipe(shares.Check(listed("a.html", "b.html")), f"{DESIGN}s1-a.html").evaluate(
        at("design"), Handoff("done")
    )
    assert f"{DESIGN}s1-b.html" in out.reason and f"{DESIGN}s1-a.html" not in out.reason


def test_a_story_without_shared_files_is_not_gated() -> None:
    out = pipe(shares.Check(shares.Listed()), FILES).evaluate(at("design"), Handoff("done"))
    assert out.verdict is Verdict.PASS


def test_the_design_gate_only_runs_on_done() -> None:
    out = pipe(shares.Check(listed("mock.html")), "").evaluate(
        at("design"), Handoff("blocked", "stuck")
    )
    assert "does not name the shared file" not in out.reason


def test_designed_joins_the_shared_reasons_with_the_others() -> None:
    p = pipe(shares.Check(listed("mock.html")), "")
    out = p.checks.designed(at("design"))
    assert out.verdict is Verdict.BOUNCE and PATH in out.reason


# ----- S9: briefs -------------------------------------------------------------------


def attach(rt, role: str, files: bool = True) -> SimpleNamespace:
    story = open_story(rt, "design")
    text = shares.with_entry(STORY, entry()) if files else STORY
    system.make_dirs(rt.config.stories_dir)
    system.write_text(rt.config.stories_dir / "s1.md", text)
    plan = SimpleNamespace(role=SimpleNamespace(name=role), story=story, prompt="brief")
    rt._attach_shares(plan)
    return plan


@pytest.mark.parametrize("role", ["architect", "customer-proxy"])
def test_the_roles_in_brief_notes_get_the_section(make_runtime, role: str) -> None:
    plan = attach(make_runtime(), role)
    want = shares.brief_section(shares.Listed((entry(),)), shares.Brief("s1", role))
    assert want and plan.prompt.startswith("brief\n\n## Shared files")
    assert f"- `{PATH}` (sha256 {SHA[:12]})" in plan.prompt
    assert shares.BRIEF_NOTES[role] in plan.prompt


@pytest.mark.parametrize("role", ["developer-cli", "code-reviewer", "tester"])
def test_other_roles_get_no_section(make_runtime, role: str) -> None:
    assert attach(make_runtime(), role).prompt == "brief"


def test_no_shared_files_means_no_section(make_runtime) -> None:
    assert attach(make_runtime(), "architect", files=False).prompt == "brief"


def test_a_step_with_no_story_gets_no_section(make_runtime) -> None:
    rt = make_runtime()
    plan = SimpleNamespace(role=SimpleNamespace(name="architect"), story=None, prompt="brief")
    rt._attach_shares(plan)
    assert plan.prompt == "brief"


def test_role_set_up_attaches_the_section_in_a_real_step(make_runtime) -> None:
    from .conftest import FakeQuery
    from .test_dispatch import run

    q = FakeQuery()
    rt = make_runtime(q)
    open_story(rt, "design")
    system.write_text(rt.config.stories_dir / "s1.md", shares.with_entry(STORY, entry()))
    run(rt, "architect", story="s1")
    assert "## Shared files" in q.calls[0]["prompt"]
    assert PATH in q.calls[0]["prompt"]


# ----- S11: the Proxy's reach -------------------------------------------------------


def test_order_and_prepared_carry_the_shared_paths() -> None:
    assert sandbox.Order.__dataclass_fields__["shared"].default == ()
    assert sandbox.Prepared.__dataclass_fields__["shared"].default == ()


def test_order_for_a_story_lists_its_shared_paths(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt, "acceptance")
    system.write_text(rt.config.stories_dir / "s1.md", shares.with_entry(STORY, entry()))
    order = rt._order(Environment("cli", "package"), story)
    assert order.shared == (PATH,)


def test_order_without_a_story_shares_nothing(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "acceptance")
    order = rt._order(Environment("cli", "package"), None)
    assert order.shared == ()


def prepared_with(config, shared: tuple[str, ...]) -> sandbox.Prepared:
    from pathlib import Path

    root = Path(config.repo) / ".team" / "run" / "customer" / "cli"
    env = Environment("cli", "package")
    made = sandbox.Prepared(env, sandbox.ENVIRONMENT_KINDS["package"], config.repo, root, root)
    made.shared = shared
    return made


def test_proxy_read_globs_include_each_shared_path_and_nothing_more(configured) -> None:
    from agile_team import config as config_mod

    config = config_mod.load(configured)
    base = sandbox.proxy_read_globs(config, prepared_with(config, ()))
    more = sandbox.proxy_read_globs(config, prepared_with(config, (PATH, f"{DESIGN}s1-b")))
    assert more == [*base, PATH, f"{DESIGN}s1-b"]


def test_allowed_reads_include_each_shared_path(configured) -> None:
    from agile_team import config as config_mod

    config = config_mod.load(configured)
    base = sandbox._allowed_reads(config, prepared_with(config, ()))
    more = sandbox._allowed_reads(config, prepared_with(config, (PATH,)))
    assert more == [*base, str(system.resolve(config.repo) / PATH)]


# ----- S4: the router ---------------------------------------------------------------


def test_the_router_has_a_sharer(make_runtime) -> None:
    assert isinstance(Router(make_runtime()).sharer, Sharer)


def test_a_tick_applies_shares_right_after_the_reorder_desk(make_runtime) -> None:
    rt = make_runtime()
    router = Router(rt)
    seen: list[str] = []
    router.desk.apply = lambda: seen.append("desk")  # type: ignore[method-assign]
    router.sharer.apply = lambda: seen.append("sharer")  # type: ignore[method-assign]
    router.clerk.settle = lambda: seen.append("clerk")  # type: ignore[method-assign]
    router.next_work = lambda: seen.append("work")  # type: ignore[method-assign]
    asyncio.run(router._tick())
    assert seen[:3] == ["desk", "sharer", "clerk"]


def test_a_tick_does_not_apply_shares_when_the_checkout_moved(make_runtime) -> None:
    rt = make_runtime()
    Shares(rt.config.run_dir).queue(shares.Share("", "s1", "mock.html", BYTES))
    rt.checkout_moved = lambda: True  # type: ignore[method-assign]
    assert asyncio.run(Router(rt)._tick()) is None
    assert rt.state.shares == {}
