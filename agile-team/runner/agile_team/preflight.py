"""Checks that must pass before a run starts.

Each check returns a list of failure strings so the CLI can report all of them
at once instead of stopping at the first.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import keys, system
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
    """The pre-run checks for one repo; the provider probe is injectable."""

    config: Config
    git: Git
    home: Path
    which: Which | None = None  # deprecated: system.which is the seam; removed in the e2e step
    probe: Probe = field(default=reachable)

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
        if system.environ().get(keys.ENV_VAR):
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
        """Every configured toolchain and delivery e2e command's executable is on PATH."""
        exes = {
            f"toolchain.{n}": executable_of(c) for n, c in self.config.toolchain.commands.items()
        }
        for d in self.config.deliveries:
            exes[f"delivery.{d.name}.e2e"] = executable_of(d.e2e) if d.e2e else ""
        return [
            f"{name}: `{exe}` not found on PATH"
            for name, exe in sorted(exes.items())
            if exe and (self.which or system.which)(exe) is None
        ]

    def providers(self) -> list[str]:
        """Every provider an enabled role uses has its token and answers at its URL."""
        table = self.config.providers
        used = [table[name] for name in sorted(self.used_providers()) if name in table]
        return [failure for provider in used for failure in self.provider_problems(provider)]

    def used_providers(self) -> set[str]:
        user_dir = user_roles_dir(self.home, system.environ())
        book = RoleBook.for_repo(self.config.repo, self.config.roles, user_dir)
        try:
            return {book.resolve(name).provider for name in book.enabled_names()}
        except RoleError:
            return set()  # `config check` reports the broken role

    def provider_problems(self, provider: Provider) -> list[str]:
        failures = []
        if provider.token_env and not system.environ().get(provider.token_env):
            failures.append(f"providers.{provider.name}: ${provider.token_env} is not set")
        if not self.probe(provider.base_url):
            failures.append(f"providers.{provider.name}: nothing answers at {provider.base_url}")
        return failures
