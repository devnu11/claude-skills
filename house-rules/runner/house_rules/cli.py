"""house-rules: check the human's code rules as code.

Exit codes: 0 clean (warnings allowed), 1 new failures or a refused baseline,
2 a usage, config, baseline or git error. ``hook`` exits 2 to show Claude what it found.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .baseline import Baseline, BaselineError
from .checker import Outcome, check_sources
from .config import ConfigError, Settings, load_settings
from .hook import run_hook
from .model import Limits
from .report import RENDERERS, Format
from .rules import NEVER, RULES
from .source import Origin, Selection, SourceError, collect_sources

USAGE_ERROR = 2
type Arg = tuple[tuple[str, ...], dict[str, Any]]


class Growth(StrEnum):
    """Whether ``baseline`` may record violations it did not know."""

    REFUSE = "refuse"
    ACCEPT = "accept"


@dataclass(frozen=True)
class Command:
    """One subcommand: its name, help, handler and arguments."""

    name: str
    help: str
    handler: Callable[[argparse.Namespace], int]
    args: tuple[Arg, ...] = ()


def run_check(args: argparse.Namespace) -> int:
    """``check``: report findings in the selected files."""
    settings = load_settings(Path.cwd())
    selection = Selection(tuple(args.paths), args.changed, args.origin)
    outcome = check_sources(collect_sources(settings, selection), settings)
    print(RENDERERS[args.format](outcome))
    return outcome.status


def run_baseline(args: argparse.Namespace) -> int:
    """``baseline``: record today's failing violations; refuse growth unless accepted."""
    settings = load_settings(Path.cwd())
    outcome = check_everything(settings)
    newer = Baseline.from_findings(outcome.findings)
    growth = outcome.baseline.list_growth(newer)
    if growth and args.growth is Growth.REFUSE:
        return deny_growth(growth)
    newer.write(settings.baseline_path)
    print(f"house-rules baseline: {len(newer.entries)} entries in {settings.baseline_path}")
    return 0


def deny_growth(growth: list[str]) -> int:
    """Name what would grow the baseline, and fail."""
    heading = "house-rules baseline: refusing to record new or grown violations:"
    advice = "fix them, or rerun with --accept-new"
    print(heading, *growth, advice, sep="\n  ", file=sys.stderr)
    return 1


def check_everything(settings: Settings) -> Outcome:
    """Every selected file under the root."""
    return check_sources(collect_sources(settings, Selection()), settings)


def run_hook_command(args: argparse.Namespace) -> int:
    """``hook``: the Claude Code PostToolUse hook."""
    return run_hook(sys.stdin, sys.stderr)


def run_rules(args: argparse.Namespace) -> int:
    """``rules``: the rule table with this repo's limits."""
    settings = load_settings(Path.cwd())
    for rule in RULES:
        limits = settings.limits.get(rule.name, rule.limits)
        state = "off" if rule.name in settings.disable else describe_limits(limits)
        ruff = f" (ruff: {', '.join(rule.ruff)})" if rule.ruff else ""
        print(f"{rule.name:<19} {state:<20} {rule.summary}{ruff}")
    return 0


def describe_limits(limits: Limits) -> str:
    """``warn > 2, fail > 3``, ``fail > 0`` or ``warn > 0``."""
    if limits.fail >= NEVER:
        return f"warn > {limits.warn}"
    if limits.warn >= limits.fail:
        return f"fail > {limits.fail}"
    return f"warn > {limits.warn}, fail > {limits.fail}"


CHECK_ARGS: tuple[Arg, ...] = (
    (("paths",), {"nargs": "*", "help": "files or directories (default: the whole root)"}),
    (("--changed",), {"metavar": "BASE", "help": "only files changed against BASE"}),
    (("--staged",), {"dest": "origin", "action": "store_const", "const": Origin.STAGED,
                     "default": Origin.WORKTREE, "help": "check the staged content"}),
    (("--format",), {"type": Format, "choices": list(Format), "default": Format.TEXT}),
)  # fmt: skip
BASELINE_ARGS: tuple[Arg, ...] = (
    (("--accept-new",), {"dest": "growth", "action": "store_const", "const": Growth.ACCEPT,
                         "default": Growth.REFUSE, "help": "record new or grown violations"}),
)  # fmt: skip
COMMANDS = (
    Command("check", "check files against the rules", run_check, CHECK_ARGS),
    Command("baseline", "write or shrink the baseline", run_baseline, BASELINE_ARGS),
    Command("hook", "Claude Code PostToolUse hook: check the edited file", run_hook_command),
    Command("rules", "list the rules and this repo's limits", run_rules),
)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, built from ``COMMANDS``."""
    parser = argparse.ArgumentParser(prog="house-rules", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        subparser = commands.add_parser(command.name, help=command.help)
        for flags, options in command.args:
            subparser.add_argument(*flags, **options)
        subparser.set_defaults(handler=command.handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and run the command."""
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ConfigError, BaselineError, SourceError) as error:
        print(f"house-rules {args.command}: {error}", file=sys.stderr)
        return USAGE_ERROR
