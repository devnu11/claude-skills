"""Shared harness for e2e tests that drive the bundled claude CLI with a scripted model.

The model asks for one Bash command, then says ``done``; the tests read back the tool result.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import claude_agent_sdk
import pytest

from .readiness import serving

PROXY_SANDBOX_PLATFORMS: tuple[str, ...] = ("darwin",)
PROXY_SANDBOX_SKIP = (
    "the Proxy's OS sandbox is verified only on macOS (Seatbelt); "
    "s60 adds linux to scripted_cli.PROXY_SANDBOX_PLATFORMS"
)
CLI_S = 600


def bundled_cli() -> Path:
    """The claude CLI bundled with claude_agent_sdk."""
    return Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"


def sse(event: str, data: dict) -> bytes:
    """One server-sent event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def message(blocks: list[dict], stop: str) -> dict:
    """A scripted assistant message."""
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "scripted",
        "content": blocks,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _block_events(i: int, block: dict) -> bytes:
    is_text = block["type"] == "text"
    start = {**block, "text": ""} if is_text else {**block, "input": {}}
    delta = (
        {"type": "text_delta", "text": block["text"]}
        if is_text
        else {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
    )
    return (
        sse(
            "content_block_start",
            {"type": "content_block_start", "index": i, "content_block": start},
        )
        + sse("content_block_delta", {"type": "content_block_delta", "index": i, "delta": delta})
        + sse("content_block_stop", {"type": "content_block_stop", "index": i})
    )


def stream(msg: dict) -> bytes:
    """The message as an SSE stream."""
    out = sse("message_start", {"type": "message_start", "message": {**msg, "content": []}})
    for i, block in enumerate(msg["content"]):
        out += _block_events(i, block)
    delta = {"stop_reason": msg["stop_reason"], "stop_sequence": None}
    out += sse(
        "message_delta", {"type": "message_delta", "delta": delta, "usage": {"output_tokens": 1}}
    )
    return out + sse("message_stop", {"type": "message_stop"})


def tool_results(body: dict) -> list[str]:
    """The tool_result texts in a request body."""
    found: list[str] = []
    for m in body.get("messages", []):
        content = m.get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_result":
                inner = block.get("content")
                found.append(inner if isinstance(inner, str) else json.dumps(inner))
    return found


def make_model(command: str, recorded: list[str]) -> type[BaseHTTPRequestHandler]:
    """A scripted model handler: one Bash tool call for ``command``, then ``done``."""

    class Model(BaseHTTPRequestHandler):
        """Scripted model: one Bash tool call, then ``done``."""

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path.endswith("count_tokens"):
                return self.reply(json.dumps({"input_tokens": 1}).encode(), "application/json")
            msg = self.answer(body)
            if body.get("stream"):
                return self.reply(stream(msg), "text/event-stream")
            self.reply(json.dumps(msg).encode(), "application/json")

        def answer(self, body: dict) -> dict:
            results = tool_results(body)
            if results:
                recorded.extend(results)
                return message([{"type": "text", "text": "done"}], "end_turn")
            if any(t.get("name") == "Bash" for t in body.get("tools") or []):
                call = {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Bash",
                    # the CLI's Bash timeout counts host sleep; the max keeps a sleep
                    # mid-run from backgrounding the command (the outer timeout bounds it)
                    "input": {
                        "command": command,
                        "description": "run the probe",
                        "timeout": 600000,
                    },
                }
                return message([call], "tool_use")
            return message([{"type": "text", "text": "ok"}], "end_turn")

        def reply(self, data: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:
            pass

    return Model


def _tail(data: bytes | None) -> str:
    """The last 60 lines of a child's captured output."""
    return "\n".join((data or b"").decode(errors="replace").splitlines()[-60:])


@dataclass(frozen=True)
class CliRun:
    """One scripted CLI run: settings, working dir, home, config dir, extra env."""

    settings: dict
    cwd: Path
    home: Path
    config_dir: Path
    env: dict[str, str] = field(default_factory=dict)


def _environment(run: CliRun, model_port: int) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(run.home),
        "CLAUDE_CONFIG_DIR": str(run.config_dir),
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{model_port}",
        "ANTHROPIC_API_KEY": "test",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        **run.env,
    }


def _cli_command(settings_path: Path) -> list[str]:
    cmd = [str(bundled_cli()), "-p", "run the probe", "--settings", str(settings_path)]
    cmd += ["--allowedTools", "Bash", "--permission-mode", "dontAsk"]
    return [*cmd, "--output-format", "json", "--max-turns", "3"]


def run_scripted(run: CliRun, command: str) -> tuple[int, list[str]]:
    """Run the bundled CLI against a model that asks for ``command`` once.

    Returns the exit code and the tool results.
    """
    recorded: list[str] = []
    model = serving(make_model(command, recorded))
    run.config_dir.parent.mkdir(parents=True, exist_ok=True)
    path = run.config_dir.parent / "settings.json"
    path.write_text(json.dumps(run.settings))
    try:
        done = subprocess.run(
            _cli_command(path),
            cwd=run.cwd,
            env=_environment(run, model.server_address[1]),
            timeout=CLI_S,
            capture_output=True,
        )
    except subprocess.TimeoutExpired as err:
        pytest.fail(
            f"the CLI ran past {CLI_S} s; stdout:\n{_tail(err.stdout)}"
            f"\nstderr:\n{_tail(err.stderr)}"
        )
    finally:
        model.shutdown()
        model.server_close()
    return done.returncode, recorded
