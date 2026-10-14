"""s115: the ops-review step: pure parts, config, gates, handoff."""

from types import SimpleNamespace

import pytest
from agile_team import config as config_mod
from agile_team import gates, handover, ops_review, reverts, roles, story_spec
from agile_team.gates import StoryStatus, Verdict
from agile_team.ops_review import ToolingRow, ToolingVerdict

from .conftest import handoff as handoff_text

AUTO = {"ac": "AC1", "verdict": "automatic", "how": "pytest in the test command"}
ADDED = {"ac": "AC2", "verdict": "added", "how": "the e2e-web job"}
MISSING = {"ac": "AC3", "verdict": "missing", "needs": "a browser harness", "story": "s130"}
UNFILED = {"ac": "AC3", "verdict": "missing", "needs": "a browser harness"}


def rows(*raw):
    return ops_review.rows_of(list(raw))


def spec(*ids) -> story_spec.Read:
    crit = tuple(story_spec.Criterion(i, f"text {i}", "cli") for i in ids)
    return story_spec.Read(spec=story_spec.Spec("s1", "T", crit))


def make_checks(read=None, files=()):
    c = gates.Checks({"test": "T"}, 95.0, lambda _c: (0, ""))
    c.story_spec = lambda _s: read or spec("AC1", "AC2", "AC3")
    c.read = lambda f: "x" if f in files else None
    return c


def story(step="ops-review"):
    return gates.StoryState("s1", "T", step, sprint=1)


def pipe(steps=None, read=None, files=("x",)):
    checks = make_checks(read, files)
    return gates.Pipeline(steps or ["design", "ops-review", "tests", "implement"], 3, checks)


def hand(status="done", tooling=(), **kw):
    return roles.Handoff(status, tooling=rows(*tooling), **kw)


# --- config / pipeline ---------------------------------------------------


def test_step_registered() -> None:
    assert gates.STEP_ROLES["ops-review"] == "devops"
    names = list(config_mod.PIPELINE_STEPS)
    assert names.index("ops-review") == names.index("design") + 1
    assert gates.CHECKPOINT_STEPS == frozenset({"ops-review"})
    assert "ops-review" not in gates.ROUTABLE_STEPS


@pytest.mark.parametrize(
    ("listed", "expected"),
    [
        (["design", "tests", "implement"], ["design", "ops-review", "tests", "implement"]),
        (["design", "tests", "ops-review"], ["design", "ops-review", "tests"]),
        (["ops-review", "design", "tests"], ["design", "ops-review", "tests"]),
        (["tests", "implement"], ["ops-review", "tests", "implement"]),
        ([], ["ops-review"]),
    ],
)
def test_pipeline_steps(listed, expected) -> None:
    assert config_mod.pipeline_steps(listed) == expected


def test_gates_pipeline_property_leaves_steps() -> None:
    g = config_mod.Gates(steps=["design", "tests"])
    assert g.pipeline == ["design", "ops-review", "tests"]
    assert g.steps == ["design", "tests"]


def test_default_gates_pipeline_has_it_once() -> None:
    assert config_mod.Gates().pipeline.count("ops-review") == 1


def test_design_passes_into_ops_review() -> None:
    s, p = story("design"), pipe()
    p.advance(s, gates.Outcome(Verdict.PASS))
    assert s.step == "ops-review"


def test_implement_pass_never_visits_it() -> None:
    s, p = story("implement"), pipe(["design", "ops-review", "tests", "implement", "quality"])
    p.advance(s, gates.Outcome(Verdict.PASS))
    assert s.step == "quality"


def test_checkpoint_is_not_routable() -> None:
    p = pipe()
    assert p.step_for_role("devops") is None
    assert p.step_for_role("architect") == "design"


def test_back_step_skips_checkpoint() -> None:
    steps = ["design", "ops-review", "tests", "implement"]
    assert reverts.back_step(steps, "implement") == "design"
    assert reverts.back_step(steps, "design") == "design"


def test_devops_bounce_is_unroutable() -> None:
    report = {"next_role": "devops", "gate": {"verdict": "bounce"}}
    assert handover._unroutable(report)


# --- handoff -------------------------------------------------------------


