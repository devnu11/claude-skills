"""``group-chat``: talk to a roster of Claude roles in one shared thread.

``say``   send one message and print the replies (state persists in ``--dir``)
``chat``  read messages from stdin until EOF or ``/quit``
``log``   print the pinned decision log
``show``  print the summary and recent turns

Exit codes: 0 done, 1 a model call failed (replies that arrived are printed
first), 2 a usage problem (bad roster, bad address, bad or locked state).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .addressing import AddressError
from .backend import Backend, ClaudeBackend
from .chat import GroupChat, Limits, PartialReplyError
from .roster import RosterError, load
from .state import StateError, Store, Turn

DESCRIPTION = "Talk to a roster of Claude roles in one shared thread."
QUIT = "/quit"
EXIT_MODEL = 1
EXIT_USAGE = 2
USAGE_ERRORS = (RosterError, AddressError, StateError)


@dataclass(frozen=True)
class Io:
    """Where the CLI reads and writes, and what model backend it uses."""

    stdin: TextIO
    stdout: TextIO
    stderr: TextIO
    backend: Callable[[], Backend] = ClaudeBackend


def non_negative(text: str) -> int:
    """An argparse type: an integer >= 0."""
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return value


def parser() -> argparse.ArgumentParser:
    """The CLI's arguments and subcommands."""
    top = argparse.ArgumentParser(prog="group-chat", description=DESCRIPTION)
    top.add_argument("--roster", type=Path, required=True, help="roster TOML file")
    top.add_argument("--dir", type=Path, required=True, help="chat state directory")
    top.add_argument("--max-handoffs", type=non_negative, default=Limits.max_handoffs)
    top.add_argument("--recent-tokens", type=non_negative, default=Limits.recent_tokens)
    sub = top.add_subparsers(dest="command", required=True)
    sub.add_parser("say").add_argument("message", nargs="+")
    for name in ("chat", "log", "show"):
        sub.add_parser(name)
    return top


def build(args: argparse.Namespace, io: Io) -> GroupChat:
    """A ``GroupChat`` from the parsed arguments; the roster is validated here."""
    limits = Limits(recent_tokens=args.recent_tokens, max_handoffs=args.max_handoffs)
    return GroupChat(load(args.roster), io.backend(), Store(args.dir), limits)


def print_turns(turns: Iterable[Turn], out: TextIO) -> None:
    """Each turn as ``@speaker: text`` followed by a blank line."""
    for turn in turns:
        print(f"{turn.render()}\n", file=out)


def send(chat: GroupChat, message: str, io: Io) -> int:
    """Send one message and print what came back; the exit code for it."""
    try:
        print_turns(chat.say(message), io.stdout)
    except PartialReplyError as exc:
        print_turns(exc.replies, io.stdout)
        print(f"group-chat: model call failed: {exc}", file=io.stderr)
        return EXIT_MODEL
    return 0


def cmd_say(args: argparse.Namespace, io: Io) -> int:
    """``say``: one message."""
    return send(build(args, io), " ".join(args.message), io)


def cmd_chat(args: argparse.Namespace, io: Io) -> int:
    """``chat``: one message per stdin line; errors are reported and skipped."""
    chat = build(args, io)
    for line in io.stdin:
        message = line.strip()
        if message == QUIT:
            break
        if message:
            _send_or_warn(chat, message, io)
    return 0


def _send_or_warn(chat: GroupChat, message: str, io: Io) -> None:
    try:
        send(chat, message, io)
    except USAGE_ERRORS as exc:
        print(f"group-chat: {exc}", file=io.stderr)


def cmd_log(args: argparse.Namespace, io: Io) -> int:
    """``log``: the pinned decisions and open questions."""
    load(args.roster)
    print(Store(args.dir).load().log.render(), file=io.stdout)
    return 0


def cmd_show(args: argparse.Namespace, io: Io) -> int:
    """``show``: the summary, then the recent turns."""
    load(args.roster)
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
    """Parse ``argv``, run the command, map errors to exit codes."""
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args, io)
    except USAGE_ERRORS as exc:
        print(f"group-chat: {exc}", file=io.stderr)
        return EXIT_USAGE


def main(argv: list[str] | None = None) -> int:
    """The console entry point."""
    return run(sys.argv[1:] if argv is None else argv, Io(sys.stdin, sys.stdout, sys.stderr))
