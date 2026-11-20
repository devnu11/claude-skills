"""A stable prompt prefix, so each run and resume reads the prompt cache instead of rewriting it.

Every prompt run asks for a system prompt that stays the same for the life of
the job (``build_system_prompt``):

- by default Claude Code's own, with ``exclude_dynamic_sections`` (the working
  directory, git status and auto-memory move to the first user message) and
  ``snapshot`` (a resumed session keeps the prompt it recorded at its start);
- with ``--system-prompt-file F``, the file's text as read at ``start``, also
  snapshotted.

The rest of the prefix (tools, MCP servers, agents, skills, plugins, model) is
whatever the settings give, so each run's init message is fingerprinted
(``note_prefix``): a ``prefix`` event holds a short hash per part and names
the parts that changed since the last run, the usual cause of a cache miss.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from claude_agent_sdk import SystemMessage

from .store import Job, Spec

PREFIX_PARTS = ("model", "tools", "mcp_servers", "agents", "skills", "plugins", "output_style")
HASH_CHARS = 12


def build_system_prompt(spec: Spec) -> dict[str, Any]:
    """The SDK ``system_prompt`` option: the job's own text, else Claude Code's, kept fixed."""
    if spec.system_prompt:
        return {"type": "custom", "prompt": spec.system_prompt, "snapshot": True}
    return {
        "type": "preset", "preset": "claude_code",
        "exclude_dynamic_sections": True, "snapshot": True,
    }  # fmt: skip


def compute_part_hashes(data: dict[str, Any]) -> dict[str, str]:
    """A short hash of each prefix part the init message reports."""
    return {part: compute_hash(data[part]) for part in PREFIX_PARTS if part in data}


def compute_hash(value: Any) -> str:
    """A short, order-stable hash of ``value`` as JSON."""
    text = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:HASH_CHARS]


def note_prefix(job: Job, message: Any) -> None:
    """At a run's init message: save the prefix's hashes and log what changed."""
    if not (isinstance(message, SystemMessage) and message.subtype == "init"):
        return
    parts = compute_part_hashes(message.data)
    before = job.load().prefix
    changed = sorted(p for p in parts if before and before.get(p) != parts[p])
    job.update(lambda st: setattr(st, "prefix", parts))
    job.event("prefix", {"parts": parts, "changed": changed})
