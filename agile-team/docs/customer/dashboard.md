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

It prints the local link, then the link for other machines, and opens the
local one in your browser:

```text
dashboard: http://localhost:8765/
from other machines: http://labbox.local:8765/
```

Use the `localhost` link on the machine running the team. Only there can
the page show a desktop notification when something goes wrong (see
"Is the team working?").

| Option | Effect |
|---|---|
| `--port 8765` | The port (default 8765). `--port 0` picks a free one and prints it. |
| `--host H` | The address to listen on. By default it is every interface, so other machines on the network can open the second link. On Windows the default is `127.0.0.1`, and only the first line is printed. |
| `--no-open` | Don't open a browser (for example over SSH). |

Stop it with Ctrl-C, or by stopping the background process.

## Open it from another machine

Use the second printed link, for example `http://labbox.local:8765/`. If
the name doesn't resolve on the other machine, use the server's IP address with the
same port. There is no login, so anyone who can reach that port sees the run:
the task, the stories, the questions and the spend. It never shows API keys.
To keep it on your own machine, run `agile-team dashboard --host 127.0.0.1`.

## What you see

- **Header:** the run's status, sprint, task, spend against the budget, and
  the live pill for the step that is running now (see "Is the team
  working?"). The spend is the same corrected figure that
  `agile-team status` shows: the Product Owner's costs from before the s25
  fix are counted once each, not as running totals. When spend reaches the
  budget, the run halts and the status reads `blocked`.
- **Board:** a backlog column, one column per pipeline step, and done. The
  board fits the window, so Done is always in view without scrolling
  sideways. A column with no stories shrinks to a narrow strip with its name
  written vertically, and the columns with stories share the rest. Every
  column lists stories in priority order, and each unfinished card shows its
  position (`#1` runs next) and its rounds. A story that cannot move shows
  `⏸ <reason>` (`questions`, `manager`, `round cap`, `needs the human` or
  `held`) and a `waits on:` line. See
  [Backlog and sprints](backlog-and-sprints.md#the-order-of-work).
- **Flow:** briefs from the Product Owner to each role, handoffs back by
  status, and questions and answers between the PO and you, next to a
  timeline of recent events. You and the customer proxy are in the top row.
  The Steering box below them holds the Product Owner and the Manager.
  Under Steering, the roles are grouped as Design, Build, Verify and
  Support. While the run is live, the role that is working now pulses, and
  each new brief, handoff, question or answer sends a dot along its arrow.
  If your system asks for reduced motion, the role glows steadily and the
  arrow lights up briefly instead.
  Above the chart, **Story / Sprint / Run** picks what each role's box
  totals: its tokens and dollars on one story, one sprint or the whole run,
  straight from the ledger. The page remembers your choice. Story starts on
  the story being worked on now. Pick another in the box beside the toggle.
  Roles that have not worked on that story are dimmed. The working role's
  box also shows its tokens per minute, a sparkline, its turn number, the
  tool it is running and the step's estimated cost so far, outlined in the
  health colour.
  The flowchart is drawn by Mermaid, which the page loads from
  `cdn.jsdelivr.net`. Without internet access it shows the chart's source
  text instead, and every other tab still works.
- **Tokens:** a bar chart by role, story or model, and cumulative spend
  over time. Above the bars, the first buttons pick the grouping (Role,
  Story, Model). The second pick the unit: **Tokens** (bars split by token
  kind) or **Dollars** (one bar of cost per row). The unit changes only that
  bar chart, and it stays as you set it while the page updates. The role and story tables also
  show **Turns/step** (average turns per step), **Last turns** (the most
  recent step's turns) and **Context/turn** (how much context each turn
  re-sends on average), next to tokens and cost. A role whose Context/turn
  climbs is reading more than its job needs. Steps from before turns were
  recorded show `—`. Each Product Owner entry is what that one PO query
  cost. In runs from before this fix, each PO entry also counted every
  earlier PO query in the same session, so older PO spend reads too high.
  ADR-004 in the skill's docs (`agile-team/docs/adr/ADR-004-po-cost-deltas.md`)
  explains how to work out the correction to subtract.
- **Questions:** questions waiting for your answer (with the
  `agile-team answer` command to copy), and questions a role raised in its
  handoff.
- **Requirements:** each requirement with its status, which acceptance
  criteria it covers, and its change history with the reasons.

The page follows your system's light or dark setting. The ◐ button in the
header switches between automatic, light and dark.

## Is the team working?

The runner, not the agents, records every turn of every step and keeps a
heartbeat file fresh. The pill in the status row turns that into one
signal, colouring its whole fill and border:

```text
● developer-cli on s29 · 3.2k/min ▂▃▅▇▆▅▃▂▁▂ · 8 s
```

That is the role and story, the team's tokens per minute, the last 10
minutes of spend, and how long ago the last turn arrived. Hover over it, or
tap it, for the step and turn number, the model that is actually answering
(it says so if that is not the configured one, for example `configured
sonnet, answering opus`), the step's tokens and estimated dollars, the tool
running now and for how long, and the time of the last turn.

| Colour | Means |
|---|---|
| green | turns are arriving, or the runner is doing its own work (for example running the tests gate) |
| amber | no turn for 3 minutes while a tool runs, or for 5 minutes with none |
| red | no turn for 10 minutes, the heartbeat is over 90 seconds old, the runner has died, or the run has halted (a usage limit, `stop --now`, a crash, the budget, a moved checkout, or the PO is blocked). The pill says why, for example `no turn for 11 min, heartbeat 4 min old` or `halted: session limit, resets 9pm` |
| plain | nothing is running: idle, done, sprint end, or waiting for your answer |

You can change these times in `.agile-team.toml` under `[health]`
(`amber_tool_s`, `amber_quiet_s`, `red_quiet_s`, `stale_s`). A step cut
short shows on the timeline as `interrupted` with its reason, such as
`exit 143 (SIGTERM)`. When it runs again after a resume, it shows `↻
restarted`.

On red, the browser tab's title starts with ⚠. On the `localhost` link the
page also shows a desktop notification. It asks your permission once, the
first time you click on the page. Browsers allow notifications only on
`localhost` or https, so over the LAN link you get only the ⚠ in the title.

## Troubleshooting

- `agile-team dashboard: cannot listen on 0.0.0.0:8765: Address already in
  use`: a dashboard is probably already running. Open its URL, or start
  another one with `--port 0`.
- No desktop notification on red: you are on the LAN link (use the
  `localhost` one), you declined the permission (allow it in the browser's
  site settings), or you have not clicked on the page yet.
- The page says "reconnecting…": the server has stopped. Start it again; the
  page reconnects by itself. If the server is still running, check any
  `REQ-*.md` file you edited by hand: `covers` must be a YAML list
  (`covers: [...]`), not a single value. A wrongly typed field stops the page from loading
  until it is fixed.
- Requirements are empty: this repo has no `<docs>/requirements/REQ-*.md`
  files yet.
- A change to `.agile-team.toml` (for example the budget, the round cap or
  the pipeline steps) shows within about a second, with no restart. While
  the file is missing or is not valid TOML, the page keeps showing the
  settings from when the dashboard started. A file that is valid but
  incomplete (for example an editor saved it half-way) loads with the
  default values until the next save. A change to a role file, or
  to `docs_dir`, needs a dashboard restart. Model changes made by the
  Product Owner show without a restart.
