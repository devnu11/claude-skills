# DevOps: Current context and conventions

**Last updated:** 2026-10-10 (s26 done)

## s26: Service delivery configuration

The runner now starts and probes services before the Proxy step, so service configuration is your responsibility. Key changes:

- **Delivery `[[delivery]]` section in `.agile-team.toml`:** The `prepare` command must use placeholders `{repo}`, `{sandbox}`, `{host}`, `{port}`. Only `url` holds the port; prepare reads it via `{port}` placeholder. A `web` delivery also needs a `probe` field (path appended to `url` for liveness check).
- **Example (dashboard):** `kind = "web"`, `prepare = "uv run --directory {repo}/agile-team/runner agile-team --repo {sandbox}/presentation/workspace dashboard --host {host} --port {port} --no-open"`, `url = "http://127.0.0.1:8799/"`, `probe = "api/snapshot"`.
- **What you don't do:** Services are started by the runner's e2e gate trial and Proxy step (never by DevOps). Your config must be correct; the runner will test it.

See ADR-0013, design `agile-team/docs/design/s26.md` (rules L1–L3, DevOps change section).

## Your role: present environments

The team's Integration Tester prepares presentation files, and the runner starts services (s26). You ensure configuration files are in place and correct:
- `.agile-team.toml` [[delivery]] sections match what the tests expect
- Paths use placeholders, not literals
- Port and probe settings are right for the customer

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. Only sprint stories can proceed past acceptance. On resume, check the current sprint before your first step.
