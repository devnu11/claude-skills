"""s58 end to end: a sandboxed curl reaches a local service only with allowLocalBinding."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import claude_agent_sdk
import pytest
from agile_team import config as cfg
from agile_team import sandbox
from agile_team.config import Delivery

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="allowLocalBinding applies to Claude Code's macOS (Seatbelt) sandbox; "
    "the Linux bubblewrap sandbox is not verified (s58)",
)

CLI = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"


class Service(BaseHTTPRequestHandler):
    """The local service the Proxy is asked to accept: 200 ``ok``."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: Any) -> None:
        pass


def sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def message(blocks: list[dict], stop: str) -> dict:
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


def stream(msg: dict) -> bytes:
    out = sse("message_start", {"type": "message_start", "message": {**msg, "content": []}})
    for i, block in enumerate(msg["content"]):
        start = {**block, "text": ""} if block["type"] == "text" else {**block, "input": {}}
        out += sse(
            "content_block_start",
            {"type": "content_block_start", "index": i, "content_block": start},
        )
        delta = (
            {"type": "text_delta", "text": block["text"]}
            if block["type"] == "text"
            else {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        )
        out += sse(
            "content_block_delta", {"type": "content_block_delta", "index": i, "delta": delta}
        )
        out += sse("content_block_stop", {"type": "content_block_stop", "index": i})
    delta = {"stop_reason": msg["stop_reason"], "stop_sequence": None}
    out += sse(
        "message_delta", {"type": "message_delta", "delta": delta, "usage": {"output_tokens": 1}}
    )
    return out + sse("message_stop", {"type": "message_stop"})


def tool_results(body: dict) -> list[str]:
    found: list[str] = []
    for m in body.get("messages", []):
        content = m.get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_result":
                inner = block.get("content")
                found.append(inner if isinstance(inner, str) else json.dumps(inner))
    return found


def make_model(curl: str, recorded: list[str]) -> type[BaseHTTPRequestHandler]:
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
                    "input": {"command": curl, "description": "probe the service"},
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


def serve(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def service():
    server = serve(Service)
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def run_cli(
    settings: dict, prepared: sandbox.Prepared, port: int, tmp: Path
) -> tuple[int, list[str]]:
    """Run the bundled CLI against a scripted model; return its exit code and the tool results."""
    url = f"http://127.0.0.1:{port}/"
    curl = f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {url}; echo \" exit=$?\""
    recorded: list[str] = []
    model = serve(make_model(curl, recorded))
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    path = tmp / "settings.json"
    path.write_text(json.dumps(settings))
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{model.server_address[1]}",
        "ANTHROPIC_API_KEY": "test",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }
    cmd = [str(CLI), "-p", "probe the service", "--settings", str(path), "--allowedTools", "Bash"]
    cmd += ["--permission-mode", "dontAsk"]
    cmd += ["--output-format", "json", "--max-turns", "3"]
    try:
        done = subprocess.run(cmd, cwd=prepared.workdir, env=env, timeout=120, capture_output=True)
    finally:
        model.shutdown()
        model.server_close()
    return done.returncode, recorded


@pytest.fixture
def proxy(configured: Path, service: int):
    d = Delivery("dash", "web", url=f"http://127.0.0.1:{service}/")
    c = cfg.load(configured)
    c.deliveries = [d]
    prepared = sandbox.layout(c, d)
    return sandbox.os_sandbox_settings(c, prepared), prepared


def test_sandboxed_curl_reaches_service_with_local_binding(
    proxy, service: int, tmp_path: Path
) -> None:
    settings, prepared = proxy
    code, results = run_cli(settings, prepared, service, tmp_path)
    assert code == 0
    assert len(results) == 1
    assert "200 exit=0" in results[0]


def test_sandboxed_curl_fails_without_local_binding(proxy, service: int, tmp_path: Path) -> None:
    settings, prepared = proxy
    bare = copy.deepcopy(settings)
    del bare["sandbox"]["network"]
    _, results = run_cli(bare, prepared, service, tmp_path)
    assert len(results) == 1
    assert "exit=7" in results[0]
