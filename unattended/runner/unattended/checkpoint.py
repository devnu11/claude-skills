"""Checkpoints: a prompt run's hand-over in a fixed, script-validated schema.

With ``--resume-from checkpoint`` every run of the job is asked for structured
output (``output_format``) in ``SCHEMA``, so the run's final reply, or its
wrap-up reply, is the checkpoint: the goal, findings with evidence pointers,
what was ruled out and why, next steps, and artifact references. The runner
validates it here (``check_checkpoint``), refuses one over ``SIZE_LIMIT`` bytes,
and writes a valid one to ``checkpoint.json`` atomically with its schema
version, the run and the time. An invalid one is logged as
``checkpoint-invalid`` and the previous checkpoint is kept.

A later run starts a fresh session from the checkpoint plus the resume prompt
(and any waiting ``tell`` message), so no transcript is replayed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .limits import local
from .store import Job

CHECKPOINT_FILE = "checkpoint.json"
SCHEMA_VERSION = 1
SIZE_LIMIT = 16_384  # bytes of JSON, so a checkpoint stays a small part of the next prompt


TEXT = {"type": "string"}
TEXTS = {"type": "array", "items": TEXT}
SCHEMA = {
    "type": "object",
    "properties": {
        "goal": TEXT,
        "findings": {"type": "array", "items": {
            "type": "object", "properties": {"claim": TEXT, "evidence": TEXTS},
            "required": ["claim", "evidence"], "additionalProperties": False,
        }},
        "ruled_out": {"type": "array", "items": {
            "type": "object", "properties": {"what": TEXT, "why": TEXT},
            "required": ["what", "why"], "additionalProperties": False,
        }},
        "next_steps": TEXTS,
        "artifacts": TEXTS,
    },
    "required": ["goal", "findings", "ruled_out", "next_steps", "artifacts"],
    "additionalProperties": False,
}  # fmt: skip
OUTPUT_FORMAT = {"type": "json_schema", "schema": SCHEMA}
PYTHON_TYPES: dict[str, type] = {"object": dict, "array": list, "string": str}


def check_value(value: Any, schema: dict[str, Any]) -> list[str]:
    """Every way ``value`` breaks ``schema`` (the object, array and string subset used
    here), each as a path below ``value`` and what is wrong there."""
    if not isinstance(value, PYTHON_TYPES[schema["type"]]):
        return [f": expected {schema['type']}"]
    if schema["type"] == "array":
        items = enumerate(value)
        return [f"[{i}]{p}" for i, item in items for p in check_value(item, schema["items"])]
    if schema["type"] == "object":
        return check_object(value, schema)
    return []


def check_object(value: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Missing and unknown keys, then each property's own problems."""
    fields = schema["properties"]
    missing = [f".{key}: missing" for key in schema["required"] if key not in value]
    unknown = [f".{key}: not in the schema" for key in value if key not in fields]
    shared = sorted(fields.keys() & value.keys())
    nested = [f".{key}{p}" for key in shared for p in check_value(value[key], fields[key])]
    return missing + unknown + nested


def check_checkpoint(value: Any) -> list[str]:
    """Every problem with ``value`` as a checkpoint: the schema, then the size."""
    found = [f"${problem}" for problem in check_value(value, SCHEMA)]
    size = len(json.dumps(value).encode())
    over = [f"$: {size} bytes, over the {SIZE_LIMIT}-byte limit"] if size > SIZE_LIMIT else []
    return found + over


@dataclass(frozen=True)
class Reply:
    """A run's structured reply: which run gave it, and the value."""

    run: int
    value: Any


def save_checkpoint(job: Job, reply: Reply) -> None:
    """Write the reply as the job's checkpoint when valid; else log why and keep the old one."""
    problems = check_checkpoint(reply.value)
    if problems:
        job.event("checkpoint-invalid", {"run": reply.run, "problems": problems[:10]})
        return
    at = local(time.time()).isoformat(timespec="seconds")
    write_checkpoint(
        job, {"schema_version": SCHEMA_VERSION, "run": reply.run, "at": at, **reply.value}
    )
    job.event("checkpoint", {"run": reply.run})


def write_checkpoint(job: Job, stamped: dict[str, Any]) -> None:
    """Replace ``checkpoint.json`` atomically, so a crash never leaves half of one."""
    tmp = job.path(f".{CHECKPOINT_FILE}.tmp")
    tmp.write_text(json.dumps(stamped, indent=2))
    tmp.replace(job.path(CHECKPOINT_FILE))


def load_checkpoint(job: Job) -> dict[str, Any] | None:
    """The job's last valid checkpoint, or None before the first."""
    path = job.path(CHECKPOINT_FILE)
    return json.loads(path.read_text()) if path.is_file() else None


def build_resume_prompt(resume_prompt: str, checkpoint: dict[str, Any]) -> str:
    """The resume prompt with the checkpoint to continue from."""
    block = json.dumps(checkpoint, indent=2)
    return f"{resume_prompt}\n\nCheckpoint from the previous run (JSON):\n{block}"
