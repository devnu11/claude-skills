"""Checks that must pass before a run starts.

Each check returns a list of failure strings so the CLI can report all of them
at once instead of stopping at the first.
"""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import keys
from .config import LOGIN_AUTH, Config
from .git_ops import Git
from .providers import Probe, Provider, reachable
from .roles import RoleBook, RoleError, user_roles_dir

Which = Callable[[str], str | None]


def executable_of(command: str) -> str:
    """First word of a shell command, ignoring leading ``VAR=value`` pairs."""
    words = [w for w in shlex.split(command) if "=" not in w.split("/")[0]]
    return words[0] if words else ""


@dataclass
class Preflight:
    """The pre-run checks for one repo; ``which`` is injectable for tests."""

    config: Config
    git: Git
    home: Path
    which: Which = field(default=shutil.which)
    probe: Probe = field(default=reachable)
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)

    def run_all(self) -> list[str]:
        """All preflight failures; empty means the run may start."""
        return self.clean_tree() + self.key() + self.toolchain() + self.providers()

    def clean_tree(self) -> list[str]:
        changed = self.git.changed_paths()
        if not changed:
            return []
        shown = ", ".join(changed[:5]) + (" …" if len(changed) > 5 else "")
        return [f"working tree is dirty ({shown}); commit or stash first"]

    def key(self) -> list[str]:
        """Key-file checks, or for login auth, that no API key is inherited."""
        return self.login() if self.config.team.auth == LOGIN_AUTH else self.key_file()

    def login(self) -> list[str]:
        """An inherited key would win over the login and bill a Console workspace."""
        if self.environ.get(keys.ENV_VAR):
            return [f"team.auth is login but ${keys.ENV_VAR} is set; unset it or use api-key"]
        return []

    def key_file(self) -> list[str]:
        """The key file exists, is mode 600, and is gitignored when inside the repo."""
        try:
            source = self.locations().resolve()
        except keys.KeyNotFound as exc:
            return [str(exc)]
        unignored = source.origin is keys.KeyOrigin.REPO and not self.git.is_ignored(
            self.config.team.key_file
        )
        failures = [f"{self.config.team.key_file} is not gitignored"] if unignored else []
        return failures + ([] if keys.mode_ok(source.path) else [f"{source.path} must be mode 600"])

    def locations(self) -> keys.KeyLocations:
        return keys.KeyLocations(self.config.repo, self.config.team.key_file, self.home)

    def toolchain(self) -> list[str]:
        """Every configured toolchain command's executable is on PATH."""
        exes = {name: executable_of(cmd) for name, cmd in self.config.toolchain.commands.items()}
        return [
            f"toolchain.{name}: `{exe}` not found on PATH"
            for name, exe in sorted(exes.items())
            if exe and self.which(exe) is None
        ]

    def providers(self) -> list[str]:
        """Every provider an enabled role uses has its token and answers at its URL."""
        table = self.config.providers
        used = [table[name] for name in sorted(self.used_providers()) if name in table]
        return [failure for provider in used for failure in self.provider_problems(provider)]

    def used_providers(self) -> set[str]:
        user_dir = user_roles_dir(self.home, self.environ)
        book = RoleBook.for_repo(self.config.repo, self.config.roles, user_dir)
        try:
            return {book.resolve(name).provider for name in book.enabled_names()}
        except RoleError:
            return set()  # `config check` reports the broken role

    def provider_problems(self, provider: Provider) -> list[str]:
        failures = []
        if provider.token_env and not self.environ.get(provider.token_env):
            failures.append(f"providers.{provider.name}: ${provider.token_env} is not set")
        if not self.probe(provider.base_url):
            failures.append(f"providers.{provider.name}: nothing answers at {provider.base_url}")
        return failures
