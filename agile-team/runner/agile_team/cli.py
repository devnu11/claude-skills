"""``agile-team`` command line: init | config check | start | status | answer | stop.

Run from the target repo's root. Every subcommand returns an exit code; errors
print ``agile-team <cmd>: <message>`` and return 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import config as config_mod
from . import gates, keys, onboard, sandbox
from . import state as state_mod
from .dispatch import QueryFn, Runtime, shell_runner
from .git_ops import Git
from .ledger import Ledger, budget_status
from .po_tools import Start, StartMode, run_po
from .preflight import Preflight
from .relay import Relay, RelayError
from .roles import ResolvedRole, RoleBook, RoleError, expand_globs

LEDGER = "ledger.jsonl"
ANSWER_FIELDS = tuple(f.name for f in fields(onboard.Answers))
Kill = Callable[[int, int], None]


class CliError(Exception):
    """A user-facing failure; the message is printed as is."""


class StopMode(StrEnum):
    """When ``agile-team stop`` takes effect."""

    AFTER_STEP = "after-step"
    NOW = "now"


@dataclass(frozen=True)
class Place:
    """Where the CLI works: the target repo and the home holding ``~/secrets``."""

    repo: Path
    home: Path

    @classmethod
    def of(cls, args: argparse.Namespace) -> Place:
        return cls(Path(args.repo), Path(args.home))


def default_query() -> QueryFn:
    from claude_agent_sdk import query

    return query


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _load_config(repo: Path) -> config_mod.Config:
    try:
        return config_mod.load(repo)
    except config_mod.ConfigError as exc:
        raise CliError(str(exc)) from exc


# ----- init --------------------------------------------------------------


def cmd_detect(args: argparse.Namespace) -> int:
    """Print the detected preset and what it would configure."""
    print_json(detection(Path(args.repo), onboard.load_presets()))
    return 0


def detection(repo: Path, presets: dict[str, Any]) -> dict[str, Any]:
    """The preset that fits ``repo``, or the known presets when none does."""
    name = onboard.detect(repo, presets)
    if name is None:
        return {"preset": None, "known": sorted(presets)}
    preset = presets[name]
    return {
        "preset": name,
        "delivery_kind": onboard.suggest_kind(repo, preset),
        "commands": preset["commands"],
        "globs": preset["globs"],
    }


def cmd_init(args: argparse.Namespace) -> int:
    """Phase A onboarding: write the config, charter and ignores, then commit."""
    repo = Path(args.repo)
    _require_init_inputs(repo, args)
    try:
        sha = onboard.onboard(repo, answers_from(args))
    except (FileExistsError, ValueError) as exc:
        raise CliError(str(exc)) from exc
    print(f"onboarded: {sha}" if sha else "nothing to change")
    return 0


def _require_init_inputs(repo: Path, args: argparse.Namespace) -> None:
    if not Git(repo).is_clean():
        raise CliError("working tree is dirty; commit or stash first")
    if not args.preset or not args.delivery_kind:
        raise CliError("--preset and --delivery are required (see --detect)")


def answers_from(args: argparse.Namespace) -> onboard.Answers:
    """The init answers; argparse dests are named after ``Answers`` fields."""
    return onboard.Answers(**{name: getattr(args, name) for name in ANSWER_FIELDS})


# ----- config check --------------------------------------------------------


def cmd_config_check(args: argparse.Namespace) -> int:
    problems = check_config(_load_config(Path(args.repo)))
    for problem in problems:
        print(f"problem: {problem}")
    print("config ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def check_config(config: config_mod.Config) -> list[str]:
    """Static config problems plus every role's resolution and glob expansion."""
    book = RoleBook.for_repo(config.repo, config.roles)
    known = config_mod.Known(book.names(), set(sandbox.DELIVERY_KINDS))
    return config_mod.validate(config, known) + _role_problems(book, config.placeholders())


def _role_problems(book: RoleBook, values: dict[str, list[str]]) -> list[str]:
    problems = []
    for name in sorted(book.names()):
        try:
            _expand_role(book.resolve(name), values)
        except RoleError as exc:
            problems.append(f"role {name}: {exc}")
    return problems


