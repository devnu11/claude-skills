"""The OS guard (s71 P1): pure tests; the caller is faked by naming the compiled module."""

import contextlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from . import os_guard
from .os_guard import RealOsCall, World


def as_module(name: str, source: str) -> dict[str, Any]:
    """Run ``source`` as if it lived in module ``name``; returns its globals."""
    scope: dict[str, Any] = {"__name__": name}
    exec(compile(source, f"<{name}>", "exec"), scope)
    return scope


def call_audited(name: str, event: str) -> None:
    """Fire the audit hook for ``event`` from a function that belongs to module ``name``."""
    scope = as_module(name, "def go(hook, event):\n    hook(event, ())\n")
    scope["go"](os_guard.hook, event)


def call_patched(name: str, func: Callable[[], Any]) -> Any:
    """Call ``func`` from a function that belongs to module ``name``."""
    scope = as_module(name, "def go(func):\n    return func()\n")
    return scope["go"](func)


def item_at(path: str) -> Any:
    return SimpleNamespace(path=Path(path))


def test_world_of_an_e2e_path_is_real() -> None:
    assert os_guard.world_of(item_at("/r/tests/e2e/test_x_e2e.py")) is World.REAL


def test_world_of_a_legacy_name_is_real() -> None:
    name = sorted(os_guard.LEGACY)[0]
    assert os_guard.world_of(item_at(f"/r/tests/{name}")) is World.REAL


def test_world_of_a_plain_unit_file_is_fake() -> None:
    assert os_guard.world_of(item_at("/r/tests/test_state.py")) is World.FAKE


def test_legacy_names_are_test_files_that_exist() -> None:
    assert all(n.startswith("test_") and n.endswith(".py") for n in os_guard.LEGACY)
    assert "test_os_guard.py" not in os_guard.LEGACY


def test_the_message_names_the_call_and_the_way_out() -> None:
    text = os_guard.MESSAGE.format(call="open", category="filesystem")
    assert "open (filesystem)" in text
    assert "inject it, or move the test to tests/e2e/" in text
    assert text.startswith("unit test reached the real OS")


def test_real_os_call_is_not_an_exception() -> None:
    assert not issubclass(RealOsCall, Exception)
    assert issubclass(RealOsCall, BaseException)


def test_an_audited_event_from_the_code_under_test_raises() -> None:
    with pytest.raises(RealOsCall, match=r"open \(filesystem\); inject it"):
        call_audited("agile_team.x", "open")
    os_guard.reset()


def test_an_unaudited_event_is_ignored() -> None:
    call_audited("agile_team.x", "compile")


@pytest.mark.parametrize(
    "exempt",
    ["importlib._bootstrap_external", "linecache", "coverage.sqldata", "xdist.workermanage"],
)
def test_an_exempt_caller_may_make_an_audited_call(exempt: str) -> None:
    call_audited(exempt, "open")


def test_the_table_rows_name_a_category() -> None:
    categories = {"filesystem", "process", "signal", "clock", "network", "machine"}
    assert set(os_guard.AUDITED.values()) <= categories
    assert {row.category for row in os_guard.PATCHED} <= categories


def test_a_patched_pid_call_raises_for_the_tests_package() -> None:
    import os

    with pytest.raises(RealOsCall, match=r"os\.getpid \(process\)"):
        call_patched("tests.test_x", os.getpid)
    os_guard.reset()


def test_a_patched_pid_call_raises_for_the_runner() -> None:
    import os

    with pytest.raises(RealOsCall):
        call_patched("agile_team.process_groups", os.getpid)
    os_guard.reset()


def test_a_patched_call_passes_for_the_stdlib() -> None:
    import os

    assert call_patched("logging", os.getpid) > 0


def test_stat_and_sleep_and_which_are_patched() -> None:
    import os
    import shutil
    import time

    for func in (lambda: os.stat("/"), lambda: time.sleep(0), lambda: shutil.which("sh")):
        with pytest.raises(RealOsCall):
            call_patched("agile_team.x", func)
    os_guard.reset()


def test_path_exists_is_caught_through_pathlib() -> None:
    with pytest.raises(RealOsCall, match=r"os\.stat"):
        call_patched("agile_team.x", lambda: Path("/").exists())
    os_guard.reset()


def test_every_world_has_a_guard_context() -> None:
    assert set(os_guard.WORLD_CONTEXTS) == set(World)


def test_a_real_world_window_installs_no_patch() -> None:
    import os

    before = os.getpid
    with os_guard.watching(World.REAL):
        assert os.getpid is before


def test_a_swallowed_violation_still_fails_the_test() -> None:
    with (
        pytest.raises(pytest.fail.Exception, match="inject it, or move the test"),
        os_guard.watching(World.FAKE),
        contextlib.suppress(BaseException),
    ):
        call_audited("agile_team.x", "open")


def test_a_clean_body_passes_the_guard() -> None:
    with os_guard.watching(World.FAKE):
        pass


def test_the_patches_are_undone_when_the_window_closes() -> None:
    import os

    patched = os.getpid
    with os_guard.watching(World.FAKE):
        assert os.getpid is not patched
    assert os.getpid is patched
