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

## When a story goes back

- The e2e step does not pass until the presentation exists
  (`story s4 has no presentation: … is missing or empty`). That counts a
  round.
- If a story reaches acceptance without a presentation (for example, one that
  was already waiting there before this feature), the runner sends it back to
  e2e without counting a round. The Proxy doesn't run, so it costs nothing.

## Onboarding outside a git repo

`agile-team init` needs a git repository:

```text
$ agile-team init --preset python --delivery package
agile-team init: not a git repository: /path/to/dir; run git init first
```

It exits with status 1.