def test_handoff_parses_rows() -> None:
    text = handoff_text("done", tooling=[AUTO, MISSING], changed_files=[])
    h = roles.parse_handoff(text)
    assert h.tooling[0] == ToolingRow("AC1", ToolingVerdict.AUTOMATIC, how=AUTO["how"])
    assert h.tooling[1].story == "s130" and h.tooling[1].verdict is ToolingVerdict.MISSING


def test_handoff_without_tooling_is_empty() -> None:
    assert roles.parse_handoff(handoff_text("done")).tooling == []


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        ["x"],
        [{"ac": "AC1", "verdict": "bogus", "how": "h"}],
        [{"ac": "AC1", "verdict": "automatic"}],
        [{"ac": "AC1", "verdict": "automatic", "how": ""}],
        [{"ac": "AC1", "verdict": "missing"}],
        [{"ac": "AC1", "verdict": "missing", "needs": ""}],
        [{"ac": "AC1", "verdict": "automatic", "how": 3}],
        [{"ac": 1, "verdict": "automatic", "how": "h"}],
        [{"verdict": "automatic", "how": "h"}],
        [{**MISSING, "story": 5}],
    ],
)
def test_malformed_tooling_is_a_handoff_error(bad) -> None:
    with pytest.raises(roles.HandoffError):
        roles.parse_handoff(handoff_text("done", tooling=bad))


def test_added_row_needs_changed_files() -> None:
    with pytest.raises(roles.HandoffError, match="changed_files"):
        roles.parse_handoff(handoff_text("done", tooling=[ADDED]))
    ok = roles.parse_handoff(handoff_text("done", tooling=[ADDED], changed_files=["ci.yml"]))
    assert ok.tooling[0].verdict is ToolingVerdict.ADDED


def test_handoff_report_has_tooling_only_when_not_empty() -> None:
    assert "tooling" not in roles.handoff_report(roles.Handoff("done"))
    report = roles.handoff_report(hand(tooling=[AUTO]))
    assert report["tooling"][0]["ac"] == "AC1" and report["tooling"][0]["how"] == AUTO["how"]


# --- the gate ------------------------------------------------------------


def evaluate(h, read=None, files=("x",), st=None):
    return pipe(read=read, files=files).evaluate(st or story(), h)


def test_all_automatic_passes_to_tests() -> None:
    s, p = story(), pipe()
    h = hand(tooling=[AUTO, {**AUTO, "ac": "AC2"}, {**AUTO, "ac": "AC3"}])
    out = p.evaluate(s, h)
    assert out.verdict is Verdict.PASS and "3 automatic today, 0 added now, 0 missing" in out.reason
    p.advance(s, out)
    assert s.step == "tests"


def test_added_row_passes() -> None:
    h = hand(tooling=[AUTO, ADDED, {**AUTO, "ac": "AC3"}], changed_files=["ci.yml"])
    assert evaluate(h).verdict is Verdict.PASS


def test_missing_with_known_story_passes() -> None:
    h = hand(tooling=[AUTO, {**AUTO, "ac": "AC2"}, MISSING])
    assert evaluate(h).verdict is Verdict.PASS


def test_missing_without_story_holds() -> None:
    h = hand(tooling=[AUTO, {**AUTO, "ac": "AC2"}, UNFILED])
    out = evaluate(h)
    assert out.verdict is Verdict.HOLD
    assert "AC3: a browser harness" in out.reason and "open_story" in out.reason


def test_unknown_story_bounces_to_ops_review() -> None:
    h = hand(tooling=[AUTO, {**AUTO, "ac": "AC2"}, MISSING])
    out = evaluate(h, files=())
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "ops-review"
    assert "s130" in out.reason and ".team/stories/s130.md" in out.reason


def test_self_story_bounces() -> None:
    h = hand(tooling=[AUTO, {**AUTO, "ac": "AC2"}, {**MISSING, "story": "s1"}])
    out = evaluate(h)
    assert out.verdict is Verdict.BOUNCE and "AC3 names this story" in out.reason


def test_coverage_problems_joined() -> None:
    h = hand(tooling=[AUTO, AUTO, {**AUTO, "ac": "AC9"}])
    out = evaluate(h)
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "ops-review"
    assert "AC2" in out.reason and "no row for AC2" in out.reason
    assert "AC9 is not an AC of the story file" in out.reason
    assert "AC1 has 2 rows" in out.reason and "; " in out.reason


def test_no_rows_bounces_for_every_ac() -> None:
    out = evaluate(hand())
    assert out.verdict is Verdict.BOUNCE and "no row for AC1" in out.reason


