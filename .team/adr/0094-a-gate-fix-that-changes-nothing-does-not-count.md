# ADR-0094: A gate fix is tied to the commit its gate ran on, and a done that changes nothing doesn't count

Story: s187. Design: `agile-team/docs/design/s187.md` (G1 to G9).
Changes s92's settle rule ("`done` pops the head and runs no gate").

## Context

A gate fix step's brief listed the failing items and the doc paths only. It
didn't say which commit the gate failed on, or which tree the step works in.
In sprint 53 the integration-tester fixing s181's e2e failures `cd`'d into the
main checkout, which didn't hold s181's code yet. It ran the tests there, saw
them pass, and handed off `done` with no commit. The runner popped the fix as
if it had been made, so the developer ran again and failed the same way. The
repeat rule escalated, and the Manager, who never saw that the fix step had
committed nothing (its context left out `gate-fix` events and had no shas),
ruled that the runner had gated a stale commit. The failures were real.

## Decision

1. **A fix knows its gate's commit.** `Fix.gated` is the full sha of the
   head of the tree the gate judged. The runner sets it on each new fix when
   the gate routes. Every gate event the runner writes for a story step
   carries that tree's `head`.
2. **The brief names the tree.** At plan time, in the story's view, the
   runner adds a `Tree:` section to the gate fix brief. It gives the gated
   commit, the tree's path, whether the head is still that commit, and if
   not, the commits since (or that the head no longer contains it).
3. **A `done` with no commit is not a fix.** The settle turns it into a
   `route` outcome that keeps the same fix queue, with the head fix's
   `unchanged` count raised by one. No round is counted, and the story doesn't
   go back to the failing step. The reason names the role, the files and the
   gated commit, so a second empty `done` in a row has the same setback key,
   and the existing repeat rule (`repeat = 2`) escalates it to the Manager.
   No new counter or cap is added. A fix that commits is settled as before.
4. **The Manager sees the fixes.** `FixRecord` keeps `gated` and the tree's
   `head` after the step. The `repeated_setback` view adds `fix_rounds`
   (records grouped by gated commit), and its `events` include `gate-fix`.

The runner does not re-run the routed tests itself to judge an empty `done`.
The gate has no named-test runner, and the repeat rule already gives the
Manager the case after two tries.

## Consequences

- An empty `done` costs one more fix step before the Manager sees it, not a
  developer round on a story that can't pass.
- A fix role whose items really were fixed already (for example by an earlier
  fix in the queue) must hand off `changes_requested` and name what it ran.
  That sends the story back as a round, as any disagreement does today.
- Each story gate makes one more `git rev-parse HEAD`. The brief's section
  makes up to three git calls per gate fix step, at plan time only, never
  while the scheduler is picking work.
- Confining Bash to the worktree is still open. The brief tells the role
  where to run, but nothing enforces it.
- State written before s187 loads with `gated = ""`, `unchanged = 0` and
  `head = ""`. The brief then says the gate's commit wasn't recorded.
