"""``group-chat``: talk to a roster of Claude roles in one shared thread.

``say``   send one message and print the replies (state persists in ``--dir``)
``chat``  read messages from stdin until EOF or ``/quit``
``log``   print the pinned decision log
``show``  print the summary and recent turns
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .addressing import AddressError
from .backend import Backend, BackendError, ClaudeBackend
from .chat import GroupChat, Limits
from .roster import RosterError, load
from .state import Store, Turn

QUIT = "/quit"
EXIT_USAGE = 2


@dataclass(frozen=True)
class Io:
    """Where the CLI reads and writes, and what model backend it uses."""

    stdin: TextIO
    stdout: TextIO
    stderr: TextIO
    backend: Callable[[], Backend] = ClaudeBackend


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="group-chat", description=__doc__.splitlines()[0])
    top.add_argument("--roster", type=Path, required=True, help="roster TOML file")
    top.add_argument("--dir", type=Path, required=True, help="chat state directory")
    top.add_argument("--max-handoffs", type=int, default=Limits.max_handoffs)
    top.add_argument("--recent-tokens", type=int, default=Limits.recent_tokens)
    sub = top.add_subparsers(dest="command", required=True)
    sub.add_parser("say").add_argument("message", nargs="+")
    for name in ("chat", "log", "show"):
        sub.add_parser(name)
    return top


def build(args: argparse.Namespace, io: Io) -> GroupChat:
    limits = Limits(recent_tokens=args.recent_tokens, max_handoffs=args.max_handoffs)
    return GroupChat(load(args.roster), io.backend(), Store(args.dir), limits)


def print_turns(turns: Iterable[Turn], out: TextIO) -> None:
    for turn in turns:
        print(f"{turn.render()}\n", file=out)


def cmd_say(args: argparse.Namespace, io: Io) -> int:
    print_turns(build(args, io).say(" ".join(args.message)), io.stdout)
    return 0


def cmd_chat(args: argparse.Namespace, io: Io) -> int:
    chat = build(args, io)
    for line in io.stdin:
        message = line.strip()
        if message == QUIT:
            break
        if message:
            _say_or_warn(chat, message, io)
    return 0


def _say_or_warn(chat: GroupChat, message: str, io: Io) -> None:
    try:
        print_turns(chat.say(message), io.stdout)
    except AddressError as exc:
        print(f"group-chat: {exc}", file=io.stderr)


def cmd_log(args: argparse.Namespace, io: Io) -> int:
    print(Store(args.dir).load().log.render(), file=io.stdout)
    return 0


def cmd_show(args: argparse.Namespace, io: Io) -> int:
    state = Store(args.dir).load()
    print(f"--- summary ---\n{state.summary or '(none)'}\n", file=io.stdout)
    print_turns(state.turns, io.stdout)
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace, Io], int]] = {
    "say": cmd_say,
    "chat": cmd_chat,
    "log": cmd_log,
    "show": cmd_show,
}


def run(argv: list[str], io: Io) -> int:
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args, io)
    except (RosterError, AddressError, BackendError) as exc:
        print(f"group-chat: {exc}", file=io.stderr)
        return EXIT_USAGE


def main(argv: list[str] | None = None) -> int:
    return run(sys.argv[1:] if argv is None else argv, Io(sys.stdin, sys.stdout, sys.stderr))
