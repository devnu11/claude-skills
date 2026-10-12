# DevOps: Current context and conventions

**Last updated:** 2026-10-11 (s62 done)

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
