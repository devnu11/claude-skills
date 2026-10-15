# ADR-0079: The OS sandbox is the Proxy's read wall, proven by escape probes

**Date:** 2026-10-15 · **Story:** s12 · **Design:** `agile-team/docs/design/s12.md`

## Context

The Customer Proxy is kept from source and tests by three layers: tool globs, a Bash
hook that reads the command as text (`guard._check_tokens`), and Claude Code's OS
sandbox (Seatbelt on macOS) built by `sandbox.os_sandbox_settings`. The s7 review
found that the text hook misses `~`, `$VAR`, `$(…)`, `--opt=path`, wildcards, `cd`
and case (P1, P2, P4). No text check can match what the shell expands. The human
narrowed s12 (t101) to proving the sandbox refuses these forms, and fixing any form
that gets through.

## Decision

- The OS sandbox is the wall for the Proxy's reads. The Bash text hook stays as a
  best-effort early refusal with a clear message, and it is not extended for
  shell-expansion forms.
- One e2e test runs the bundled CLI with the real sandbox settings and a table of
  escape probes (`PROBES`). A control run without the sandbox shows that each probe
  reads the secret. With the sandbox, none may.
- A form that gets through is fixed in the sandbox settings, as data. A leak the
  settings cannot express goes back to design.
- The platforms these e2e tests run on are one tuple,
  `tests/e2e/scripted_cli.PROXY_SANDBOX_PLATFORMS`, today `("darwin",)`. s60 adds
  Linux there.
- s58's scripted-model harness moves to `tests/e2e/scripted_cli.py`, shared by both
  sandbox e2e tests.

## Consequences

- A new escape idea is one row in `PROBES`, not a new text rule in the guard.
- The proof holds only where `PROXY_SANDBOX_PLATFORMS` runs. On Linux, until s60,
  only the text hook and the tool globs are checked.
- The P1, P2 and P4 holes stay in the text hook on purpose. Its refusals are not a
  security boundary.
