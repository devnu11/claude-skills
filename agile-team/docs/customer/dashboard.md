# The live dashboard

`agile-team dashboard` serves a web page that shows the team at work: the
board, who is briefing and handing off to whom, token spend, questions
waiting for you and requirement changes. It updates by itself as the run
moves. It reads the run's files and changes only one thing: on the
**Backlog** tab you can reorder the stories outside the current sprint.
You can start and stop it at any time.

## Start it

From the repo root (the liaison does this for you next to `start`):

```sh
agile-team dashboard
```

It prints the local link, then the link for other machines, and opens the
local one in your browser:

```text
dashboard: http://localhost:8765/?token=Xq3vB9kTf0aLm2Rw8sYc1g
from other machines: http://labbox.local:8765/
```

Use the `localhost` link on the machine running the team. Only there can
the page show a desktop notification when something goes wrong (see
"Is the team working?"). Only there, with the token in the link, can you
reorder the backlog. The token is new each time the dashboard starts.

| Option | Effect |
|---|---|
| `--port 8765` | The port (default 8765). `--port 0` picks a free one and prints it. |
| `--host H` | The address to listen on. By default it is every interface, so other machines on the network can open the second link. On Windows the default is `127.0.0.1`, and only the first line is printed. |
| `--no-open` | Don't open a browser (for example over SSH). |
| `--token T` | Use `T` as the write token instead of a random one (for scripts and presentations). Without it, `[dashboard] token = "T"` in the repo's `.agile-team.toml` does the same; leave that unset in a real repo so the token stays random. |

Stop it with Ctrl-C, or by stopping the background process.

## Open it from another machine

