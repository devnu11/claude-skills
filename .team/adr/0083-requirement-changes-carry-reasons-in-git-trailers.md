# ADR-0083: Requirement changes carry their reasons in git trailers

Story: s2. Design: `agile-team/docs/design/s2.md`. Builds on ADR-0060.

## Context

s1 (ADR-0060) made requirements into files and made the design gate trace
every AC to one. Nothing recorded why a requirement changed. When the
architect edited or retired one, the stories that traced it and had already
been designed went on against the old text, and stories already done were
never checked again. The human wants to see how requirements changed over
time, with a reason for each change, and to trust that work in flight
follows the current requirements. The dashboard (s4 D6) already reads
`requirement-changed` events as a requirement's history. It expected s2 to
add the commit sha.

## Decision

1. **Git is the only store.** The step commit's message ends with one
   trailer block: one `Requirement-Changed: <id>: <reason>` line per
   requirement the step added, changed or retired, then the usual
   `Co-Authored-By`. All of these lines sit in one paragraph, so
   `git log %(trailers)` reads them. There is no new file and no new state
   field. `agile-team requirements log` reads the trailers back, and an
   event per change (with the sha) feeds the dashboard, which reads no git.
2. **The diff classifies.** `git diff --name-status --no-renames` over the
   step's in-scope `REQ-*.md` files, plus untracked files as added, sorts
   them into added, changed and retired. Retired means a status flipped to
   `retired`, or a file removed. The write scope decides which steps have
   candidates. The code has no role check.
3. **A change needs a reason. If it has none, its edit is held back.** The
   handoff's `requirement_changes` maps ids to reasons. An added requirement
   gets `new requirement` when it has no reason. A changed or retired one
   without a reason is committed alone and reverted, the same way the
   quarantine works. The step then counts as a bad handoff and bounces
   ("explain change to REQ-003"). We chose this over committing the edit
   and asking for the reason later. A later reason would land on a
   different commit, or on none if the next step changed nothing, and the
   history would have gaps. Holding the edit back keeps the rule simple:
   every requirement change in the tree has its reason in its own commit.
   The edit can be recovered from the hold-back sha.
4. **The architect is stopped first.** A new stop check, `requirements`,
   refuses an architect's `done` stop while a reason is missing. The
   architect then fixes its handoff in the same conversation, and the
   hold-back stays a rare fallback (a non-`done` handoff, a malformed one,
   or a stop allowed after 3 refusals).
5. **Auto-accept.** A changed or retired requirement sends every other open
   story that it covered, before or after the change, and that is past the
   design step, back to design with `Pipeline.redesign`. That is the same
   reset a story amend uses, so no round is counted. A note names the
   change. A done story is listed in `affected_done_stories`, and a new
   hand-over tells the PO to ask the liaison for a follow-up story
   (`request_story`). The PO never writes stories (ADR-0070).

## Consequences

- `requirements log` needs only git, and it survives rebases. It reads
  author dates, which a rebase keeps, and the shas are the current ones.
  A squash would merge trailers into one commit. The runner never squashes
  (repo rule).
- An unexplained edit costs the architect a round and a redo. The stop check
  makes that rare.
- Auto-accept can send a story back that the change didn't really affect,
  for example after a wording fix. The architect's redesign step is then
  short. We chose this over trusting a judgement nobody records.
- `with_trailer` takes optional trailer lines. Every other commit's message
  stays exactly as it was.
- A requirement edited by hand outside a step has no reason and sends no
  story back. Only step commits are tracked.
