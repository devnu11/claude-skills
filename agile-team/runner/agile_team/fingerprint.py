"""Content fingerprints that ignore whitespace and comments (s30)."""

from __future__ import annotations

import hashlib
import io
import tokenize
from pathlib import PurePosixPath

LINE_COMMENTS: dict[str, str] = {
    **dict.fromkeys((".sh", ".bash", ".rb", ".pl", ".r", ".yaml", ".yml", ".toml"), "#"),
    **dict.fromkeys(
        (
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".ts",
            ".tsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".kts",
            ".scala",
            ".swift",
            ".c",
            ".h",
            ".cc",
            ".cpp",
            ".hpp",
            ".cs",
            ".dart",
            ".php",
        ),
        "//",
    ),
    **dict.fromkeys((".sql", ".lua", ".hs"), "--"),
}
PYTHON = frozenset({".py", ".pyi"})
DROPPED = frozenset({tokenize.COMMENT, tokenize.NL})
STRUCTURAL = frozenset({tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE})


def of(path: str, text: str) -> str:
    """The sha256 hex digest of the normalised ``text`` of ``path``."""
    return hashlib.sha256(normalise(path, text).encode("utf-8")).hexdigest()


def normalise(path: str, text: str) -> str:
    """``text`` reduced to what counts as a change for the file's language."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in PYTHON:
        return _python(text)
    return _lines(text, LINE_COMMENTS.get(suffix, ""))


def _python(text: str) -> str:
    try:
        return _tokens(text)
    except (tokenize.TokenError, SyntaxError):
        return _lines(text, "#")


def _tokens(text: str) -> str:
    found = tokenize.generate_tokens(io.StringIO(text).readline)
    return "\n".join(_shown(t) for t in found if t.type not in DROPPED)


def _shown(token: tokenize.TokenInfo) -> str:
    return tokenize.tok_name[token.type] if token.type in STRUCTURAL else token.string


def _lines(text: str, marker: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(x for x in lines if x and not (marker and x.startswith(marker)))