def _expand_role(role: ResolvedRole, values: dict[str, list[str]]) -> None:
    expand_globs(role.write, values)
    expand_globs(role.read, values)


# ----- start ---------------------------------------------------------------


def make_pipeline(config: config_mod.Config) -> gates.Pipeline:
    """The configured steps and round cap, with command gates run in the repo."""
    baseline = gates.load_baseline(config.repo).get("coverage")
    commands, threshold = config.toolchain.commands, config.gates.coverage
    checks = gates.Checks(commands, threshold, shell_runner(config.repo), baseline)
    return gates.Pipeline(list(config.gates.steps), config.gates.round_cap, checks)


def make_runtime(place: Place, query_fn: QueryFn) -> Runtime:
    """Wire config, roles, git, ledger, relay, state and the API key together."""
    config = _load_config(place.repo)
    locations = keys.KeyLocations(place.repo, config.team.key_file, place.home)
    return Runtime(
        config=config,
        book=RoleBook.for_repo(place.repo, config.roles),
        git=Git(place.repo),
        ledger=Ledger(config.run_dir / LEDGER),
        relay=Relay(config.run_dir),
        state=state_mod.load(config.run_dir),
        env=keys.child_env(keys.read_key(locations.resolve().path)),
        secrets=locations.secret_paths(),
        query_fn=query_fn,
        pipeline=make_pipeline(config),
    )


def start_from(args: argparse.Namespace) -> Start:
    """The PO's task and start mode; only a resume may omit the task."""
    if args.mode is not StartMode.RESUME and not args.task:
        raise CliError("--task is required unless --resume")
    return Start(args.task or "", args.mode)


def cmd_start(args: argparse.Namespace, query_fn: QueryFn | None = None) -> int:
    """Preflight, then run the Product Owner loop in the foreground."""
    place, start = Place.of(args), start_from(args)
    config = _load_config(place.repo)
    _require_preflight(config, place.home)
    runtime = make_runtime(place, query_fn or default_query())
    runtime.state.cadence = args.cadence or config.team.cadence
    return _run(runtime, start)


def _require_preflight(config: config_mod.Config, home: Path) -> None:
    failures = Preflight(config, Git(config.repo), home).run_all() + check_config(config)
    if failures:
        raise CliError("preflight failed:\n  " + "\n  ".join(failures))


def _run(runtime: Runtime, start: Start) -> int:
    with pid_file(runtime.config.run_dir):
        result = asyncio.run(run_po(runtime, start))
    print(result.text)
    return 0


