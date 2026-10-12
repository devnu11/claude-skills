"""The PostToolUse hook."""

import io
import json
from pathlib import Path

from house_rules.hook import run_hook


def run(payload: object) -> tuple[int, str]:
    stderr = io.StringIO()
    code = run_hook(io.StringIO(json.dumps(payload)), stderr)
    return code, stderr.getvalue()


def write_repo(tmp_path: Path, text: str) -> Path:
    (tmp_path / ".house-rules.toml").write_text("")
    path = tmp_path / "pkg" / "shape.py"
    path.parent.mkdir()
    path.write_text(text)
    return path


def test_violating_file_blocks_with_the_finding(tmp_path: Path) -> None:
    path = write_repo(tmp_path, "def area(shape):\n    return shape\n")
    code, stderr = run({"tool_name": "Write", "tool_input": {"file_path": str(path)}})
    assert code == 2 and "pkg/shape.py:1: fail verb-name" in stderr


def test_clean_file_passes(tmp_path: Path) -> None:
    path = write_repo(tmp_path, "def compute_area(shape):\n    return shape\n")
    assert run({"tool_input": {"file_path": str(path)}}) == (0, "")


def test_non_python_missing_and_garbage_pass(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("x")
    assert run({"tool_input": {"file_path": str(tmp_path / "notes.md")}}) == (0, "")
    assert run({"tool_input": {"file_path": str(tmp_path / "gone.py")}}) == (0, "")
    assert run({}) == (0, "")
    assert run_hook(io.StringIO("not json"), io.StringIO()) == 0
    assert run(["a list"]) == (0, "")


def test_excluded_and_test_files_pass(tmp_path: Path) -> None:
    (tmp_path / ".house-rules.toml").write_text('exclude = ["gen/**"]\n')
    for name in ("gen/area.py", "tests/test_area.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("def area(shape):\n    return shape\n")
        assert run({"tool_input": {"file_path": str(tmp_path / name)}}) == (0, "")
