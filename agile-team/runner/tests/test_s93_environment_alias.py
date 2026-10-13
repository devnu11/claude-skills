"""s93: the old section name still loads (E1-E7), and the ``document`` kind (E11).

This is the only test file that may hold the old word.
"""

import json
import tomllib
from pathlib import Path

import pytest
import tomli_w
from agile_team import cli, dispatch, onboard, presentation, sandbox, state, system
from agile_team import config as cfg
from agile_team.config import Environment
from agile_team.gates import StoryState
from agile_team.presentation import Check, Need, Recipe

from .conftest import PY_CONFIG, FakeQuery, present
from .fake_system import FAKE_REPO, Done, FakeSystem
from .test_dispatch import open_story, run

OLD = "delivery"
ENTRY = {"name": "cli", "kind": "package", "prepare": "", "bin": ["bin"]}
WARNING = "[[delivery]] is the old name of [[environment]]; rename the section"
BOTH = "[[environment]] and [[delivery]] are both set; move every [[delivery]] into [[environment]]"


def write_config(repo: Path, **sections) -> None:
    base = {k: v for k, v in PY_CONFIG.items() if k != "environment"}
    system.write_text(repo / cfg.CONFIG_NAME, tomli_w.dumps({**base, **sections}))


def check(repo: Path, capsys) -> tuple[int, str]:
    code = cli.main(["--repo", str(repo), "config", "check"])
    return code, capsys.readouterr().out


# ----- E1-E4: the alias -------------------------------------------------------


def test_constants() -> None:
    assert cfg.ENVIRONMENT_SECTION == "environment"
    assert cfg.OLD_ENVIRONMENT_NAME == OLD
    assert cfg.RENAMED_SECTIONS == {OLD: "environment"}
    assert cfg.RENAMED_WARNING == "[[{old}]] is the old name of [[{new}]]; rename the section"
    assert cfg.BOTH_SECTIONS == (
        "[[{new}]] and [[{old}]] are both set; move every [[{old}]] into [[{new}]]"
    )


def test_new_name_loads_without_warning(configured: Path) -> None:
    write_config(configured, environment=[ENTRY])
    c = cfg.load(configured)
    assert [e.name for e in c.environments] == ["cli"]
    assert c.warnings == []


def test_old_name_loads_the_same_with_a_warning(configured: Path) -> None:
    write_config(configured, environment=[ENTRY])
    new = cfg.load(configured)
    write_config(configured, **{OLD: [ENTRY]})
    old = cfg.load(configured)
    assert old.environments == new.environments
    assert old.warnings == [WARNING]


def test_both_sections_are_a_load_error(configured: Path) -> None:
    write_config(configured, environment=[ENTRY], **{OLD: [ENTRY]})
    with pytest.raises(cfg.ConfigError) as info:
        cfg.load(configured)
    assert str(info.value) == BOTH


def test_renamed_moves_the_old_key_and_leaves_the_rest() -> None:
    assert cfg.renamed({OLD: [1], "team": {}}) == {"environment": [1], "team": {}}
    assert cfg.renamed({"environment": [1]}) == {"environment": [1]}
    assert cfg.renamed({}) == {}


def test_rename_warnings() -> None:
    assert cfg.rename_warnings({OLD: []}) == [WARNING]
    assert cfg.rename_warnings({"environment": []}) == []


def test_config_check_warns_and_exits_zero(configured: Path, capsys) -> None:
    write_config(configured, **{OLD: [ENTRY]})
    code, out = check(configured, capsys)
    assert code == 0
    assert out.splitlines() == [f"warning: {WARNING}", "config ok"]


def test_config_check_prints_warning_before_problems(configured: Path, capsys) -> None:
    write_config(configured, **{OLD: [{"name": "w", "kind": "web"}]})
    code, out = check(configured, capsys)
    lines = out.splitlines()
    assert code == 1
    assert lines[0] == f"warning: {WARNING}"
    assert lines[1].startswith("problem: ") and "needs a url" in lines[1]
    assert lines[-1] == "1 problem(s)"


def test_config_check_new_name_has_no_warning(configured: Path, capsys) -> None:
    write_config(configured, environment=[ENTRY])
    code, out = check(configured, capsys)
    assert (code, out) == (0, "config ok\n")


def test_config_check_accepts_a_bare_document_environment(configured: Path, capsys) -> None:
    write_config(configured, environment=[{"name": "review", "kind": "document"}])
    code, out = check(configured, capsys)
    assert (code, out) == (0, "config ok\n")


# ----- E5: old state loads ----------------------------------------------------


def saved_text(story: StoryState) -> str:
    st = state.RunState()
    st.stories[story.id] = story
    state.save(FAKE_REPO / "run", st)
    return system.read_text(FAKE_REPO / "run" / state.STATE_FILE)


def test_state_with_the_old_key_loads_and_saves_the_new_one() -> None:
    text = saved_text(StoryState("s1", "A", "design", environment="cli"))
    old = text.replace('"environment"', f'"{OLD}"')
    assert f'"{OLD}"' in old
    system.write_text(FAKE_REPO / "run" / state.STATE_FILE, old)
    loaded = state.load(FAKE_REPO / "run")
    assert loaded.stories["s1"].environment == "cli"
    state.save(FAKE_REPO / "run", loaded)
    again = system.read_text(FAKE_REPO / "run" / state.STATE_FILE)
    assert '"environment": "cli"' in again and f'"{OLD}"' not in again