@contextmanager
def pid_file(run_dir: Path) -> Iterator[None]:
    """Clear any stale stop request and record this process for ``stop --now``."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / state_mod.STOP_FILE).unlink(missing_ok=True)
    path = run_dir / state_mod.PID_FILE
    path.write_text(str(os.getpid()))
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


# ----- status / answer / stop ----------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    print_json(status_report(_load_config(Path(args.repo))))
    return 0


def status_report(config: config_mod.Config) -> dict[str, Any]:
    """Run state, open questions and budget, for the liaison."""
    st = state_mod.load(config.run_dir)
    return {
        "status": st.status,
        "cadence": st.cadence,
        "sprint": st.sprint,
        "running": (config.run_dir / state_mod.PID_FILE).exists(),
        "stories": {k: asdict(v) for k, v in st.stories.items()},
        "manager_due": st.manager_due,
        "open_questions": [asdict(m) for m in Relay(config.run_dir).open_questions()],
        "budget": budget_status(Ledger(config.run_dir / LEDGER), config.team.budget_usd),
    }


def cmd_answer(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.repo))
    try:
        Relay(config.run_dir).answer(args.id, args.text)
    except RelayError as exc:
        raise CliError(str(exc)) from exc
    print(f"answered {args.id}")
    return 0


def cmd_stop(args: argparse.Namespace, kill: Kill = os.kill) -> int:
    """Ask the runner to stop after its step; ``--now`` also signals it."""
    pid = _request_stop(Path(args.repo)) / state_mod.PID_FILE
    if args.stop is StopMode.NOW and pid.is_file():
        kill(int(pid.read_text()), signal.SIGTERM)
        print("stop requested; runner signalled")
        return 0
    print("stop requested; the team stops after the current step")
    return 0


def _request_stop(repo: Path) -> Path:
    run_dir = _load_config(repo).run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / state_mod.STOP_FILE).touch()
    return run_dir


# ----- parser ----------------------------------------------------------------

Arg = tuple[tuple[str, ...], dict[str, Any]]


@dataclass(frozen=True)
class Command:
    """One subcommand: its name, help, handler and arguments."""

    name: str
    help: str
    func: Callable[[argparse.Namespace], int]
    args: tuple[Arg, ...] = ()


GLOBAL_ARGS: tuple[Arg, ...] = (
    (("--repo",), {"default": ".", "help": "target repo root (default: cwd)"}),
    (("--home",), {"default": str(Path.home()), "help": argparse.SUPPRESS}),
)
INIT_ARGS: tuple[Arg, ...] = (
    (("--detect",), {"action": "store_const", "dest": "func", "const": cmd_detect,
                     "help": "print the detected preset and exit"}),
    (("--preset",), {}),
    (("--delivery",), {"dest": "delivery_kind", "choices": sorted(sandbox.DELIVERY_KINDS)}),
    (("--url",), {"default": "", "help": "web delivery URL"}),
    (("--docs-dir",), {"default": "docs"}),
    (("--artifacts",), {"choices": config_mod.ARTIFACT_POLICIES, "default": "committed"}),
    (("--key-file",), {"default": config_mod.DEFAULT_KEY_FILE}),
    (("--budget",), {"dest": "budget_usd", "type": float, "default": 20.0}),
    (("--cadence",), {"choices": config_mod.CADENCES, "default": "sprint"}),
    (("--reconfigure",), {"action": "store_const", "dest": "mode",
                          "const": onboard.WriteMode.RECONFIGURE,
                          "default": onboard.WriteMode.CREATE}),
)  # fmt: skip
START_ARGS: tuple[Arg, ...] = (
    (("--task",), {"help": "the task for the Product Owner"}),
    (("--cadence",), {"choices": config_mod.CADENCES}),
    (("--onboard",), {"action": "store_const", "dest": "mode", "const": StartMode.ONBOARD,
                      "default": StartMode.DELIVERY, "help": "run the onboarding sprint"}),
    (("--resume",), {"action": "store_const", "dest": "mode", "const": StartMode.RESUME,
                     "help": "continue the previous run"}),
)  # fmt: skip
STOP_ARGS: tuple[Arg, ...] = (
    (("--now",), {"action": "store_const", "dest": "stop", "const": StopMode.NOW,
                  "default": StopMode.AFTER_STEP, "help": "also SIGTERM the runner"}),
)  # fmt: skip
COMMANDS = (
    Command("init", "phase A onboarding (no API calls)", cmd_init, INIT_ARGS),
    Command("config", "validate .agile-team.toml and roles", cmd_config_check,
            ((("action",), {"choices": ["check"]}),)),
    Command("start", "run the team (blocks; run in the background)", cmd_start, START_ARGS),
    Command("status", "print run state as JSON", cmd_status),
    Command("answer", "answer a PO question", cmd_answer, ((("id",), {}), (("text",), {}))),
    Command("stop", "stop after the current step", cmd_stop, STOP_ARGS),
)  # fmt: skip


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agile-team", description=__doc__)
    _add_args(parser, GLOBAL_ARGS)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        _add_command(sub, command)
    return parser


def _add_command(sub: Any, command: Command) -> None:
    parser = sub.add_parser(command.name, help=command.help)
    _add_args(parser, command.args)
    parser.set_defaults(func=command.func)


def _add_args(parser: argparse.ArgumentParser, args: tuple[Arg, ...]) -> None:
    for flags, options in args:
        parser.add_argument(*flags, **options)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CliError, keys.KeyNotFound) as exc:
        print(f"agile-team {args.command}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
