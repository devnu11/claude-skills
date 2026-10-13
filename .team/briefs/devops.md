# DevOps: Current context and conventions

**Last updated:** 2026-10-13 (s93 done; s99 done; s103 done; s75 done)

## s93 complete: Config section [[delivery]] renamed to [[environment]] (no new runtime work)

**What changed:** The config section `[[delivery]]` is now `[[environment]]`. Old sections load as environments with a warning, and `config check` says `warning: [[delivery]] is the old name of [[environment]]; rename the section`. Both sections in one file error.

**Your work:** If you have `.agile-team.toml` with `[[delivery]]`, rename those sections to `[[environment]]`. `agile-team config check` will guide you. When you run `config edit` (WriteMode.RECONFIGURE), the old section is automatically migrated to the new one, so a full reconfig cleans it up.

**Rule E6:** `DEVOPS_SECTIONS` includes both "delivery" and "environment" so your edits that rename the section are not quarantined (a section rename is allowed by the dispatcher).

**New environment kind:** `document` (for documentation-only ACs). You cannot configure it in `.agile-team.toml`; it is defined by the runner. The proxy uses it for stories with no service to run.

No code changes to DevOps work. See design `agile-team/docs/design/s93.md` (E6 dispatch rule, E7 reconfigure migration).

## s99 complete: Repo tools are now data in config (no new runtime work)

You own `[[tool]]` entries in `.agile-team.toml`. Each tool has `name`, `description`, `command`. Names must match `[a-z0-9][a-z0-9_+-]*(\.[a-z0-9][a-z0-9_+-]*)*` and cannot clash with built-in stages (gate.*, boundary.*, env.*, presentation.*, po.*, runner-tool.*). Empty description or command is refused. Duplicate names refused. Run `agile-team tools` (new CLI command) to see the 21 built-in stages and your repo tools as JSON (built_in and repo lists). **What you don't do:** Repo tools are defined but not executed in s99. No changes to delivery or boundary configuration. A future story will execute tools by name (not guessed from command text). **Your role:** Ensure tool names are unique, descriptive, and non-conflicting. See design `agile-team/docs/design/s99.md` (RS11–RS13).

## s103 complete: Guard refusal messages standardized (no change to DevOps work)

Bash refusal messages now follow a consistent format with rule names and allowed forms (e.g., `"refused by rule 'full-suite': … Allowed: named tests, e.g. 'pytest …'"`). No change to your test scoping rule (s75), delivery configuration, or boundary fix steps. This is a clarity improvement for roles reading error messages.

## s75: Test scoping rule documented; your exemption boundary established (ADR-0039)

Your role file `agile-team/runner/agile_team/roles/devops.md` now has a `## Test runs` section (and one sentence added to `## Onboarding sprint`). The rule: **run only what proves your change, normally one named test.** Never run the full suite or a coverage run; the runner's gate does those. The exemption from s69 exists only so onboarding can record its baseline—that is the one step where you run full suite and coverage. In boundary fixes, run the failing tests the brief names; the runner re-runs full checks after. For changes to test or coverage commands themselves, say in your summary that the change waits on the runner's next check. No code change; the boundary is discipline, not enforcement. Test in `tests/test_roles.py` pins five key phrases. All ACs pass. See design `agile-team/docs/design/s75.md`, ADR-0039.

## s26: Service delivery configuration

The runner now starts and probes services before the Proxy step, so service configuration is your responsibility. Key changes:

- **Delivery `[[delivery]]` section in `.agile-team.toml`:** The `prepare` command must use placeholders `{repo}`, `{sandbox}`, `{host}`, `{port}`. Only `url` holds the port; prepare reads it via `{port}` placeholder. A `web` delivery also needs a `probe` field (path appended to `url` for liveness check).
- **Example (dashboard):** `kind = "web"`, `prepare = "uv run --directory {repo}/agile-team/runner agile-team --repo {sandbox}/presentation/workspace dashboard --host {host} --port {port} --no-open"`, `url = "http://127.0.0.1:8799/"`, `probe = "api/snapshot"`.
- **What you don't do:** Services are started by the runner's e2e gate trial and Proxy step (never by DevOps). Your config must be correct; the runner will test it.

See ADR-0013, design `agile-team/docs/design/s26.md` (rules L1–L3, DevOps change section).

## s29: Boundary fix steps

At each sprint start and end, the runner syncs and builds review branches as boundary steps. When a check fails or a rebuild conflicts, you get a fix step with a brief quoting the failure:

- **Team branch check failed:** fix it on the team branch. For this step only you may also edit source, tests, e2e tests, and config. The runner commits your work and checks again.
- **Review branch check failed:** same, fix on the team branch (not the worktree). The runner rebuilds the review branches from the team branch and checks them again.
- **Rebuild conflict:** you work in the review worktree with a cherry-pick in progress. Resolve the conflict markers in exactly the files listed. The runner records the resolution with `git rerere`, so later rebuilds reuse it.

A repeat of the same failure escalates to the Manager (via s27 escalation logic).

See ADR-0015, design `agile-team/docs/design/s29.md` (rules U9–U11, U16, DevOps role file).

## s62: CI workflows now use `uv sync --locked` and `uv run --locked`

Both `.github/workflows/agile-team.yml` and `unattended.yml` enforce locked resolution in CI:
- `uv sync --locked --dev` ensures the lock file matches pyproject.toml
- `uv run --locked …` enforces that lock file
- Any mismatch fails CI and blocks merge

This prevents lock file rewrites that would break unattended jobs using `--frozen`. No changes to your configuration or delivery setup.

See ADR-0029, design `agile-team/docs/design/s62.md` (rule F2).

## Your role: present environments

The team's Integration Tester prepares presentation files, and the runner starts services (s26). You ensure configuration files are in place and correct:
- `.agile-team.toml` [[delivery]] sections match what the tests expect
- Paths use placeholders, not literals
- Port and probe settings are right for the customer

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. Only sprint stories can proceed past acceptance. On resume, check the current sprint before your first step.
