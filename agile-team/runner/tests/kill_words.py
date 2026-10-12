"""The kill-word check (s76 J6): no repo code or script kills a process by name.

Pure: it receives ``{path: text}`` and reads nothing. The e2e test feeds it the tracked files.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

WORDS: tuple[str, ...] = ("pkill", "killall")
PATTERN = re.compile(r"\b(pkill|killall)\b")
CODE_SUFFIXES = frozenset(
    {".py", ".sh", ".bash", ".zsh", ".yml", ".yaml", ".toml", ".js", ".mjs", ".html"}
)
ALLOWED: frozenset[str] = frozenset(
    {  # repo-relative posix paths
        "agile-team/runner/agile_team/kill_check.py",  # BY_NAME, the K1 denylist
        "agile-team/runner/tests/test_kill_check.py",  # the K1 case table
        "agile-team/runner/tests/e2e/test_signal_own_groups_e2e.py",  # K1 on the real guard
        "agile-team/runner/tests/kill_words.py",  # this table
    }
)
SHEBANG = "#!"


def is_code(path: str, text: str) -> bool:
    """A code or script file: a CODE_SUFFIXES suffix, or no suffix and a ``#!`` first line."""
    suffix = PurePosixPath(path).suffix
    return suffix in CODE_SUFFIXES or (not suffix and text.startswith(SHEBANG))


def _hits(path: str, text: str) -> list[str]:
    return [
        f"{path}:{number}: {found.group(1)}"
        for number, line in enumerate(text.splitlines(), start=1)
        for found in PATTERN.finditer(line)
    ]


def offenders(files: Mapping[str, str]) -> list[str]:
    """``"<path>:<line>: <word>"`` for each use of a WORDS word in a code file not in ALLOWED."""
    checked = ((p, t) for p, t in files.items() if p not in ALLOWED and is_code(p, t))
    return [hit for path, text in checked for hit in _hits(path, text)]