def test_state_with_both_keys_prefers_environment() -> None:
    data = json.loads(saved_text(StoryState("s1", "A", "design", environment="new")))
    data["stories"]["s1"][OLD] = "old"
    system.write_text(FAKE_REPO / "run" / state.STATE_FILE, json.dumps(data))
    assert state.load(FAKE_REPO / "run").stories["s1"].environment == "new"


def test_story_renames_table() -> None:
    assert state.STORY_RENAMES == {OLD: "environment"}


# ----- E6: DevOps may migrate -------------------------------------------------


def test_devops_sections_hold_both_names() -> None:
    assert set(dispatch.DEVOPS_SECTIONS) == {"toolchain", "environment", OLD, "tool"}


def test_renaming_the_section_is_an_allowed_config_edit(configured: Path) -> None:
    write_config(configured, **{OLD: [ENTRY]})
    head = system.read_text(configured / cfg.CONFIG_NAME)
    write_config(configured, environment=[ENTRY])

    class Committed:
        repo = configured

        def run(self, *args: str) -> str:
            return head

    assert dispatch.config_edit_allowed(Committed())


# ----- E7: reconfigure migrates ----------------------------------------------


def test_reconfigure_rewrites_an_old_config_as_environment(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "status"), Done(0, "M .agile-team.toml\0"))
    fake.reply(("git", "check-ignore"), Done(1))
    onboard.onboard(repo, onboard.Answers("python", "package"))
    path = repo / cfg.CONFIG_NAME
    data = tomllib.loads(system.read_text(path))
    data[OLD] = [{**data.pop("environment")[0], "prepare": "make mine"}]
    system.write_text(path, tomli_w.dumps(data))
    mode = onboard.WriteMode.RECONFIGURE
    onboard.onboard(repo, onboard.Answers("python", "package", mode=mode))
    after = tomllib.loads(system.read_text(path))
    assert OLD not in after
    assert after["environment"][0]["prepare"] == "make mine"
    assert cfg.load(repo).warnings == []


# ----- E11: the document kind -------------------------------------------------

GUIDANCE = (
    "Nothing runs for this story: it changes prompts, docs or designs. The presentation's "
    "workspace holds the changed files. Read the guide and those files, and judge each "
    "criterion against them. Do not ask the human anything."
)


def test_document_kind_row() -> None:
    kind = sandbox.ENVIRONMENT_KINDS["document"]
    assert kind.tools == ("Read", "Grep", "Glob", "Write")
    assert "Bash" not in kind.tools
    assert kind.guidance == GUIDANCE


def test_document_presentation_recipe() -> None:
    assert presentation.PRESENTATIONS["document"] == Recipe(Need.WORKSPACE)
    assert presentation.PRESENTATIONS["document"].check is Check.FILES


def test_document_needs_the_guide_and_a_workspace(configured: Path) -> None:
    c = cfg.load(configured)
    c.environments = [Environment("review", "document")]
    story = StoryState("s4", "A", "e2e", sprint=1, environment="review")
    assert presentation.missing(c, story) is not None
    present(c, "s4", workspace=False)
    assert presentation.missing(c, story) is not None
    present(c, "s4")
    assert presentation.missing(c, story) is None


def test_document_liveness_passes_without_preparing(configured: Path) -> None:
    c = cfg.load(configured)
    c.environments = [Environment("review", "document")]

    def never(*_a):
        raise AssertionError("prepare must not run")

    story = StoryState("s4", "A", "e2e", sprint=1, environment="review")
    outcome = presentation.Trial(c, never).liveness(story)
    assert outcome.verdict.name == "PASS"


def test_document_acceptance_posts_no_question_and_has_no_bash(make_runtime) -> None:
    rt = make_runtime(FakeQuery("judged\n" + _done()))
    rt.config.environments = [Environment("review", "document")]
    open_story(rt, "acceptance", environment="review")
    present(rt.config)
    report = run(rt, "customer-proxy", story="s1")
    assert "question_id" not in report
    assert rt.relay.open_questions() == []
    assert "Bash" not in rt.query_fn.calls[0]["options"].tools
    assert set(rt.query_fn.calls[0]["options"].tools) <= {"Read", "Grep", "Glob", "Write"}


def test_manual_acceptance_still_posts_a_question(make_runtime) -> None:
    rt = make_runtime(FakeQuery("1. Plug in.\n" + _done()))
    rt.config.environments = [Environment("hw", "manual")]
    open_story(rt, "acceptance", environment="hw")
    present(rt.config, workspace=False)
    assert "question_id" in run(rt, "customer-proxy", story="s1")


def test_init_accepts_the_document_environment(repo: Path, capsys) -> None:
    args = ["--repo", str(repo), "init", "--preset", "python", "--environment", "document"]
    assert cli.main(args) == 0
    assert "error" not in capsys.readouterr().err.lower()


def _done() -> str:
    from .conftest import handoff

    return handoff("done")


def test_the_backlog_detail_line_labels_the_field_acceptance_environment() -> None:
    from importlib import resources

    page = system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))
    assert 'const DETAIL_LABELS = { environment: "acceptance environment" };' in page
    assert '"environment"]' in page
    assert "${DETAIL_LABELS[k] ?? k}: " in page
