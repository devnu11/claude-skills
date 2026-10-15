"""s87 end to end: the s79 and s77 designs carry the m72 void and the amendment."""

from __future__ import annotations

import re
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[3] / "docs" / "design"


def _paragraph_with(text: str, marker: str) -> str:
    return next(p for p in text.split("\n\n") if marker in p)


def test_s79_developer_tests_only_inside_void_paragraph() -> None:
    text = (DESIGN / "s79.md").read_text()
    assert text.count("Void (m72") == 1
    void = _paragraph_with(text, "**Void (m72: no such role).**")
    rest = text.replace(void, "")
    assert "developer-tests" in void
    assert "developer-tests" not in rest


def test_s77_amendment_rows_each_have_a_why() -> None:
    text = (DESIGN / "s77.md").read_text()
    section = text.split("## Amended by s87", 1)[1].split("\n## ", 1)[0]
    for rule in ("Z1", "Z6", "Z7", "Z9"):
        row = next(r for r in section.splitlines() if r.startswith(f"| {rule} |"))
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]
        assert len(cells) == 3 and cells[2], rule
    assert len(re.findall(r"Amended by s87", text)) >= 5
