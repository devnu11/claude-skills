# ADR-003: Keep each session's context small

Status: proposed (s23). Date: 2026-10-09. Design: [`../design/s23.md`](../design/s23.md).

## Context

A step's cost grows with the context it re-sends on every API call, not
with the work it does. The human asked the team to measure why the Unit
Tester's context is large, and to stop the PO's single session from growing
across a whole sprint.

All numbers below come from `.team/run/ledger.jsonl` (entries since s13 carry
`turns`) and from the role steps' SDK transcripts
(`~/.claude/projects/-Users-devans-code-claude-skills/<session>.jsonl`).
**Re-sent context per turn** means `(input + cache_read + cache_creation) /
turns`: the average prompt size per turn.

### Ledger: re-sent context per turn

| Step | Turns | Re-sent tokens | Per turn | Cost |
|---|---|---|---|---|
| unit-tester s13 r0 | 31 | 2.97M | 95.7k | $1.42 |
| unit-tester s19 r0 | 28 | 3.19M | **113.9k** | $1.63 |
| unit-tester s11 r0 | 21 | 1.59M | 75.9k | $0.79 |
| architect s13 r0 | 47 | 2.28M | 48.5k | $2.59 |
| architect s19 r0 | 70 | 4.40M | 62.9k | $4.18 |
| architect s11 r0 | 48 | 3.31M | 69.1k | $2.94 |
| developer-cli s19 r0 | 37 | 4.24M | 114.6k | $1.74 |
| product-owner (ledger line 122) | 26 | 4.17M | 160.4k | $11.99 |
| product-owner (ledger line 134) | 10 | 2.34M | 233.7k | $14.97 |

Correction to the story notes: s19's 70-turn step was the **Architect's**
design step. The s19 Unit Tester took 28 turns and re-sent 3.19M tokens.

### Transcript: where the s19 Unit Tester's 3.19M tokens went

The transcript (`f38a6890…`) has 25 API calls; their prompt sizes add up to
the ledger's 3.19M exactly. The prompt grew from 7.4k on the first call to
170k on the last. Each token added at call *k* is re-sent on every later
call, so early additions cost the most.

| Cause | Size | Re-sent | Share |
|---|---|---|---|
| System prompt and built-in tools | 7.4k from call 1 | 0.19M | 6% |
| **claude.ai connectors** (see below) | ≈43k from call 2 | ≈1.06M | **33%** |
| Design file (`design/s19.md`, 509 lines) and story, read on call 1 | ≈15k | ≈0.36M | 11% |
| Source and test reads (calls 2–8): whole modules through `cat`, one cut-off output and its re-read | ≈56k by call 9 | ≈1.13M | **35%** |
| Writing tests (Bash heredocs), Python patch scripts, test runs | ≈48k by the last call | ≈0.46M | 14% |

1. **claude.ai connectors in every role session.** After the first call the
   CLI adds an `mcp_instructions_delta` attachment. It holds the human's
   claude.ai connectors (Claude Docs, Google Docs, Google Sheets, Google
   Slides). The prompt jumps by ≈43k tokens with only ≈15k of reading to
   explain it. On s13's Unit Tester, the jump is +45k after reading only a
   story, `ls` and `git log` (≈3–4k). The runner passes `setting_sources=[]`
   and no MCP servers, but the logged-in CLI (`auth = "login"`) still loads
   the account's connectors. No role is allowed to call them, yet every
   role, and the PO, pays for them on every call.
2. **Whole-file reads and the re-reads they cause.** Call 3 ran `cat` on five
   modules (`dispatch`, `gates`, `state`, `relay`, `events`). The output was
   42.2 KB, so the CLI returned a 2 KB preview (`Output too large (42.2KB)…
   Preview (first 2KB)`). Call 4 then read four of the same modules again,
   plus `sed -n 60,640p dispatch.py`, which added 16.4k. In s13, the same
   `sed` command ran twice (transcript lines 55 and 59). s13's design was
   still inside the 1600-line `architecture.md`, so its Unit Tester grepped
   it and read lines 1325–1600.
3. **The design file.** A 509-line design is needed, but it is re-sent on
   every call. It is better kept focused, with exact signatures, so that the
   tester does not also have to read the modules.
4. **Test output is not a top cause in these steps.** s19 ran the full suite
   once, filtered through `grep … | head -8`. s13 ran one targeted run with
   `--no-cov`, and s11 one targeted run through `tail -4`.

