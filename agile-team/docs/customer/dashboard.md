# The live dashboard

`agile-team dashboard` serves a web page that shows the team at work: the
board, who is briefing and handing off to whom, token spend, questions
waiting for you and requirement changes. It updates by itself as the run
moves. It only reads the run's files, so it never changes anything, and you
can start and stop it at any time.

## Start it

From the repo root (the liaison does this for you next to `start`):

```sh
agile-team dashboard
```

It prints one line and opens your browser:

```text
dashboard: http://labbox:8765/
```

| Option | Effect |
|---|---|
| `--port 8765` | The port (default 8765). `--port 0` picks a free one and prints it. |
| `--host H` | The address to listen on. By default it is every interface, so other machines on the network can open the printed URL (it uses the machine's hostname). On Windows the default is `127.0.0.1`. |
| `--no-open` | Don't open a browser (for example over SSH). |

Stop it with Ctrl-C, or by stopping the background process.

## Open it from another machine

Use the printed URL, for example `http://labbox:8765/`. If the hostname
doesn't resolve on the other machine, use the server's IP address with the
same port. There is no login, so anyone who can reach that port sees the run:
the task, the stories, the questions and the spend. It never shows API keys.
To keep it on your own machine, run `agile-team dashboard --host 127.0.0.1`.

## What you see

- **Header:** the run's status, sprint, task, spend against the budget, and
  the step that is running now.
- **Board:** a backlog column, one column per pipeline step, and done. Each
  card shows the story's rounds, plus a flag when it is blocked or waiting
  for the Manager.
- **Flow:** briefs from the Product Owner to each role, handoffs back by
  status, and questions and answers between the PO and you, next to a
  timeline of recent events.
  The flowchart is drawn by Mermaid, which the page loads from
  `cdn.jsdelivr.net`. Without internet access it shows the chart's source
  text instead, and every other tab still works.
- **Tokens:** spend by role, story or model (switch with the buttons above
  the bars), and cumulative spend over time.
- **Questions:** questions waiting for your answer (with the
  `agile-team answer` command to copy), and questions a role raised in its
  handoff.
- **Requirements:** each requirement with its status, which acceptance
  criteria it covers, and its change history with the reasons.

The page follows your system's light or dark setting. The ◐ button in the
header switches between automatic, light and dark.

## Troubleshooting

- `agile-team dashboard: cannot listen on 0.0.0.0:8765: Address already in
  use`: a dashboard is probably already running. Open its URL, or start
  another one with `--port 0`.
- The page says "reconnecting…": the server has stopped. Start it again; the
  page reconnects by itself.
- Requirements are empty: this repo has no `<docs>/requirements/REQ-*.md`
  files yet.
- A change to `.agile-team.toml` or a role file doesn't show: restart the
  dashboard. Model changes made by the Product Owner do show without a
  restart.
