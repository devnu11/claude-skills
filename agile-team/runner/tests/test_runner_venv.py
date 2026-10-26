"""s174: the runner's own venv is hidden from the roles and commands it starts."""

from __future__ import annotations

from agile_team import dispatch, runner_venv

from .fake_system import FakeSystem


def test_strip_venv_bin_drops_only_the_venvs_directories() -> None:
    path = "/r/.venv/bin:/p/.venv/bin:/bin"
    assert runner_venv.strip_venv_bin(path, "/r/.venv") == "/p/.venv/bin:/bin"


def test_strip_venv_bin_drops_a_scripts_directory_too() -> None:
    assert runner_venv.strip_venv_bin("/r/.venv/Scripts:/bin", "/r/.venv") == "/bin"


def test_strip_venv_bin_leaves_a_path_without_the_venv_unchanged() -> None:
    assert runner_venv.strip_venv_bin("/usr/bin:/bin", "/r/.venv") == "/usr/bin:/bin"


def test_hide_runner_venv_keeps_a_launch_path_and_other_venvs() -> None:
    inherited = {"VIRTUAL_ENV": "/r/.venv", "PATH": "/r/.venv/bin:/bin"}
    env = {"PATH": "/sandbox/bin:/r/.venv/bin:/p/.venv/bin:/bin", "K": "v"}
    hidden = runner_venv.hide_runner_venv(env, inherited)
    assert hidden == {"PATH": "/sandbox/bin:/p/.venv/bin:/bin", "K": "v", "VIRTUAL_ENV": ""}
    assert runner_venv.hide_runner_venv(env, {"PATH": "/bin"}) == env


def test_dispatch_still_names_hide_runner_venv() -> None:
    assert dispatch.hide_runner_venv is runner_venv.hide_runner_venv


def test_a_command_environment_has_no_venv_and_no_venv_bin(fake: FakeSystem) -> None:
    fake.env = {
        "VIRTUAL_ENV": "/r/.venv",
        "PATH": "/r/.venv/bin:/usr/bin",
        "HOME": "/h",
        "K": "v",
    }
    assert runner_venv.get_command_environ() == {"PATH": "/usr/bin", "HOME": "/h", "K": "v"}


def test_a_command_environment_without_a_venv_is_the_runners(fake: FakeSystem) -> None:
    fake.env = {"PATH": "/r/.venv/bin:/usr/bin", "HOME": "/h"}
    assert runner_venv.get_command_environ() == fake.env


def test_an_empty_virtual_env_is_removed_and_path_kept(fake: FakeSystem) -> None:
    fake.env = {"VIRTUAL_ENV": "", "PATH": "/r/.venv/bin:/usr/bin"}
    assert runner_venv.get_command_environ() == {"PATH": "/r/.venv/bin:/usr/bin"}