Use the second printed link, for example `http://labbox.local:8765/`. If
the name doesn't resolve on the other machine, use the server's IP address with the
same port. There is no login, so anyone who can reach that port sees the run:
the task, the stories, the questions and the spend. It never shows API keys.
From another machine the page is read-only: reordering works only on the
machine running the team.
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
- **Backlog:** every story that isn't done, in the order the team will take
  them, in two groups: **Current sprint** and **Backlog**. Each row shows
  its position, id, title, step, status, delivery, and why it is held.
  Cancelled and held stories are labelled. A story that needs others done
  first shows `depends on s1, s5 (done)`: `(done)` marks a dependency that
  is already finished, and the story won't start until the rest are. A
  story ranked above one of its own dependencies shows a warning pill,
  for example `⚠ s2 is above s5, which it depends on`. Such a move is
  allowed, but the story will wait. The timeline's **priority** row for that
  move ends with the same `⚠` warning. Click a row to open it: the
  story file, its state (sprint, step, status, rounds, disputes, hold,
  developer, delivery, commits), links to its design, review and
  acceptance files when they exist, its spend and turns, its last 10
  events, and the open questions about it. Click again to close it.
  Backlog rows have `↑`, `↓` and `⤒` buttons, and you can drag them onto
  another Backlog row. Current-sprint rows can't be moved. A move is
  applied by the runner between steps, so the tab says
  `waiting for the runner` until then. If the order changed in the
  meantime, your move is refused and the tab asks you to reload. Once you
  have set the backlog's order, the Product Owner keeps it. It can change
  it only with a stated reason, and the reason shows in the timeline. See
  [Backlog and sprints](backlog-and-sprints.md#the-order-of-work).
  An open row ends with the story's thread (see "Discuss a story").
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
  totals: its tokens, dollars and time on one story, one sprint or the
  whole run. Tokens and dollars come from the ledger. Time is the awake time
  of the role's finished steps, shown in h and min: if you close the lid
  mid-step, the time asleep is left out. The Product Owner's box
  shows no time, because its queries are not steps. A role that is working
  now also shows `⏱ running 12 min`, which moves on each minute. Steps
  recorded before this feature have no awake clock and count their full
  wall time; a running one says `(may include sleep)`. The page
  remembers your choice. Story starts on
  the story being worked on now. Pick another in the box beside the toggle.
  Roles that have not worked on that story are dimmed: their box turns
  grey, and its text stays in place. In Sprint and Run, roles with nothing
  to show are dimmed. A box with no tokens, dollars or time in the scope
  reads `idle` instead of zeros. The chart shows only the roles your
  pipeline uses or that have worked in this run; a role's box appears when
  it starts its first step. The chart keeps its full size, with text as
  large as the rest of the page; if it is wider than the window, scroll it
  sideways. The working role's
  box also shows its tokens per minute, a sparkline, its turn number, the
  tool it is running and the step's estimated cost so far, outlined in the
  health colour.
  The flowchart is drawn by Mermaid, which the page loads from
  `cdn.jsdelivr.net`. Without internet access it shows the chart's source
  text instead, and every other tab still works.
  Handoff summaries, questions and answers in the timeline are shown with
  their Markdown formatting: headings, lists, code, tables and links. Links
  open in a new tab. Raw HTML is shown as text and never runs, and only
  `http(s)` links become links.
- **Tokens:** a bar chart by role, story or model, and cumulative spend
  over time. Above the bars, the first buttons pick the grouping (Role,
  Story, Model). The second pick the unit: **Tokens** (bars split by token
  kind), **Dollars** (one bar of cost per row) or **Time** (one bar of step
  time per row, titled "Time by", with the legend "Awake time"). A Time
  bar's tooltip gives the number of steps and the row's share of all step
  time. It also says how many of them may include sleep, if any were
  recorded before awake time was measured. Time counts agent steps only.
  The runner's own work between steps, such as gate runs, syncs and
  presentation builds, is not in it. A step cut off by a killed runner
  counts as a step but adds no time. The unit changes only that
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
  handoff. Questions and answers are shown with their Markdown formatting.
  The formatter is `markdown-it`, which the page also loads from
  `cdn.jsdelivr.net`. Without internet access the text is shown plain, line
  breaks kept.
- **Requirements:** each requirement with its status, which acceptance
  criteria it covers, and its change history with the reasons.

The page follows your system's light or dark setting. The ◐ button in the
header switches between automatic, light and dark.

## Discuss a story

Open a story's row on the Backlog tab. Under its details is the story's
thread: everything you wrote about it and every answer, oldest first, each
marked `you → PO`, `PO → you`, `you → liaison` or `liaison → you`. A story
with no messages shows `No messages yet.` Done stories have threads too.

To write, use the localhost link with the token (the same one that lets you
reorder). Type in the box (up to 4000 characters, Markdown welcome), pick
**PO** or **liaison**, and press **send**. What you are typing survives the
page's live updates. Your message shows in the thread with the next update,
within about a second.

- **To the PO:** the Product Owner reads it at its next turn, which is when
  the current step ends. A stopped run delivers it at the next
  `agile-team start --resume`. The PO answers on the thread. It treats your
  message as a conversation, like a `tell`, not as an order to change the
  plan. It sees only your new message, not the thread before it, so quote
  what it needs.
- **To the liaison:** the Claude session you started the team from is woken
  within a few seconds while it watches the run. It answers on the thread
  with `agile-team reply <story> <file>`, or it answers you in chat. This
  works while the run is stopped.

The thread's messages also appear in the Flow tab's timeline, under the
story's chip. An empty message gets `write a message first`, and a link
without the token shows the thread read-only. Example: on s12, ask the PO
"Can the export also cover CSV?" and the answer appears under s12 once the
PO's turn comes.

## The liaison's opinions

The liaison (the Claude session you started the team from) can tell you
which stories it would change: move up, move down, fold into another,
close, rescope, or ask about. You decide what to do with each one.

- **Ask for a review.** At the top of the Backlog tab, press **Ask the
  liaison to review the backlog**. The liaison is woken within a few
  seconds while it watches the run. It records an opinion on each story it
  would change, then a short summary. While you wait, the bar reads `Asked
  <time>; waiting for the liaison.` Once the summary arrives, it reads
  `Last review: <time>` with the summary below. The liaison may also give
  opinions without being asked.
- **See the suggestions.** A story with a suggestion has a `liaison:
  <kind>` badge, for example `liaison: move-up`. Tick **only suggestions**
  to list just those stories. Their `#position` and handles stay the same
  as in the full list. An opinion of `keep` means "leave it as it is" and
  gets no badge.
- **Act on one.** Expand the story to read the opinion's text and date.
  Then press **dismiss** to set it aside, or **apply** to agree with it:
  - `apply: move to the top of the backlog` (or `… bottom …`) queues a
    reorder, as if you had dragged the story there. You see its status
    (pending, applied or refused) under the opinion.
  - `apply: send to the PO` (for fold, close, scope, ask, or a move on a
    story in the current sprint) sends the opinion to the PO on the
    story's thread. The PO treats it as your request and answers there. A
    `close` still needs your say before anything is cancelled.

An opinion that has been acted on shows `dismissed` or `applied`, and you
can't act on it again. If the liaison has since given a newer opinion on
the story, you are asked to reload. Without the token the opinions are
read-only. Opinions and your acts on them also appear in the Flow tab's
timeline. Example: the liaison suggests `move-up` on s14 because s9
depends on it. Apply it and s14 goes to the top of the Backlog between
steps.

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
| green | turns are arriving, or the runner is doing its own work (for example running the tests gate, or waiting for your answer to the PO's question) |
| amber | no turn for 3 minutes while a tool runs, or for 5 minutes with none, or the heartbeat is late while a tool or the runner's own work (a gate, a sprint boundary) is running, for example `heartbeat 2 min old while runner: gate: implement on s29 for 2 min` |
| red | no turn for 10 minutes, the heartbeat is over 90 seconds old with nothing running (or over 10 minutes old whatever runs), the machine slept, the runner has died, or the run has halted (a usage limit, `stop --now`, a crash, the budget, a moved checkout, or the PO is blocked). The pill says why, for example `no turn for 11 min, heartbeat 4 min old`, `the machine slept for 11 min` or `halted: session limit, resets 9pm` |
| plain | nothing is running: idle, done, sprint end, or stopped because you ran `agile-team stop` (a stop you asked for never turns red or notifies; `stop --now` does) |

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