### The PO's ledger cost looks cumulative across resumes

The PO's seven ledger entries report $1.86, $3.09, $4.75, $7.31, $7.60,
$11.99 and $14.97. That is strictly increasing, while their tokens are not.
Ledger line 87 reports **$7.60** for 750k cache reads, 6.4k
cache writes and 4.6k output. Even at Opus 4.1 list prices ($1.50/M cache
read, $18.75/M cache write, $75/M output), that is at most about $1.60. Role
steps always start fresh sessions, and their reported costs track their
tokens. The likely cause: the SDK's `total_cost_usd` for a resumed session
includes the session's earlier queries, so the ledger counts the PO more
than once. If so, the "$24.62 over five PO sessions" in the story notes
overstates the PO. The PO's per-turn context (160k–234k) is still the
largest of any role. This story does not change cost accounting, but fresh
PO sessions (decision 1) limit the error. Verifying and fixing it is an open
question for the human.

## Decision

1. **Renew the PO's session at boundaries.** At sprint start, and when a
   story reaches done, the runner renews the PO's session before its next
   turn. It first tries `/compact` with instructions on what to keep. It
   uses the fallback (the PO writes `.team/po/handoff.md`, and a fresh
   session starts from it plus `story_status`) only when no compact boundary
   comes back. Open questions are carried over from the inbox in code, not
   from the PO's memory.
   - Evidence that `/compact` works headless (static): the installed SDK
     (bundled CLI 2.1.286) declares a `PreCompact` hook whose
     `trigger` is `"manual" | "auto"`, with `custom_instructions`. Its
     session code handles the compact boundary's back pointer
     (`logicalParentUuid`) and `isCompactSummary` entries. A slash command
     sent as the prompt is how the SDK reaches manual compaction.
   - Live evidence: the runner checks every attempt for a `compact_boundary`
     system message and logs a `po-session` event with the path that
     worked. The first boundary after this story ships settles the question.
     The Scribe records the result here (see "Re-measure").
2. **Turn off the claude.ai connectors for every query.** Set
   `strict_mcp_config=True` (the SDK option: "only use MCP servers passed via
   `mcp_servers`") and `ENABLE_CLAUDEAI_MCP_SERVERS=false` in each query's
   environment. Servers the runner passes itself (the PO's `team` tools, the
   Customer Proxy's sandbox servers) still load.
3. **Read little, read once.** A rule in `_shared.md` for every role: Grep
   first, Read ranges with `offset`/`limit`, never `cat` source files
   through Bash, never repeat a command, and run checks quietly, keeping only
   the tail of the output. A "Work lean" section in the Unit Tester's role
   file: run only its own test files to see them fail, and write each file
   once.
4. **Focused designs.** Per-story design files (`design/<id>.md`, briefed by
   the router since s19) list the exact signatures of new and changed
   functions. Testers and developers can then work from the design instead
   of reading whole modules.
5. **Measure it all the time.** The ledger already records `turns`. The
   `step-end` event gains `turns`. The dashboard and the Manager's
   `spend_by_role` show turns per step, the latest step's turns and the
   re-sent context per turn. The Manager also gets `long_running_roles` and
   must raise each one as friction, with a proposal. There is no turn cap.

## Projection and target

For s19's Unit Tester step: removing the connectors takes ≈1.06M / 28 ≈ 38k
off each turn (113.9k → ≈76k). Targeted reads instead of whole-module `cat`
and no re-reads take off roughly 15k more. Target: **under 60k per turn** for
the Unit Tester on a comparable step (20 turns or more).

## Re-measure

To be filled in by the Scribe after the first Unit Tester step of 20 turns
or more that runs on the new code. A running runner keeps its loaded code,
so this needs `stop` and then `start --resume`. Record that step's `turns`,
re-sent tokens and context per turn from the ledger. Confirm that its
transcript has no `mcp_instructions_delta` attachment, and record which
renewal path the first `po-session` event took.

## Consequences

- One extra PO query per boundary (the compaction, or the handoff turn). It
  replaces a context that would otherwise keep growing for the rest of the
  sprint.
- If `/compact` turns out not to work headless, the runner stops trying it
  (`po_renew_path` becomes `handoff`) and logs that once.
- Roles can no longer reach the human's claude.ai connectors. None was ever
  allowed to call them.