def test_story_file_problems_hold() -> None:
    out = evaluate(hand(tooling=[AUTO]), read=story_spec.Read(problems=("bad file",)))
    assert out.verdict is Verdict.HOLD and "bad file" in out.reason


@pytest.mark.parametrize("next_role", [None, "developer", "devops"])
def test_changes_requested_goes_to_design(next_role) -> None:
    s, p = story(), pipe()
    h = roles.Handoff("changes_requested", summary="no harness can exist", next_role=next_role)
    out = p.evaluate(s, h)
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "design"
    assert out.reason == "no harness can exist"
    p.advance(s, out)
    assert s.step == "design" and s.rounds == 1 and s.status is not StoryStatus.DONE


def test_changes_requested_without_summary_or_design_step() -> None:
    p = pipe(["ops-review", "tests"])
    out = p.evaluate(story(), roles.Handoff("changes_requested"))
    assert out.bounce_to == "ops-review" and out.reason == ops_review.REDESIGN
    assert p.design_step() == "ops-review"
    assert pipe().design_step() == "design"


# --- pure module ---------------------------------------------------------


def test_section_text() -> None:
    text = ops_review.section(rows(AUTO, ADDED, MISSING))
    assert text == (
        "## Tooling\n\n"
        "How each AC is checked automatically (DevOps, ops-review step):\n\n"
        "- AC1: automatic today: pytest in the test command\n"
        "- AC2: added now: the e2e-web job\n"
        "- AC3: missing: a browser harness (story s130)\n"
    )


def test_with_section_appends_and_replaces_in_place() -> None:
    new = rows(AUTO)
    appended = ops_review.with_section("body\n", new)
    assert appended == "body\n\n" + ops_review.section(new)
    old = "body\n\n## Tooling\n\nold line\n\n## Reverted\n\nkept\n"
    out = ops_review.with_section(old, new)
    assert out == "body\n\n" + ops_review.section(new) + "\n## Reverted\n\nkept\n"
    assert ops_review.with_section(out, new) == out


def test_story_file() -> None:
    assert ops_review.story_file("s9") == f"{config_mod.STORIES_DIR}/s9.md"


def test_unfiled_and_texts() -> None:
    r = rows(AUTO, UNFILED, MISSING)
    assert [x.ac for x in ops_review.unfiled(r)] == ["AC3"]
    assert "AC3: a browser harness" in ops_review.unfiled_text(r)
    assert ops_review.passed_text(r) == (
        "tooling recorded: 1 automatic today, 0 added now, 2 missing"
    )


def test_problems_order() -> None:
    r = rows(AUTO, AUTO, {**AUTO, "ac": "AC9"})
    assert ops_review.problems(("AC1", "AC2"), r) == [
        "no row for AC2",
        "AC9 is not an AC of the story file",
        "AC1 has 2 rows",
    ]


def make_facts(read, **kw):
    cfg = SimpleNamespace(
        toolchain=SimpleNamespace(commands={"test": "pytest"}, globs={"ci": [".github/**"]}),
        environments=[SimpleNamespace(name="cli", kind="cli")],
        tools=[SimpleNamespace(name="lint")],
    )
    return ops_review.facts(cfg, read)


def test_facts_and_brief_section() -> None:
    text = ops_review.brief_section(make_facts(spec("AC1")))
    assert text.startswith("## Ops review\n")
    assert "| AC1 | cli | text AC1 |" in text
    assert "- test: `pytest`" in text and "- cli (kind cli)" in text
    assert "- lint" in text and "- .github/**" in text


def test_brief_section_empty_lists_and_escaping() -> None:
    crit = (story_spec.Criterion("AC1", "a | b\nc", "cli"),)
    read = story_spec.Read(spec=story_spec.Spec("s1", "T", crit))
    cfg = SimpleNamespace(
        toolchain=SimpleNamespace(commands={}, globs={}), environments=[], tools=[]
    )
    text = ops_review.brief_section(ops_review.facts(cfg, read))
    assert "a \\| b c" in text and text.count("- (none)") == 4


def test_brief_section_shows_story_problem() -> None:
    text = ops_review.brief_section(make_facts(story_spec.Read(problems=("bad file",))))
    assert "The story file has problems, and the gate will hold the story: bad file" in text
    assert "| AC |" not in text
