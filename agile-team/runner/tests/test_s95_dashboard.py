"""s95 AE13: static checks of the environment pills and the `next` outcome in index.html.

Behaviour checks (rendering `envPills`) need node, so they move to e2e:
test_envpills_render_each_mark_and_fall_back (envPills output per ENV_MARKS row, the
fallback without `environments`, and the `next` activity line).
"""

from importlib import resources

from agile_team import system

PAGE = system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_env_marks_table_has_a_row_per_verdict() -> None:
    table = PAGE.split("const ENV_MARKS = {")[1].split("};")[0]
    assert 'pass: { tone: "good", mark: " ✓"' in table
    assert 'fail: { tone: "critical", mark: " ✗"' in table
    assert '"": { tone: "", mark: ""' in table
    for title in ("passed", "failed", "not tried yet"):
        assert f'title: "{title}"' in table


def test_pill_title_names_the_environment() -> None:
    assert "acceptance environment ${e.name}: ${m.title}" in PAGE


def test_the_backlog_row_and_the_board_card_use_the_pills() -> None:
    assert PAGE.count("${envPills(") == 2


def test_next_is_an_outcome_and_a_status_tone() -> None:
    assert 'next: { outcome: "tried; next environment", fill: "--s2" }' in PAGE
    assert 'next: ""' in PAGE
