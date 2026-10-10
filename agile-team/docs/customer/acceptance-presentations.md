# How the team presents a story for acceptance

Before a story is accepted, the team shows it to the Customer Proxy the way
you would receive it. The Integration Tester prepares the presentation, and
the Customer Proxy only uses what it is given. If something is missing or
broken, the Proxy sends the story back to the Integration Tester. It never
sets anything up itself.

## Where to find it

For story `s4`:

| Path | What it is |
|---|---|
| `.team/run/presentation/s4/PRESENTATION.md` | What to try for each acceptance criterion, and what you should see |
| `.team/run/presentation/s4/workspace/` | A ready-made project (its own git repo). For this runner, `agile-team init` has already run in it, and it holds the run files the story needs |
| `.team/run/presentation/s4/live-status.json` | When a criterion needs a live run: the real `agile-team status` output of that run |
| `.team/acceptance/s4.md` | The Customer Proxy's report: each criterion, what it did, pass or fail |

These run files are not committed. The next Integration Tester step on the
story replaces them.

## Try it yourself

Follow `PRESENTATION.md`. For example, with the runner installed:

```sh
agile-team --repo .team/run/presentation/s8/workspace status
agile-team --repo .team/run/presentation/s4/workspace dashboard --no-open --port 0
```

A presentation is self-contained. The Customer Proxy can't read your repo, so
a presentation names no repo paths. It holds copies of what you need (for
example an ADR or a protocol section) and captured command output (test and
ruff results, each with its command and exit code).

## Web deliveries are running before acceptance starts

For a delivery that runs as a service (kind `web`, such as the `dashboard`),
the runner starts it from the presentation and checks that it answers
before the e2e step passes. It does the same again before the Customer
Proxy starts. The address and the check come from `.agile-team.toml`:

```toml
[[delivery]]
name = "dashboard"
kind = "web"
prepare = "uv run --directory {repo}/agile-team/runner agile-team --repo {sandbox}/presentation/workspace dashboard --host {host} --port {port} --no-open"
url = "http://127.0.0.1:8799/"
probe = "api/snapshot"
```

`{host}` and `{port}` come from `url`, so the port is set in one place. The
service counts as up when `GET http://127.0.0.1:8799/api/snapshot` returns
200 with valid JSON within 30 seconds. While the Proxy works, its output is
in `.team/run/customer/dashboard.log`. The runner stops the service when
the Proxy's step ends.

## When a story goes back

- The e2e step does not pass until the presentation exists
  (`story s4 has no presentation: … is missing or empty`). That counts a
  round.
- For a web delivery, it also does not pass until the service answers. If
  the service fails, the reason quotes its output, for example:

  ```text
  story s4 presentation is not up: delivery 'dashboard' did not start: the start command exited with code 1 before http://127.0.0.1:8799/api/snapshot answered. Last output:
  agile-team dashboard: .agile-team.toml not found in …; run `agile-team init`
  ```

  That counts a round.
- If another program already uses the delivery's port, the story is put on
  hold without a round, and the PO tells you:
  `delivery 'dashboard' cannot start: 127.0.0.1:8799 is already in use by a process the runner did not start; stop it or change the delivery's url`.
  Stop that program (or change `url`), and the PO continues the story.
- If a story reaches acceptance without a presentation (for example, one that
  was already waiting there before this feature), or its web service doesn't
  come up for the Proxy, the runner sends it back to e2e without counting a
  round. The Proxy doesn't run, so it costs nothing.

## Onboarding outside a git repo

`agile-team init` needs a git repository:

```text
$ agile-team init --preset python --delivery package
agile-team init: not a git repository: /path/to/dir; run git init first
```

It exits with status 1.
